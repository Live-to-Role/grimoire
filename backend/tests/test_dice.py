"""Tests for dice notation parsing."""

from grimoire.utils.dice import parse_dice, dice_average


def test_parse_simple():
    assert parse_dice("3d8") == (3, 8, 0)


def test_parse_with_modifier():
    assert parse_dice("3d8+3") == (3, 8, 3)
    assert parse_dice("2d4-1") == (2, 4, -1)


def test_parse_plain_integer():
    assert parse_dice("7") == (0, 0, 7)


def test_parse_whitespace_and_case():
    assert parse_dice(" 1D6 + 2 ") == (1, 6, 2)


def test_parse_garbage_returns_none():
    assert parse_dice("special") is None
    assert parse_dice("") is None
    assert parse_dice(None) is None


def test_average():
    assert dice_average("3d8+3") == 16.5   # 3 * 4.5 + 3
    assert dice_average("1d6") == 3.5
    assert dice_average("7") == 7.0
    assert dice_average("nonsense") is None
