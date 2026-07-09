"""DCC backfill matching helpers."""
import pytest

from scripts.backfill_dcc_levels import normalize_title, parse_module_number


@pytest.mark.parametrize("text,expected", [
    ("DCC #67 Sailors on the Starless Sea", "67"),
    ("DCC 067 - Sailors on the Starless Sea.pdf", "67"),
    ("dcc-035-gazetteer.pdf", "35"),
    ("DCC RPG Core Rulebook", None),          # no module number
    ("Sailors on the Starless Sea", None),
    ("DCC #91.1 Barako", "91.1"),             # decimal sub-module
    ("dcc-091.2-lairs.pdf", "91.2"),          # decimal sub-module, leading-zero integer part
])
def test_parse_module_number(text, expected):
    assert parse_module_number(text) == expected


def test_normalize_title():
    assert normalize_title("Sailors on the  Starless Sea!") == "sailors on the starless sea"
    assert normalize_title("The Music of the Spheres is Chaos") == \
        normalize_title("the music of the spheres is chaos")
