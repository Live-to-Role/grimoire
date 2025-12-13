"""
Session Prep Assistant service.
Helps GMs prepare for game sessions by gathering relevant content from products.
"""

import json
import os
from typing import Any

import httpx

from grimoire.schemas.ttrpg import Monster, Spell, NPC, Location


SESSION_PREP_PROMPT = """You are a helpful TTRPG session prep assistant. Based on the campaign context and session notes provided, help the GM prepare for their upcoming session.

Campaign: {campaign_name}
Game System: {game_system}
Session Number: {session_number}
Session Title: {session_title}
Session Notes: {session_notes}

Available Products in Campaign:
{product_list}

Extracted Content from Products:
{content_summary}

Please provide:
1. **Session Overview**: A brief summary of what this session might cover based on the notes
2. **Key NPCs**: Important NPCs that might appear, with quick reference notes
3. **Potential Encounters**: Monsters or combat encounters that might be relevant
4. **Important Locations**: Key locations the party might visit
5. **Items & Treasure**: Magic items or treasure that might be found
6. **Random Tables**: Relevant random tables that might be useful
7. **Prep Checklist**: A checklist of things the GM should prepare before the session

Format your response as JSON with these sections."""


async def generate_session_prep(
    campaign_name: str,
    game_system: str | None,
    session_number: int,
    session_title: str | None,
    session_notes: str | None,
    products: list[dict],
    extracted_content: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """
    Generate session prep materials using AI.
    
    Args:
        campaign_name: Name of the campaign
        game_system: Game system (e.g., "D&D 5E")
        session_number: Session number
        session_title: Optional session title
        session_notes: GM's notes for the session
        products: List of products in the campaign
        extracted_content: Optional pre-extracted content from products
        provider: AI provider (openai, anthropic)
        model: Specific model to use
    
    Returns:
        Session prep materials as structured dict
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    
    if provider is None:
        provider = "anthropic" if anthropic_key else "openai" if openai_key else None
    
    if not provider:
        return _generate_basic_prep(
            campaign_name, session_number, session_title, session_notes, products
        )
    
    # Build product list
    product_list = "\n".join([
        f"- {p.get('title', p.get('file_name', 'Unknown'))} ({p.get('game_system', 'Unknown system')})"
        for p in products
    ])
    
    # Build content summary
    content_summary = "No extracted content available."
    if extracted_content:
        parts = []
        if extracted_content.get("monsters"):
            monster_names = [m.get("name", "Unknown") for m in extracted_content["monsters"][:10]]
            parts.append(f"Monsters: {', '.join(monster_names)}")
        if extracted_content.get("npcs"):
            npc_names = [n.get("name", "Unknown") for n in extracted_content["npcs"][:10]]
            parts.append(f"NPCs: {', '.join(npc_names)}")
        if extracted_content.get("locations"):
            loc_names = [l.get("name", "Unknown") for l in extracted_content["locations"][:10]]
            parts.append(f"Locations: {', '.join(loc_names)}")
        if parts:
            content_summary = "\n".join(parts)
    
    prompt = SESSION_PREP_PROMPT.format(
        campaign_name=campaign_name,
        game_system=game_system or "Unknown",
        session_number=session_number,
        session_title=session_title or "Untitled",
        session_notes=session_notes or "No notes provided",
        product_list=product_list or "No products linked",
        content_summary=content_summary,
    )
    
    try:
        if provider == "openai" and openai_key:
            result = await _call_openai(prompt, openai_key, model or "gpt-4o-mini")
        elif provider == "anthropic" and anthropic_key:
            result = await _call_anthropic(prompt, anthropic_key, model or "claude-3-haiku-20240307")
        else:
            return _generate_basic_prep(
                campaign_name, session_number, session_title, session_notes, products
            )
        
        return result
    except Exception as e:
        # Fall back to basic prep on error
        basic = _generate_basic_prep(
            campaign_name, session_number, session_title, session_notes, products
        )
        basic["error"] = str(e)
        return basic


async def _call_openai(prompt: str, api_key: str, model: str) -> dict:
    """Call OpenAI API for session prep."""
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
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


async def _call_anthropic(prompt: str, api_key: str, model: str) -> dict:
    """Call Anthropic API for session prep."""
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
                "messages": [{"role": "user", "content": prompt + "\n\nRespond with valid JSON only."}],
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
        return {"error": "Failed to parse AI response"}


def _generate_basic_prep(
    campaign_name: str,
    session_number: int,
    session_title: str | None,
    session_notes: str | None,
    products: list[dict],
) -> dict:
    """Generate basic session prep without AI."""
    return {
        "session_overview": f"Session {session_number}: {session_title or 'Untitled'}",
        "key_npcs": [],
        "potential_encounters": [],
        "important_locations": [],
        "items_and_treasure": [],
        "random_tables": [],
        "prep_checklist": [
            "Review session notes",
            "Prepare NPC voices and motivations",
            "Have monster stat blocks ready",
            "Prepare maps if needed",
            "Review relevant rules",
            "Prepare music/ambiance",
            "Have random encounter tables ready",
        ],
        "products": [
            {"title": p.get("title", p.get("file_name", "Unknown")), "id": p.get("id")}
            for p in products
        ],
        "notes": session_notes,
        "ai_generated": False,
    }


def generate_encounter_card(monster: dict) -> str:
    """Generate a quick reference encounter card for a monster."""
    name = monster.get("name", "Unknown")
    ac = monster.get("armor_class", "?")
    hp = monster.get("hit_points", "?")
    cr = monster.get("challenge_rating", "?")
    
    abilities = monster.get("abilities") or {}
    
    card = f"""
## {name}
**AC** {ac} | **HP** {hp} | **CR** {cr}

| STR | DEX | CON | INT | WIS | CHA |
|:---:|:---:|:---:|:---:|:---:|:---:|
"""
    
    def fmt(score):
        if not score:
            return "—"
        mod = (score - 10) // 2
        sign = "+" if mod >= 0 else ""
        return f"{score} ({sign}{mod})"
    
    str_val = abilities.get("strength") or abilities.get("str")
    dex_val = abilities.get("dexterity") or abilities.get("dex")
    con_val = abilities.get("constitution") or abilities.get("con")
    int_val = abilities.get("intelligence") or abilities.get("int")
    wis_val = abilities.get("wisdom") or abilities.get("wis")
    cha_val = abilities.get("charisma") or abilities.get("cha")
    
    card += f"| {fmt(str_val)} | {fmt(dex_val)} | {fmt(con_val)} | {fmt(int_val)} | {fmt(wis_val)} | {fmt(cha_val)} |\n"
    
    # Add key actions
    actions = monster.get("actions", [])
    if actions:
        card += "\n### Actions\n"
        for action in actions[:3]:  # Limit to 3 for quick reference
            if isinstance(action, dict):
                card += f"- **{action.get('name', 'Action')}**: {action.get('description', '')[:100]}...\n"
    
    return card


def generate_npc_card(npc: dict) -> str:
    """Generate a quick reference card for an NPC."""
    name = npc.get("name", "Unknown")
    role = npc.get("role", "")
    race = npc.get("race", "")
    occupation = npc.get("occupation", "")
    
    card = f"""
## {name}
*{race} {occupation}* {f'({role})' if role else ''}

"""
    
    if npc.get("description"):
        card += f"**Appearance**: {npc['description']}\n\n"
    
    if npc.get("personality"):
        card += f"**Personality**: {npc['personality']}\n\n"
    
    if npc.get("motivation"):
        card += f"**Wants**: {npc['motivation']}\n\n"
    
    if npc.get("secret"):
        card += f"> **Secret**: {npc['secret']}\n"
    
    return card
