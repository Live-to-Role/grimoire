"""Interpret natural-language library queries into filters + a refined
semantic query.

Heuristic regex pass always runs (zero latency, no dependencies). If an
Anthropic or OpenAI key is configured, an LLM pass refines the result; any
failure or timeout falls back to the heuristic interpretation. Search never
blocks on LLM availability.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, asdict

import httpx

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 5.0
ANTHROPIC_MODEL = "claude-haiku-4-5"
OPENAI_MODEL = "gpt-4o-mini"


@dataclass
class Interpretation:
    semantic_query: str
    level_min: int | None = None
    level_max: int | None = None
    game_system: str | None = None
    product_type: str | None = None
    source: str = "heuristic"

    @property
    def has_filters(self) -> bool:
        return any(
            v is not None
            for v in (self.level_min, self.level_max, self.game_system, self.product_type)
        )

    def to_dict(self) -> dict:
        return asdict(self)


# --- Heuristic pass -------------------------------------------------------

# Order matters: ranges before single levels; "for Nth level characters"
# before bare "Nth level" so the whole phrase is stripped.
_LEVEL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bfor\s+(\d{1,2})(?:st|nd|rd|th)?\s*[- ]?level\s+(?:characters?|pcs?|players?)\b", re.I), "single"),
    (re.compile(r"\blevels?\s+(\d{1,2})\s*(?:-|–|—|\bto\b)\s*(\d{1,2})\b", re.I), "range"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s*[- ]?level\b", re.I), "single"),
    (re.compile(r"\blevels?\s+(\d{1,2})\b", re.I), "single"),
]

# Curated aliases mapped onto substrings of known DB game_system values.
# Key: phrase in the query; value: substring to find in a known system name.
_SYSTEM_ALIASES: dict[str, str] = {
    "dcc": "dungeon crawl",
    "dungeon crawl classics": "dungeon crawl",
    "5e": "5e",
    "fifth edition": "5e",
    "d&d": "d&d",
    "dnd": "d&d",
    "pf2e": "pathfinder 2",
    "pf2": "pathfinder 2",
    "pathfinder 2e": "pathfinder 2",
    "pathfinder": "pathfinder",
    "osr": "osr",
    "call of cthulhu": "cthulhu",
    "coc": "cthulhu",
}

# Query keyword -> product_type value (validated against known values).
# These words stay in the semantic query — they carry topical meaning too.
_TYPE_KEYWORDS: dict[str, str] = {
    "adventure": "Adventure",
    "module": "Adventure",
    "sourcebook": "Sourcebook",
    "bestiary": "Bestiary",
    "monster manual": "Bestiary",
    "setting": "Setting",
}


def _clamp_level(v) -> int | None:
    try:
        return max(0, min(30, int(v)))
    except (TypeError, ValueError):
        return None


def interpret_heuristic(
    query: str, known_systems: list[str], known_types: list[str]
) -> Interpretation:
    """Regex/alias interpretation. Pure and synchronous."""
    result = Interpretation(semantic_query=query)
    working = query

    # Levels — first matching pattern wins; strip the matched phrase.
    for pattern, kind in _LEVEL_PATTERNS:
        m = pattern.search(working)
        if m:
            if kind == "range":
                result.level_min = _clamp_level(m.group(1))
                result.level_max = _clamp_level(m.group(2))
            else:
                result.level_min = result.level_max = _clamp_level(m.group(1))
            working = (working[: m.start()] + " " + working[m.end():]).strip()
            break

    # Game system — known value verbatim first, then curated aliases. Longest
    # phrases first so "dungeon crawl classics" beats "dcc"-style prefixes.
    lowered = working.lower()
    matched_system_phrase: str | None = None
    for system in sorted(known_systems, key=len, reverse=True):
        s = (system or "").strip()
        if s and re.search(rf"\b{re.escape(s.lower())}\b", lowered):
            result.game_system = system
            matched_system_phrase = s.lower()
            break
    if result.game_system is None:
        for alias in sorted(_SYSTEM_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                target = _SYSTEM_ALIASES[alias]
                hit = next(
                    (s for s in known_systems if s and target in s.lower()), None
                )
                if hit:
                    result.game_system = hit
                    matched_system_phrase = alias
                    break
    if matched_system_phrase:
        working = re.sub(
            rf"\b{re.escape(matched_system_phrase)}\b", " ", working, flags=re.I
        ).strip()

    # Product type — sets the filter but the keyword STAYS in the query
    # ("adventure" is topical as well as categorical).
    lowered = working.lower()
    for keyword in sorted(_TYPE_KEYWORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            candidate = _TYPE_KEYWORDS[keyword]
            hit = next(
                (t for t in known_types if t and t.lower() == candidate.lower()), None
            )
            if hit:
                result.product_type = hit
                break

    working = re.sub(r"\s{2,}", " ", working).strip(" ,.-")
    result.semantic_query = working if working else query
    return result


# --- LLM refinement -------------------------------------------------------

_LLM_PROMPT = """You are a search query interpreter for a tabletop-RPG PDF library.

Convert the user's query into structured search parameters. Return ONLY a JSON object:
{{"level_min": int or null, "level_max": int or null,
  "game_system": string or null, "product_type": string or null,
  "semantic_query": "query text optimized for semantic search over book content"}}

game_system must be one of: {systems}
product_type must be one of: {types}
Use null when the query does not clearly imply a value. Keep topical words
(monsters, themes, environments) in semantic_query.

User query: {query}"""

# Tiny in-process cache: query string -> validated Interpretation
_llm_cache: dict[str, Interpretation] = {}
_LLM_CACHE_MAX = 256


def _validate_llm_result(
    data: dict,
    heuristic: Interpretation,
    known_systems: list[str],
    known_types: list[str],
) -> Interpretation:
    """Merge validated LLM output over the heuristic result. Unknown
    game_system/product_type values are dropped; levels clamped to 0-30;
    empty semantic_query keeps the heuristic one."""
    out = Interpretation(**{**heuristic.to_dict(), "source": "llm"})

    if "level_min" in data:
        out.level_min = _clamp_level(data.get("level_min"))
    if "level_max" in data:
        out.level_max = _clamp_level(data.get("level_max"))

    system = data.get("game_system")
    if isinstance(system, str):
        hit = next((s for s in known_systems if s and s.lower() == system.lower()), None)
        out.game_system = hit if hit else out.game_system
        if hit is None and system:
            out.game_system = heuristic.game_system  # never invent values
    ptype = data.get("product_type")
    if isinstance(ptype, str):
        hit = next((t for t in known_types if t and t.lower() == ptype.lower()), None)
        if hit:
            out.product_type = hit

    sq = data.get("semantic_query")
    if isinstance(sq, str) and sq.strip():
        out.semantic_query = sq.strip()
    return out


async def _call_llm(prompt: str) -> dict | None:
    """One LLM call, Anthropic preferred, OpenAI fallback. None on any failure."""
    from grimoire.processors.ai_identifier import get_setting_from_db

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "") or (
        await get_setting_from_db("anthropic_api_key") or ""
    )
    openai_key = os.getenv("OPENAI_API_KEY", "") or (
        await get_setting_from_db("openai_api_key") or ""
    )
    if not anthropic_key and not openai_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            if anthropic_key:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": ANTHROPIC_MODEL,
                        "max_tokens": 300,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                content = resp.json()["content"][0]["text"].strip()
            else:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]

        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(content[start:end + 1])
    except Exception as e:
        logger.warning("LLM query interpretation failed, using heuristics: %s", e)
        return None


async def _get_known_values(db) -> tuple[list[str], list[str]]:
    from sqlalchemy import select
    from grimoire.models import Product

    systems = [
        s for s in (await db.execute(
            select(Product.game_system).distinct().where(Product.game_system.isnot(None))
        )).scalars().all() if s
    ]
    types = [
        t for t in (await db.execute(
            select(Product.product_type).distinct().where(Product.product_type.isnot(None))
        )).scalars().all() if t
    ]
    return systems, types


async def interpret_query(db, query: str) -> Interpretation:
    """Full interpretation: heuristics always; LLM refinement when a key is
    configured (validated, cached per query, 5s timeout, silent fallback)."""
    known_systems, known_types = await _get_known_values(db)
    heuristic = interpret_heuristic(query, known_systems, known_types)

    cached = _llm_cache.get(query)
    if cached is not None:
        return cached

    data = await _call_llm(_LLM_PROMPT.format(
        systems=", ".join(known_systems[:50]) or "(none)",
        types=", ".join(known_types[:20]) or "(none)",
        query=query,
    ))
    if data is None:
        return heuristic

    result = _validate_llm_result(data, heuristic, known_systems, known_types)
    if len(_llm_cache) >= _LLM_CACHE_MAX:
        _llm_cache.clear()
    _llm_cache[query] = result
    return result
