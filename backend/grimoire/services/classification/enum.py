"""The Codex product_type enum and the free-text vocabulary that maps onto it.

Grimoire's `product_type` column adopts this enum (spec Phase C/D) so there is
one vocabulary and the sync needs no mapping. `core_rules` is deliberately
absent from the enum: Codex refuses it, so the vocabulary maps it to
`core_rulebook`.

This module imports nothing from `grimoire`: `models/product.py` imports it.
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
    # "Module" / "One-Shot" are the old Codex sync aliases.
    **dict.fromkeys(["Adventure", "Campaign", "Module", "One-Shot", "One Shot"], "adventure"),
    **dict.fromkeys(["Supplement", "Expansion", "Accessory"], "supplement"),
    "Sourcebook": "sourcebook",
    **dict.fromkeys(["Setting", "Campaign Setting"], "setting"),
    **dict.fromkeys(
        [
            "Core Rulebook", "Rulebook", "Rules", "Quickstart", "Quick Start",
            "Quickstart Guide", "Quick Start Guide", "Quick-Start Rules",
            "Quick Start Rules", "Jumpstart", "Starter Set", "RPG",
            "Roleplaying Game", "Game", "core_rules",
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
    # No true periodicals in this catalog (Michael, pilot review).
    "Magazine": "zine",
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

#: `product_type` values that describe a collection of images rather than a
#: document. Compared case-insensitively, since these are free text written by
#: several different code paths — the live library holds "Map", "Art/Maps",
#: "Stock Art", "Token" and "Portrait" among others.
#:
#: Deliberately *not* here: "Character Sheet", "Handout", "GM Tools". Those are
#: page-light but they are play aids, which is exactly what Codex is for.
IMAGE_PRODUCT_TYPES = frozenset({
    "map",
    "maps",
    "art/maps",
    "art / maps",
    "stock art",
    "token",
    "tokens",
    "portrait",
    "portraits",
    "texture",   # image_classifier's label; a texture pack is an image collection
    "textures",
})

_VOCAB_LOWER = {k.lower(): v for k, v in VOCAB_MAP.items()}


def normalize_free_text(value: str | None) -> str | None:
    """Map a Grimoire free-text type onto the enum, or None when unmapped."""
    if value is None:
        return None
    key = value.strip().lower()
    # The table first: it may redirect an enum spelling ("Magazine" -> zine).
    if key in _VOCAB_LOWER:
        return _VOCAB_LOWER[key]
    return key if key in CODEX_PRODUCT_TYPES else None


def canonical_product_type(value: str | None) -> str | None:
    """The one rule for what `Product.product_type` stores.

    Anything the vocabulary knows becomes the enum, except image free text
    whose enum is not `map` ("Token" would become `tools`, "Stock Art"
    `other`): those stay as written, because the Codex image guard and the
    image reset recognise only the free text. Unmapped text is kept as given.
    """
    if value is None or not value.strip():
        return value
    mapped = normalize_free_text(value)
    if value.strip().lower() in IMAGE_PRODUCT_TYPES and mapped != "map":
        return value
    return mapped or value
