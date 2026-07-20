"""Shared derivation of computed monster stats and validation flags.

Single source of truth for the numbers the bestiary shows. Both LLM
extraction (`monster_normalizer.build_entry_from_llm`) and hand-created /
hand-edited entries (the monsters API) route through here, so a typed-in
entry is flagged and scored exactly as an extracted one is.
"""

from grimoire.utils.dice import dice_average, parse_dice


def derive_stats(
    ac: int | None,
    hd_dice: str | None,
    attacks: list[dict] | None,
) -> tuple[dict, list[str]]:
    """Compute derived stat fields and validation flags.

    Returns (fields, flags). `fields["attacks"]` is a list of dicts - callers
    are responsible for `json.dumps` before storing it in the Text column.
    """
    flags: list[str] = []

    if ac is not None and not (0 <= int(ac) <= 30):
        flags.append("ac_out_of_range")

    normalized_attacks = []
    for atk in attacks or []:
        damage_dice = atk.get("damage_dice")
        damage_avg = dice_average(damage_dice)
        if damage_dice and damage_avg is None:
            flags.append("damage_unparseable")
        normalized_attacks.append({
            "name": atk.get("name") or "attack",
            "bonus": atk.get("bonus"),
            "damage_dice": damage_dice,
            "damage_avg": damage_avg,
        })
    if not normalized_attacks:
        flags.append("no_attacks")

    hp_avg = dice_average(hd_dice)
    parsed_hd = parse_dice(hd_dice)
    hd_value = float(parsed_hd[0]) if parsed_hd else None
    if hd_dice and parsed_hd is None:
        flags.append("hd_unparseable")

    fields = {
        "ac": int(ac) if ac is not None else None,
        "hd_dice": hd_dice,
        "hd_value": hd_value,
        "hp_avg": hp_avg,
        "attacks": normalized_attacks,
    }
    return fields, sorted(set(flags))
