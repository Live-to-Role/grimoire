"""
Structured content extraction using AI.
Extracts monsters, spells, items, and other TTRPG content into structured JSON.
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx

from grimoire.schemas.ttrpg import (
    Monster,
    Spell,
    MagicItem,
    RandomTable,
    NPC,
    ExtractedContent,
)


MONSTER_EXTRACTION_PROMPT = """Extract monster/creature stat blocks from this text into structured JSON.

For each monster found, extract:
- name, size, creature_type, alignment
- armor_class, armor_type, hit_points, hit_dice
- speed (as object with walk, fly, swim, etc.)
- abilities (strength, dexterity, constitution, intelligence, wisdom, charisma)
- saving_throws, skills (as objects with ability/skill name and modifier)
- damage_vulnerabilities, damage_resistances, damage_immunities, condition_immunities (as arrays)
- senses, languages
- challenge_rating, experience_points
- traits (array of {name, description})
- actions (array of {name, description, attack if applicable})
- bonus_actions, reactions, legendary_actions (same format as actions)

Return a JSON object with a "monsters" array containing the extracted creatures.
If no monsters are found, return {"monsters": []}.

Text to extract from:
{text}

Return ONLY valid JSON."""


SPELL_EXTRACTION_PROMPT = """Extract spell definitions from this text into structured JSON.

For each spell found, extract:
- name, level (0 for cantrips), school, ritual (boolean)
- casting_time, range, duration, concentration (boolean)
- components: {verbal, somatic, material, material_description, material_cost, material_consumed}
- description, higher_levels (at higher levels text)
- classes, subclasses (arrays)
- damage if applicable: {dice, damage_type, average}
- save (ability for saving throw)

Return a JSON object with a "spells" array containing the extracted spells.
If no spells are found, return {"spells": []}.

Text to extract from:
{text}

Return ONLY valid JSON."""


MAGIC_ITEM_PROMPT = """Extract magic item definitions from this text into structured JSON.

For each magic item found, extract:
- name, rarity (common/uncommon/rare/very rare/legendary/artifact)
- item_type (weapon, armor, wondrous item, etc.)
- requires_attunement (boolean), attunement_requirements
- description, properties (array)
- charges, recharge

Return a JSON object with a "magic_items" array containing the extracted items.
If no magic items are found, return {"magic_items": []}.

Text to extract from:
{text}

Return ONLY valid JSON."""


NPC_EXTRACTION_PROMPT = """Extract NPC (non-player character) definitions from this text into structured JSON.

For each NPC found, extract:
- name, role (shopkeeper, quest giver, villain, etc.)
- race, occupation, location
- description (physical appearance)
- personality, motivation, secret

Return a JSON object with an "npcs" array containing the extracted NPCs.
If no NPCs are found, return {"npcs": []}.

Text to extract from:
{text}

Return ONLY valid JSON."""


async def extract_with_openai(
    text: str,
    prompt_template: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> dict:
    """Extract structured content using OpenAI."""
    prompt = prompt_template.format(text=text[:15000])  # Limit text length
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


async def extract_with_anthropic(
    text: str,
    prompt_template: str,
    api_key: str,
    model: str = "claude-3-haiku-20240307",
) -> dict:
    """Extract structured content using Anthropic."""
    prompt = prompt_template.format(text=text[:15000])
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["content"][0]["text"].strip()
        
        # Extract JSON from response
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            return json.loads(content[start:end + 1])
        return {}


async def extract_monsters(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Extract monster stat blocks from text."""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    if provider is None:
        provider = "anthropic" if anthropic_key else "openai" if openai_key else None
    
    if provider == "openai" and openai_key:
        result = await extract_with_openai(
            text, MONSTER_EXTRACTION_PROMPT, openai_key, model or "gpt-4o-mini"
        )
    elif provider == "anthropic" and anthropic_key:
        result = await extract_with_anthropic(
            text, MONSTER_EXTRACTION_PROMPT, anthropic_key, model or "claude-3-haiku-20240307"
        )
    else:
        return []
    
    return result.get("monsters", [])


async def extract_spells(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Extract spell definitions from text."""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    if provider is None:
        provider = "anthropic" if anthropic_key else "openai" if openai_key else None
    
    if provider == "openai" and openai_key:
        result = await extract_with_openai(
            text, SPELL_EXTRACTION_PROMPT, openai_key, model or "gpt-4o-mini"
        )
    elif provider == "anthropic" and anthropic_key:
        result = await extract_with_anthropic(
            text, SPELL_EXTRACTION_PROMPT, anthropic_key, model or "claude-3-haiku-20240307"
        )
    else:
        return []
    
    return result.get("spells", [])


async def extract_magic_items(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Extract magic item definitions from text."""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    if provider is None:
        provider = "anthropic" if anthropic_key else "openai" if openai_key else None
    
    if provider == "openai" and openai_key:
        result = await extract_with_openai(
            text, MAGIC_ITEM_PROMPT, openai_key, model or "gpt-4o-mini"
        )
    elif provider == "anthropic" and anthropic_key:
        result = await extract_with_anthropic(
            text, MAGIC_ITEM_PROMPT, anthropic_key, model or "claude-3-haiku-20240307"
        )
    else:
        return []
    
    return result.get("magic_items", [])


async def extract_npcs(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Extract NPC definitions from text."""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    if provider is None:
        provider = "anthropic" if anthropic_key else "openai" if openai_key else None
    
    if provider == "openai" and openai_key:
        result = await extract_with_openai(
            text, NPC_EXTRACTION_PROMPT, openai_key, model or "gpt-4o-mini"
        )
    elif provider == "anthropic" and anthropic_key:
        result = await extract_with_anthropic(
            text, NPC_EXTRACTION_PROMPT, anthropic_key, model or "claude-3-haiku-20240307"
        )
    else:
        return []
    
    return result.get("npcs", [])


async def extract_all_content(
    text: str,
    provider: str | None = None,
    model: str | None = None,
    extract_monsters: bool = True,
    extract_spells: bool = True,
    extract_items: bool = True,
    extract_npcs: bool = True,
) -> ExtractedContent:
    """
    Extract all structured content from text.
    
    Args:
        text: The text to extract from
        provider: AI provider (openai, anthropic)
        model: Specific model to use
        extract_monsters: Whether to extract monsters
        extract_spells: Whether to extract spells
        extract_items: Whether to extract magic items
        extract_npcs: Whether to extract NPCs
    
    Returns:
        ExtractedContent with all extracted data
    """
    from grimoire.processors.structured_extractor import (
        extract_monsters as do_extract_monsters,
        extract_spells as do_extract_spells,
        extract_magic_items as do_extract_items,
        extract_npcs as do_extract_npcs,
    )
    
    content = ExtractedContent()
    
    if extract_monsters:
        monsters = await do_extract_monsters(text, provider, model)
        content.monsters = [Monster(**m) for m in monsters if m]
    
    if extract_spells:
        spells = await do_extract_spells(text, provider, model)
        content.spells = [Spell(**s) for s in spells if s]
    
    if extract_items:
        items = await do_extract_items(text, provider, model)
        content.magic_items = [MagicItem(**i) for i in items if i]
    
    if extract_npcs:
        npcs = await do_extract_npcs(text, provider, model)
        content.npcs = [NPC(**n) for n in npcs if n]
    
    return content
