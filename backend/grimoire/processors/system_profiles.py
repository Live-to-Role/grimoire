"""Game system profiles for monster extraction.

The canonical downstream model is hit probability as a function of target
defense, encoded as a normalized attack bonus vs. ascending AC. THAC0,
attack matrices, and descending AC are input dialects that these profiles
translate at extraction time; they never leak past this layer.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemProfile:
    id: str
    label: str
    statline_anchor: re.Pattern
    # Ordered ascending-AC values for: unarmored, leather, chain, plate & shield
    armor_tiers: dict[str, int]
    prompt_hint: str


def normalize_thac0(thac0: int) -> int:
    """THAC0 -> ascending-AC attack bonus."""
    return 20 - thac0


def normalize_descending_ac(ac: int) -> int:
    """Descending AC -> ascending AC (OSE convention: 9 <-> 10)."""
    return 19 - ac


DCC_PROFILE = SystemProfile(
    id="dcc",
    label="Dungeon Crawl Classics",
    # DCC inline statline: "Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; ..."
    statline_anchor=re.compile(r"Init\s+[+-]?\d+.{0,120}?\bAC\s+\d+.{0,80}?\bHD\s+\d+d\d+", re.IGNORECASE | re.DOTALL),
    armor_tiers={"unarmored": 10, "leather": 12, "chain": 15, "plate & shield": 19},
    prompt_hint=(
        "This is a Dungeon Crawl Classics (DCC) stat line. AC is ascending. "
        "Attack bonuses appear like 'Atk bite +4 melee (1d6+2)'. HD like '3d8+3'."
    ),
)

OSR_PROFILE = SystemProfile(
    id="osr",
    label="Generic OSR (B/X, AD&D, OSE-style)",
    # OSR block statline: needs AC and HD near each other; THAC0 optional.
    statline_anchor=re.compile(r"\bAC[:\s]+-?\d+.{0,160}?\bHD[:\s]+\d+", re.IGNORECASE | re.DOTALL),
    armor_tiers={"unarmored": 10, "leather": 12, "chain": 14, "plate & shield": 17},
    prompt_hint=(
        "This is an old-school (B/X, AD&D, OSE) stat block. AC may be DESCENDING "
        "(lower is better, unarmored = 9) unless a bracketed ascending value like "
        "'AC 7 [12]' is present. THAC0 may be given instead of attack bonuses. "
        "Report values exactly as printed and set ac_style accordingly."
    ),
)

PROFILES: dict[str, SystemProfile] = {p.id: p for p in (DCC_PROFILE, OSR_PROFILE)}


def get_profile(profile_id: str) -> SystemProfile:
    return PROFILES[profile_id]
