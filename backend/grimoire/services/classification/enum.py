"""The Codex product_type enum and the free-text vocabulary that maps onto it.

Grimoire's `product_type` column adopts this enum (spec Phase C/D) so there is
one vocabulary and the sync needs no mapping. `core_rules` is deliberately
absent: Codex refuses it.
"""

CODEX_PRODUCT_TYPES: tuple[str, ...] = (
    "adventure",
    "sourcebook",
    "supplement",
    "bestiary",
    "tools",
    "magazine",
    "core_rulebook",
    "setting",
    "character_options",
    "gm_tools",
    "map",
    "zine",
    "screen",
    "other",
)

# Spec Phase D table. Keys are written as they appear in Grimoire; lookups are
# case-insensitive.
VOCAB_MAP: dict[str, str] = {
    **dict.fromkeys(["Adventure", "Campaign"], "adventure"),
    **dict.fromkeys(["Supplement", "Expansion", "Accessory"], "supplement"),
    "Sourcebook": "sourcebook",
    **dict.fromkeys(["Setting", "Campaign Setting"], "setting"),
    **dict.fromkeys(
        [
            "Core Rulebook", "Rulebook", "Rules", "Quickstart", "Quick Start",
            "Quickstart Guide", "Quick Start Guide", "Quick-Start Rules",
            "Quick Start Rules", "Jumpstart", "Starter Set", "RPG",
            "Roleplaying Game", "Game",
        ],
        "core_rulebook",
    ),
    **dict.fromkeys(["Bestiary", "Monster"], "bestiary"),
    **dict.fromkeys(
        ["Character Options", "Class", "Class/Archetype", "Background", "Player's Guide"],
        "character_options",
    ),
    **dict.fromkeys(["GM Tools", "GM's Resource", "Generator"], "gm_tools"),
    **dict.fromkeys(
        [
            "Character Sheet", "Character Sheets", "Token", "Portrait", "Handout",
            "Item Cards", "Cards", "Spell Sheet", "Pregenerated Character",
            "Pregenerated Characters", "Template", "Paper Model",
            "Quick Reference", "Reference",
        ],
        "tools",
    ),
    **dict.fromkeys(["Map", "Maps", "Art/Maps", "Dungeon Backdrop"], "map"),
    "Magazine": "magazine",
    "Zine": "zine",
    "GM Screen": "screen",
    **dict.fromkeys(
        [
            "Stock Art", "Texture", "Comic", "Comic/Graphic Novel",
            "Graphic Novel", "Fiction", "Short Story",
        ],
        "other",
    ),
}

_VOCAB_LOWER = {k.lower(): v for k, v in VOCAB_MAP.items()}


def normalize_free_text(value: str | None) -> str | None:
    """Map a Grimoire free-text type onto the enum, or None when unmapped."""
    if value is None:
        return None
    key = value.strip().lower()
    if key in CODEX_PRODUCT_TYPES:
        return key
    return _VOCAB_LOWER.get(key)
