"""Closed-form combat metrics over normalized monster statlines.

Consumes probabilities, not mechanics: the normalized attack bonus encodes a
d20 hit-probability line. A future non-d20 profile would supply a different
curve here without touching callers.
"""

import json

from grimoire.models.monster_entry import MonsterEntry
from grimoire.processors.system_profiles import get_profile

_MIN_P = 0.05  # natural 1 always misses
_MAX_P = 0.95  # natural 20 always hits


def hit_chance(bonus: int, target_ac: int) -> float:
    """P(d20 + bonus >= target_ac), clamped for natural 1/20."""
    return max(_MIN_P, min(_MAX_P, (21 + bonus - target_ac) / 20))


def compute_metrics(entry: MonsterEntry) -> dict:
    """Hit chance and damage-per-round vs. the profile's armor tiers."""
    profile = get_profile(entry.system_profile)
    attacks = json.loads(entry.attacks) if entry.attacks else []

    tiers = []
    for tier_name, tier_ac in profile.armor_tiers.items():
        tier_attacks = []
        total_dpr = 0.0
        for atk in attacks:
            bonus, damage_avg = atk.get("bonus"), atk.get("damage_avg")
            if bonus is None:
                tier_attacks.append({"name": atk.get("name"), "hit_chance": None, "dpr": None})
                continue
            p = hit_chance(int(bonus), tier_ac)
            dpr = round(p * damage_avg, 2) if damage_avg is not None else None
            if dpr is not None:
                total_dpr += dpr
            tier_attacks.append({"name": atk.get("name"), "hit_chance": p, "dpr": dpr})
        tiers.append({
            "tier": tier_name,
            "ac": tier_ac,
            "attacks": tier_attacks,
            "total_dpr": round(total_dpr, 2),
        })

    return {"hp_avg": entry.hp_avg, "tiers": tiers}
