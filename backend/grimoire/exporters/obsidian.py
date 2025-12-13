"""
Obsidian markdown export functionality.
Converts extracted content to Obsidian-compatible markdown with YAML frontmatter.
"""

from typing import Any
from grimoire.schemas.ttrpg import Monster, Spell, MagicItem, RandomTable, NPC, Location


def monster_to_obsidian(monster: Monster | dict) -> str:
    """Convert a monster to Obsidian markdown with YAML frontmatter."""
    if isinstance(monster, dict):
        m = monster
    else:
        m = monster.model_dump() if hasattr(monster, 'model_dump') else monster.__dict__

    lines = ["---"]
    
    # YAML frontmatter
    lines.append(f"name: \"{m.get('name', 'Unknown')}\"")
    lines.append("type: monster")
    if m.get("size"):
        lines.append(f"size: {m.get('size')}")
    if m.get("creature_type"):
        lines.append(f"creature_type: {m.get('creature_type')}")
    if m.get("alignment"):
        lines.append(f"alignment: {m.get('alignment')}")
    if m.get("challenge_rating"):
        lines.append(f"cr: \"{m.get('challenge_rating')}\"")
    if m.get("armor_class"):
        lines.append(f"ac: {m.get('armor_class')}")
    if m.get("hit_points"):
        lines.append(f"hp: {m.get('hit_points')}")
    if m.get("source_page"):
        lines.append(f"source_page: {m.get('source_page')}")
    lines.append("tags:")
    lines.append("  - monster")
    if m.get("creature_type"):
        lines.append(f"  - {m.get('creature_type').lower()}")
    
    lines.append("---")
    lines.append("")
    
    # Title
    lines.append(f"# {m.get('name', 'Unknown')}")
    lines.append("")
    
    # Basic info
    size = m.get("size", "Medium")
    ctype = m.get("creature_type", "creature")
    alignment = m.get("alignment", "")
    lines.append(f"*{size} {ctype}{', ' + alignment if alignment else ''}*")
    lines.append("")
    
    # Stats block
    lines.append("---")
    lines.append("")
    
    if m.get("armor_class"):
        ac_type = f" ({m.get('armor_type')})" if m.get("armor_type") else ""
        lines.append(f"**Armor Class** {m.get('armor_class')}{ac_type}")
    
    if m.get("hit_points"):
        hd = f" ({m.get('hit_dice')})" if m.get("hit_dice") else ""
        lines.append(f"**Hit Points** {m.get('hit_points')}{hd}")
    
    speed = m.get("speed", {})
    if speed:
        speed_parts = []
        for stype, sval in speed.items():
            if sval:
                if stype == "walk":
                    speed_parts.insert(0, f"{sval} ft.")
                else:
                    speed_parts.append(f"{stype} {sval} ft.")
        if speed_parts:
            lines.append(f"**Speed** {', '.join(speed_parts)}")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Ability scores table
    abilities = m.get("abilities") or {}
    if abilities:
        lines.append("| STR | DEX | CON | INT | WIS | CHA |")
        lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|")
        
        def fmt_ability(score):
            if score is None:
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
        
        lines.append(f"| {fmt_ability(str_val)} | {fmt_ability(dex_val)} | {fmt_ability(con_val)} | {fmt_ability(int_val)} | {fmt_ability(wis_val)} | {fmt_ability(cha_val)} |")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Saving throws, skills, etc.
    if m.get("saving_throws"):
        saves = ", ".join(f"{k.upper()} +{v}" for k, v in m["saving_throws"].items())
        lines.append(f"**Saving Throws** {saves}")
    
    if m.get("skills"):
        skills = ", ".join(f"{k} +{v}" for k, v in m["skills"].items())
        lines.append(f"**Skills** {skills}")
    
    if m.get("damage_vulnerabilities"):
        lines.append(f"**Damage Vulnerabilities** {', '.join(m['damage_vulnerabilities'])}")
    
    if m.get("damage_resistances"):
        lines.append(f"**Damage Resistances** {', '.join(m['damage_resistances'])}")
    
    if m.get("damage_immunities"):
        lines.append(f"**Damage Immunities** {', '.join(m['damage_immunities'])}")
    
    if m.get("condition_immunities"):
        lines.append(f"**Condition Immunities** {', '.join(m['condition_immunities'])}")
    
    senses = m.get("senses", {})
    if senses:
        sense_list = ", ".join(f"{k} {v}" for k, v in senses.items())
        lines.append(f"**Senses** {sense_list}")
    
    if m.get("languages"):
        lines.append(f"**Languages** {', '.join(m['languages'])}")
    
    if m.get("challenge_rating"):
        xp = f" ({m.get('experience_points'):,} XP)" if m.get("experience_points") else ""
        lines.append(f"**Challenge** {m.get('challenge_rating')}{xp}")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Traits
    for trait in m.get("traits", []):
        if isinstance(trait, dict):
            lines.append(f"***{trait.get('name', 'Trait')}.*** {trait.get('description', '')}")
            lines.append("")
    
    # Actions
    if m.get("actions"):
        lines.append("## Actions")
        lines.append("")
        for action in m["actions"]:
            if isinstance(action, dict):
                lines.append(f"***{action.get('name', 'Action')}.*** {action.get('description', '')}")
                lines.append("")
    
    # Bonus Actions
    if m.get("bonus_actions"):
        lines.append("## Bonus Actions")
        lines.append("")
        for action in m["bonus_actions"]:
            if isinstance(action, dict):
                lines.append(f"***{action.get('name', 'Bonus Action')}.*** {action.get('description', '')}")
                lines.append("")
    
    # Reactions
    if m.get("reactions"):
        lines.append("## Reactions")
        lines.append("")
        for action in m["reactions"]:
            if isinstance(action, dict):
                lines.append(f"***{action.get('name', 'Reaction')}.*** {action.get('description', '')}")
                lines.append("")
    
    # Legendary Actions
    if m.get("legendary_actions"):
        lines.append("## Legendary Actions")
        lines.append("")
        for action in m["legendary_actions"]:
            if isinstance(action, dict):
                lines.append(f"***{action.get('name', 'Legendary Action')}.*** {action.get('description', '')}")
                lines.append("")
    
    return "\n".join(lines)


def spell_to_obsidian(spell: Spell | dict) -> str:
    """Convert a spell to Obsidian markdown."""
    if isinstance(spell, dict):
        s = spell
    else:
        s = spell.model_dump() if hasattr(spell, 'model_dump') else spell.__dict__

    lines = ["---"]
    
    # YAML frontmatter
    lines.append(f"name: \"{s.get('name', 'Unknown')}\"")
    lines.append("type: spell")
    lines.append(f"level: {s.get('level', 0)}")
    if s.get("school"):
        lines.append(f"school: {s.get('school')}")
    if s.get("ritual"):
        lines.append("ritual: true")
    if s.get("concentration"):
        lines.append("concentration: true")
    if s.get("classes"):
        lines.append(f"classes: [{', '.join(s['classes'])}]")
    lines.append("tags:")
    lines.append("  - spell")
    if s.get("school"):
        lines.append(f"  - {s.get('school').lower()}")
    
    lines.append("---")
    lines.append("")
    
    # Title
    level = s.get("level", 0)
    school = s.get("school", "")
    if level == 0:
        level_text = f"{school} cantrip" if school else "Cantrip"
    else:
        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(level, f"{level}th")
        level_text = f"{ordinal}-level {school.lower()}" if school else f"{ordinal}-level"
    
    ritual_tag = " (ritual)" if s.get("ritual") else ""
    
    lines.append(f"# {s.get('name', 'Unknown')}")
    lines.append(f"*{level_text}{ritual_tag}*")
    lines.append("")
    
    # Spell details
    lines.append(f"**Casting Time:** {s.get('casting_time', '1 action')}")
    lines.append(f"**Range:** {s.get('range', 'Self')}")
    
    # Components
    components = s.get("components") or {}
    if isinstance(components, dict):
        comp_parts = []
        if components.get("verbal"):
            comp_parts.append("V")
        if components.get("somatic"):
            comp_parts.append("S")
        if components.get("material"):
            mat_desc = components.get("material_description", "")
            comp_parts.append(f"M ({mat_desc})" if mat_desc else "M")
        lines.append(f"**Components:** {', '.join(comp_parts) if comp_parts else 'None'}")
    
    duration = s.get("duration", "Instantaneous")
    if s.get("concentration"):
        duration = f"Concentration, {duration}"
    lines.append(f"**Duration:** {duration}")
    lines.append("")
    
    # Description
    if s.get("description"):
        lines.append(s["description"])
        lines.append("")
    
    # At Higher Levels
    if s.get("higher_levels"):
        lines.append(f"**At Higher Levels.** {s['higher_levels']}")
        lines.append("")
    
    # Classes
    if s.get("classes"):
        lines.append(f"**Spell Lists:** {', '.join(s['classes'])}")
    
    return "\n".join(lines)


def magic_item_to_obsidian(item: MagicItem | dict) -> str:
    """Convert a magic item to Obsidian markdown."""
    if isinstance(item, dict):
        i = item
    else:
        i = item.model_dump() if hasattr(item, 'model_dump') else item.__dict__

    lines = ["---"]
    
    # YAML frontmatter
    lines.append(f"name: \"{i.get('name', 'Unknown')}\"")
    lines.append("type: magic-item")
    if i.get("rarity"):
        lines.append(f"rarity: {i.get('rarity')}")
    if i.get("item_type"):
        lines.append(f"item_type: {i.get('item_type')}")
    if i.get("requires_attunement"):
        lines.append("attunement: true")
    lines.append("tags:")
    lines.append("  - magic-item")
    if i.get("rarity"):
        lines.append(f"  - {i.get('rarity').lower().replace(' ', '-')}")
    
    lines.append("---")
    lines.append("")
    
    # Title
    lines.append(f"# {i.get('name', 'Unknown')}")
    
    # Subtitle
    item_type = i.get("item_type", "Wondrous item")
    rarity = i.get("rarity", "")
    attune = " (requires attunement)" if i.get("requires_attunement") else ""
    if i.get("attunement_requirements"):
        attune = f" (requires attunement {i['attunement_requirements']})"
    
    lines.append(f"*{item_type}, {rarity}{attune}*")
    lines.append("")
    
    # Description
    if i.get("description"):
        lines.append(i["description"])
        lines.append("")
    
    # Charges
    if i.get("charges"):
        lines.append(f"The item has {i['charges']} charges. {i.get('recharge', '')}")
        lines.append("")
    
    return "\n".join(lines)


def random_table_to_obsidian(table: RandomTable | dict) -> str:
    """Convert a random table to Obsidian markdown."""
    if isinstance(table, dict):
        t = table
    else:
        t = table.model_dump() if hasattr(table, 'model_dump') else table.__dict__

    lines = ["---"]
    
    # YAML frontmatter
    lines.append(f"name: \"{t.get('name', 'Random Table')}\"")
    lines.append("type: random-table")
    lines.append(f"die: {t.get('die', 'd20')}")
    lines.append("tags:")
    lines.append("  - random-table")
    
    lines.append("---")
    lines.append("")
    
    # Title
    lines.append(f"# {t.get('name', 'Random Table')}")
    lines.append("")
    
    if t.get("description"):
        lines.append(t["description"])
        lines.append("")
    
    # Table
    lines.append(f"| {t.get('die', 'd20')} | Result |")
    lines.append("|:---:|:---|")
    
    for entry in t.get("entries", []):
        if isinstance(entry, dict):
            roll_min = entry.get("roll_min", 1)
            roll_max = entry.get("roll_max", 1)
            if roll_min == roll_max:
                roll = str(roll_min)
            else:
                roll = f"{roll_min}-{roll_max}"
            result = entry.get("result", "").replace("|", "\\|")
            lines.append(f"| {roll} | {result} |")
    
    lines.append("")
    
    return "\n".join(lines)


def npc_to_obsidian(npc: NPC | dict) -> str:
    """Convert an NPC to Obsidian markdown."""
    if isinstance(npc, dict):
        n = npc
    else:
        n = npc.model_dump() if hasattr(npc, 'model_dump') else npc.__dict__

    lines = ["---"]
    
    # YAML frontmatter
    lines.append(f"name: \"{n.get('name', 'Unknown')}\"")
    lines.append("type: npc")
    if n.get("role"):
        lines.append(f"role: {n.get('role')}")
    if n.get("race"):
        lines.append(f"race: {n.get('race')}")
    if n.get("location"):
        lines.append(f"location: \"[[{n.get('location')}]]\"")
    lines.append("tags:")
    lines.append("  - npc")
    if n.get("role"):
        lines.append(f"  - {n.get('role').lower().replace(' ', '-')}")
    
    lines.append("---")
    lines.append("")
    
    # Title
    lines.append(f"# {n.get('name', 'Unknown')}")
    
    # Subtitle
    parts = []
    if n.get("race"):
        parts.append(n["race"])
    if n.get("occupation"):
        parts.append(n["occupation"])
    if parts:
        lines.append(f"*{' '.join(parts)}*")
    lines.append("")
    
    # Location
    if n.get("location"):
        lines.append(f"**Location:** [[{n['location']}]]")
        lines.append("")
    
    # Description
    if n.get("description"):
        lines.append("## Description")
        lines.append(n["description"])
        lines.append("")
    
    # Personality
    if n.get("personality"):
        lines.append("## Personality")
        lines.append(n["personality"])
        lines.append("")
    
    # Motivation
    if n.get("motivation"):
        lines.append("## Motivation")
        lines.append(n["motivation"])
        lines.append("")
    
    # Secret
    if n.get("secret"):
        lines.append("## Secret")
        lines.append(f"> [!warning]- Secret\n> {n['secret']}")
        lines.append("")
    
    return "\n".join(lines)


def location_to_obsidian(location: Location | dict) -> str:
    """Convert a location to Obsidian markdown."""
    if isinstance(location, dict):
        loc = location
    else:
        loc = location.model_dump() if hasattr(location, 'model_dump') else location.__dict__

    lines = ["---"]
    
    # YAML frontmatter
    name = loc.get("name") or f"Room {loc.get('number', '?')}"
    lines.append(f"name: \"{name}\"")
    lines.append("type: location")
    if loc.get("number"):
        lines.append(f"room_number: \"{loc.get('number')}\"")
    lines.append("tags:")
    lines.append("  - location")
    
    lines.append("---")
    lines.append("")
    
    # Title
    if loc.get("number"):
        lines.append(f"# {loc.get('number')}. {loc.get('name', 'Location')}")
    else:
        lines.append(f"# {loc.get('name', 'Location')}")
    lines.append("")
    
    # Read aloud text
    if loc.get("read_aloud"):
        lines.append("> [!quote] Read Aloud")
        for line in loc["read_aloud"].split("\n"):
            lines.append(f"> {line}")
        lines.append("")
    
    # Description
    if loc.get("description"):
        lines.append(loc["description"])
        lines.append("")
    
    # Features
    if loc.get("features"):
        lines.append("## Features")
        for feature in loc["features"]:
            lines.append(f"- {feature}")
        lines.append("")
    
    # Connections
    if loc.get("connections"):
        lines.append("## Connections")
        for conn in loc["connections"]:
            lines.append(f"- [[{conn}]]")
        lines.append("")
    
    # Treasure
    if loc.get("treasure"):
        lines.append("## Treasure")
        for item in loc["treasure"]:
            lines.append(f"- {item}")
        lines.append("")
    
    return "\n".join(lines)


def export_to_obsidian_vault(
    monsters: list = None,
    spells: list = None,
    items: list = None,
    tables: list = None,
    npcs: list = None,
    locations: list = None,
) -> dict[str, str]:
    """
    Export content to Obsidian markdown files.
    
    Returns a dict mapping filename to markdown content.
    """
    files = {}

    if monsters:
        for m in monsters:
            name = m.get("name", "Unknown") if isinstance(m, dict) else m.name
            filename = f"Monsters/{_sanitize_filename(name)}.md"
            files[filename] = monster_to_obsidian(m)

    if spells:
        for s in spells:
            name = s.get("name", "Unknown") if isinstance(s, dict) else s.name
            filename = f"Spells/{_sanitize_filename(name)}.md"
            files[filename] = spell_to_obsidian(s)

    if items:
        for i in items:
            name = i.get("name", "Unknown") if isinstance(i, dict) else i.name
            filename = f"Items/{_sanitize_filename(name)}.md"
            files[filename] = magic_item_to_obsidian(i)

    if tables:
        for t in tables:
            name = t.get("name", "Random Table") if isinstance(t, dict) else t.name
            filename = f"Tables/{_sanitize_filename(name)}.md"
            files[filename] = random_table_to_obsidian(t)

    if npcs:
        for n in npcs:
            name = n.get("name", "Unknown") if isinstance(n, dict) else n.name
            filename = f"NPCs/{_sanitize_filename(name)}.md"
            files[filename] = npc_to_obsidian(n)

    if locations:
        for loc in locations:
            name = loc.get("name") or f"Room {loc.get('number', '?')}" if isinstance(loc, dict) else loc.name
            filename = f"Locations/{_sanitize_filename(name)}.md"
            files[filename] = location_to_obsidian(loc)

    return files


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    import re
    # Remove invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    return name[:100]  # Limit length
