"""
Foundry VTT export functionality.
Converts extracted content to Foundry VTT compatible JSON format.
"""

import json
from typing import Any

from grimoire.schemas.ttrpg import Monster, Spell, MagicItem, RandomTable, NPC


def ability_modifier(score: int) -> int:
    """Calculate ability modifier from score."""
    return (score - 10) // 2


def monster_to_foundry(monster: Monster | dict) -> dict:
    """Convert a monster to Foundry VTT 5e system format."""
    if isinstance(monster, dict):
        m = monster
    else:
        m = monster.model_dump() if hasattr(monster, 'model_dump') else monster.__dict__

    abilities = m.get("abilities") or {}
    if isinstance(abilities, dict) and "strength" in abilities:
        # Full names to short
        abilities = {
            "str": abilities.get("strength"),
            "dex": abilities.get("dexterity"),
            "con": abilities.get("constitution"),
            "int": abilities.get("intelligence"),
            "wis": abilities.get("wisdom"),
            "cha": abilities.get("charisma"),
        }

    # Build Foundry actor data
    foundry_actor = {
        "name": m.get("name", "Unknown"),
        "type": "npc",
        "img": "icons/svg/mystery-man.svg",
        "system": {
            "abilities": {},
            "attributes": {
                "ac": {
                    "flat": m.get("armor_class"),
                    "calc": "flat",
                },
                "hp": {
                    "value": m.get("hit_points"),
                    "max": m.get("hit_points"),
                    "formula": m.get("hit_dice"),
                },
                "movement": {},
                "senses": {},
            },
            "details": {
                "biography": {"value": ""},
                "alignment": m.get("alignment"),
                "cr": m.get("challenge_rating"),
                "xp": {"value": m.get("experience_points")},
                "type": {
                    "value": m.get("creature_type"),
                    "subtype": m.get("subtype"),
                },
            },
            "traits": {
                "size": _size_to_foundry(m.get("size")),
                "di": {"value": m.get("damage_immunities", [])},
                "dr": {"value": m.get("damage_resistances", [])},
                "dv": {"value": m.get("damage_vulnerabilities", [])},
                "ci": {"value": m.get("condition_immunities", [])},
                "languages": {"value": m.get("languages", [])},
            },
        },
        "items": [],
        "flags": {
            "grimoire": {
                "source": "grimoire-export",
                "source_page": m.get("source_page"),
            }
        },
    }

    # Add abilities
    for abbr in ["str", "dex", "con", "int", "wis", "cha"]:
        score = abilities.get(abbr)
        if score:
            foundry_actor["system"]["abilities"][abbr] = {
                "value": score,
                "proficient": 0,
            }

    # Add movement
    speed = m.get("speed", {})
    if isinstance(speed, dict):
        foundry_actor["system"]["attributes"]["movement"] = {
            "walk": speed.get("walk"),
            "fly": speed.get("fly"),
            "swim": speed.get("swim"),
            "climb": speed.get("climb"),
            "burrow": speed.get("burrow"),
            "units": "ft",
        }

    # Add senses
    senses = m.get("senses", {})
    if isinstance(senses, dict):
        foundry_actor["system"]["attributes"]["senses"] = {
            "darkvision": _parse_sense_range(senses.get("darkvision")),
            "blindsight": _parse_sense_range(senses.get("blindsight")),
            "tremorsense": _parse_sense_range(senses.get("tremorsense")),
            "truesight": _parse_sense_range(senses.get("truesight")),
            "units": "ft",
        }

    # Add traits as items
    for trait in m.get("traits", []):
        if isinstance(trait, dict):
            foundry_actor["items"].append({
                "name": trait.get("name", "Trait"),
                "type": "feat",
                "system": {
                    "description": {"value": trait.get("description", "")},
                    "type": {"value": "monster"},
                },
            })

    # Add actions as items
    for action in m.get("actions", []):
        if isinstance(action, dict):
            foundry_actor["items"].append(_action_to_foundry_item(action))

    # Add legendary actions
    for action in m.get("legendary_actions", []):
        if isinstance(action, dict):
            item = _action_to_foundry_item(action)
            item["system"]["activation"] = {"type": "legendary", "cost": 1}
            foundry_actor["items"].append(item)

    return foundry_actor


def _size_to_foundry(size: str | None) -> str:
    """Convert size to Foundry format."""
    if not size:
        return "med"
    size_map = {
        "tiny": "tiny",
        "small": "sm",
        "medium": "med",
        "large": "lg",
        "huge": "huge",
        "gargantuan": "grg",
    }
    return size_map.get(size.lower(), "med")


def _parse_sense_range(sense: str | None) -> int | None:
    """Parse sense range from string like '60 ft.'"""
    if not sense:
        return None
    import re
    match = re.search(r'(\d+)', str(sense))
    return int(match.group(1)) if match else None


def _action_to_foundry_item(action: dict) -> dict:
    """Convert an action to a Foundry item."""
    item = {
        "name": action.get("name", "Action"),
        "type": "feat",
        "system": {
            "description": {"value": action.get("description", "")},
            "activation": {"type": "action", "cost": 1},
            "type": {"value": "monster"},
        },
    }

    # If it has attack info, make it a weapon
    attack = action.get("attack")
    if attack:
        item["type"] = "weapon"
        item["system"]["actionType"] = "mwak" if attack.get("attack_type") == "melee" else "rwak"
        item["system"]["attackBonus"] = attack.get("to_hit")
        item["system"]["range"] = {
            "value": _parse_sense_range(attack.get("reach") or attack.get("range")),
            "units": "ft",
        }

        # Add damage
        damage = attack.get("damage", [])
        if damage:
            item["system"]["damage"] = {
                "parts": [[d.get("dice", ""), d.get("damage_type", "")] for d in damage if isinstance(d, dict)],
            }

    return item


def spell_to_foundry(spell: Spell | dict) -> dict:
    """Convert a spell to Foundry VTT 5e system format."""
    if isinstance(spell, dict):
        s = spell
    else:
        s = spell.model_dump() if hasattr(spell, 'model_dump') else spell.__dict__

    components = s.get("components") or {}
    if isinstance(components, dict):
        comp_data = {
            "vocal": components.get("verbal", False),
            "somatic": components.get("somatic", False),
            "material": components.get("material", False),
            "value": components.get("material_description", ""),
        }
    else:
        comp_data = {"vocal": False, "somatic": False, "material": False}

    foundry_spell = {
        "name": s.get("name", "Unknown Spell"),
        "type": "spell",
        "img": "icons/svg/explosion.svg",
        "system": {
            "description": {"value": s.get("description", "")},
            "source": {"custom": "Grimoire Export"},
            "level": s.get("level", 0),
            "school": _school_to_foundry(s.get("school")),
            "components": comp_data,
            "materials": {
                "value": components.get("material_description", "") if isinstance(components, dict) else "",
                "consumed": components.get("material_consumed", False) if isinstance(components, dict) else False,
                "cost": 0,
            },
            "preparation": {"mode": "prepared"},
            "activation": {
                "type": _activation_type(s.get("casting_time")),
                "cost": 1,
            },
            "duration": {
                "value": _parse_duration_value(s.get("duration")),
                "units": _parse_duration_units(s.get("duration")),
                "concentration": s.get("concentration", False),
            },
            "range": {
                "value": _parse_sense_range(s.get("range")),
                "units": "ft" if s.get("range") else "self",
            },
            "properties": ["ritual"] if s.get("ritual") else [],
        },
        "flags": {
            "grimoire": {
                "source": "grimoire-export",
                "source_page": s.get("source_page"),
            }
        },
    }

    # Add damage if present
    damage = s.get("damage")
    if damage and isinstance(damage, dict):
        foundry_spell["system"]["damage"] = {
            "parts": [[damage.get("dice", ""), damage.get("damage_type", "")]],
        }

    # Add save if present
    save = s.get("save")
    if save:
        foundry_spell["system"]["save"] = {
            "ability": save[:3].lower() if save else "",
            "dc": None,
            "scaling": "spell",
        }

    return foundry_spell


def _school_to_foundry(school: str | None) -> str:
    """Convert spell school to Foundry abbreviation."""
    if not school:
        return "evo"
    school_map = {
        "abjuration": "abj",
        "conjuration": "con",
        "divination": "div",
        "enchantment": "enc",
        "evocation": "evo",
        "illusion": "ill",
        "necromancy": "nec",
        "transmutation": "trs",
    }
    return school_map.get(school.lower(), "evo")


def _activation_type(casting_time: str | None) -> str:
    """Convert casting time to Foundry activation type."""
    if not casting_time:
        return "action"
    ct = casting_time.lower()
    if "bonus" in ct:
        return "bonus"
    if "reaction" in ct:
        return "reaction"
    if "minute" in ct:
        return "minute"
    if "hour" in ct:
        return "hour"
    return "action"


def _parse_duration_value(duration: str | None) -> int | None:
    """Parse duration value from string."""
    if not duration:
        return None
    import re
    match = re.search(r'(\d+)', duration)
    return int(match.group(1)) if match else None


def _parse_duration_units(duration: str | None) -> str:
    """Parse duration units from string."""
    if not duration:
        return "inst"
    d = duration.lower()
    if "instant" in d:
        return "inst"
    if "round" in d:
        return "round"
    if "minute" in d:
        return "minute"
    if "hour" in d:
        return "hour"
    if "day" in d:
        return "day"
    if "permanent" in d or "until" in d:
        return "perm"
    return "inst"


def magic_item_to_foundry(item: MagicItem | dict) -> dict:
    """Convert a magic item to Foundry VTT format."""
    if isinstance(item, dict):
        i = item
    else:
        i = item.model_dump() if hasattr(item, 'model_dump') else item.__dict__

    foundry_item = {
        "name": i.get("name", "Unknown Item"),
        "type": _item_type_to_foundry(i.get("item_type")),
        "img": "icons/svg/item-bag.svg",
        "system": {
            "description": {"value": i.get("description", "")},
            "source": {"custom": "Grimoire Export"},
            "rarity": i.get("rarity", "common"),
            "attunement": "required" if i.get("requires_attunement") else "",
            "properties": i.get("properties", []),
        },
        "flags": {
            "grimoire": {
                "source": "grimoire-export",
                "source_page": i.get("source_page"),
            }
        },
    }

    # Add charges if present
    if i.get("charges"):
        foundry_item["system"]["uses"] = {
            "value": i.get("charges"),
            "max": i.get("charges"),
            "per": "charges",
            "recovery": i.get("recharge", ""),
        }

    return foundry_item


def _item_type_to_foundry(item_type: str | None) -> str:
    """Convert item type to Foundry type."""
    if not item_type:
        return "loot"
    it = item_type.lower()
    if "weapon" in it:
        return "weapon"
    if "armor" in it or "shield" in it:
        return "equipment"
    if "potion" in it:
        return "consumable"
    if "scroll" in it:
        return "consumable"
    if "wand" in it or "rod" in it or "staff" in it:
        return "equipment"
    return "loot"


def random_table_to_foundry(table: RandomTable | dict) -> dict:
    """Convert a random table to Foundry RollTable format."""
    if isinstance(table, dict):
        t = table
    else:
        t = table.model_dump() if hasattr(table, 'model_dump') else table.__dict__

    results = []
    for entry in t.get("entries", []):
        if isinstance(entry, dict):
            results.append({
                "type": 0,  # Text result
                "text": entry.get("result", ""),
                "weight": 1,
                "range": [entry.get("roll_min", 1), entry.get("roll_max", 1)],
                "drawn": False,
            })

    return {
        "name": t.get("name", "Random Table"),
        "img": "icons/svg/d20-grey.svg",
        "description": t.get("description", ""),
        "results": results,
        "formula": f"1{t.get('die', 'd20')}",
        "replacement": True,
        "displayRoll": True,
        "flags": {
            "grimoire": {
                "source": "grimoire-export",
                "source_page": t.get("source_page"),
            }
        },
    }


def export_to_foundry_compendium(
    monsters: list = None,
    spells: list = None,
    items: list = None,
    tables: list = None,
) -> dict:
    """
    Export content to a Foundry VTT compendium-style JSON.
    
    Returns a dict with separate arrays for each content type.
    """
    export = {
        "system": "dnd5e",
        "version": "1.0",
        "source": "grimoire",
    }

    if monsters:
        export["actors"] = [monster_to_foundry(m) for m in monsters]

    if spells:
        export["spells"] = [spell_to_foundry(s) for s in spells]

    if items:
        export["items"] = [magic_item_to_foundry(i) for i in items]

    if tables:
        export["tables"] = [random_table_to_foundry(t) for t in tables]

    return export
