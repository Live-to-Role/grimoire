# backend/grimoire/processors/monster_normalizer.py
"""LLM normalization of monster candidates into MonsterEntry field dicts."""

import json
import logging
import os

from grimoire.processors.monster_segmenter import Candidate
from grimoire.processors.structured_extractor import (
    extract_with_anthropic,
    extract_with_openai,
)
from grimoire.processors.system_profiles import (
    SystemProfile,
    normalize_descending_ac,
    normalize_thac0,
)
from grimoire.utils.dice import dice_average, parse_dice

logger = logging.getLogger(__name__)

NORMALIZE_PROMPT = """You are normalizing a monster stat block candidate from a tabletop RPG book.

{profile_hint}

Report values EXACTLY as printed - do not convert or invent anything. If the
text is not actually a monster/creature stat block, return {{"is_monster": false}}.

Return ONLY this JSON shape:
{{"is_monster": true, "name": str, "ac": int or null,
 "ac_style": "ascending" or "descending", "thac0": int or null,
 "hd_dice": str or null, "attacks": [{{"name": str, "bonus": int or null, "damage_dice": str or null}}],
 "move": str or null, "special_abilities": [str], "environments": [str],
 "confidence": float 0-1}}

For "environments", infer terrain/habitat tags from the descriptive prose
(e.g. "forest", "mountains", "underground", "swamp", "desert", "aquatic",
"urban", "wilderness"). Use [] if nothing is stated or implied.

Candidate text:
{text}

Return ONLY valid JSON."""

_DEFAULT_MODELS = {"openai": "gpt-4o-mini", "anthropic": "claude-haiku-4-5-20251001"}


def resolve_provider(provider: str | None = None) -> str | None:
    """Resolve which LLM provider is actually usable, given an optional explicit choice.

    Precedence: an explicit `provider` is only honored if its key is set (no
    silent fallback to a different provider); `provider=None` picks anthropic
    if its key is set, else openai if its key is set, else None. Returns None
    when nothing is usable (no key configured, or an unrecognized provider
    name), signaling "no provider available" to callers.

    This is the single source of truth for provider precedence — both
    `normalize_candidate` and the queue handler's pre-flight check call this
    so the two paths cannot drift.
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if provider is None:
        return "anthropic" if anthropic_key else "openai" if openai_key else None
    if provider == "anthropic":
        return "anthropic" if anthropic_key else None
    if provider == "openai":
        return "openai" if openai_key else None
    return None


def build_entry_from_llm(llm: dict, candidate: Candidate, profile: SystemProfile) -> dict:
    """Pure normalization + validation of LLM output into MonsterEntry fields."""
    flags: list[str] = []

    ac = llm.get("ac")
    if ac is not None and llm.get("ac_style") == "descending":
        ac = normalize_descending_ac(int(ac))
    if ac is not None and not (0 <= int(ac) <= 30):
        flags.append("ac_out_of_range")

    thac0 = llm.get("thac0")
    attacks = []
    for atk in llm.get("attacks") or []:
        bonus = atk.get("bonus")
        if bonus is None and thac0 is not None:
            bonus = normalize_thac0(int(thac0))
        damage_dice = atk.get("damage_dice")
        damage_avg = dice_average(damage_dice)
        if damage_dice and damage_avg is None:
            flags.append("damage_unparseable")
        attacks.append({
            "name": atk.get("name") or "attack",
            "bonus": bonus,
            "damage_dice": damage_dice,
            "damage_avg": damage_avg,
        })
    if not attacks:
        flags.append("no_attacks")

    hd_dice = llm.get("hd_dice")
    hp_avg = dice_average(hd_dice)
    parsed_hd = parse_dice(hd_dice)
    hd_value = float(parsed_hd[0]) if parsed_hd else None
    if hd_dice and parsed_hd is None:
        flags.append("hd_unparseable")

    return {
        "name": llm.get("name") or candidate.name_guess,
        "page_number": candidate.page,
        "system_profile": profile.id,
        "raw_text": candidate.raw_text,
        "ac": int(ac) if ac is not None else None,
        "hd_dice": hd_dice,
        "hd_value": hd_value,
        "hp_avg": hp_avg,
        "attacks": json.dumps(attacks),
        "move": llm.get("move"),
        "special_abilities": json.dumps(llm.get("special_abilities") or []),
        "environments": json.dumps(llm.get("environments") or []),
        "extraction_confidence": llm.get("confidence"),
        "flags": json.dumps(sorted(set(flags))),
        "review_status": "pending",
    }


async def normalize_candidate(
    candidate: Candidate,
    profile: SystemProfile,
    provider: str | None = None,
    model: str | None = None,
) -> dict | None:
    """Send one candidate through the LLM and normalize the result.

    Returns None when no provider is configured or the LLM rejects the
    candidate as not-a-monster. Raises on transport errors (caller flags).
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    resolved = resolve_provider(provider)

    prompt_template = NORMALIZE_PROMPT.replace("{profile_hint}", profile.prompt_hint)

    if resolved == "anthropic":
        llm = await extract_with_anthropic(
            candidate.raw_text, prompt_template, anthropic_key, model or _DEFAULT_MODELS["anthropic"]
        )
    elif resolved == "openai":
        llm = await extract_with_openai(
            candidate.raw_text, prompt_template, openai_key, model or _DEFAULT_MODELS["openai"]
        )
    else:
        logger.warning("No AI provider configured for monster normalization")
        return None

    if not llm or not llm.get("is_monster"):
        return None
    return build_entry_from_llm(llm, candidate, profile)
