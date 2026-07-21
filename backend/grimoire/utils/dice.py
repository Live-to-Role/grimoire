"""Dice notation parsing and averaging."""

import re

_DICE_RE = re.compile(r"^\s*(\d+)\s*[dD]\s*(\d+)\s*(?:([+-])\s*(\d+))?\s*$")
_INT_RE = re.compile(r"^\s*(\d+)\s*$")


def parse_dice(notation: str | None) -> tuple[int, int, int] | None:
    """Parse dice notation like '3d8+3' into (count, sides, modifier).

    Plain integers parse as (0, 0, value). Returns None if unparseable.
    """
    if not notation:
        return None
    match = _DICE_RE.match(notation)
    if match:
        count, sides = int(match.group(1)), int(match.group(2))
        modifier = int(match.group(4)) if match.group(4) else 0
        if match.group(3) == "-":
            modifier = -modifier
        return (count, sides, modifier)
    match = _INT_RE.match(notation)
    if match:
        return (0, 0, int(match.group(1)))
    return None


def dice_average(notation: str | None) -> float | None:
    """Average roll of a dice expression, or None if unparseable."""
    parsed = parse_dice(notation)
    if parsed is None:
        return None
    count, sides, modifier = parsed
    return count * (sides + 1) / 2 + modifier
