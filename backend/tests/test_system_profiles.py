"""Tests for system profile normalization and registry."""

import pytest

from grimoire.processors.system_profiles import (
    PROFILES,
    get_profile,
    normalize_descending_ac,
    normalize_thac0,
)


def test_thac0_to_bonus():
    assert normalize_thac0(19) == 1
    assert normalize_thac0(20) == 0
    assert normalize_thac0(15) == 5


def test_descending_ac_to_ascending():
    assert normalize_descending_ac(9) == 10   # unarmored
    assert normalize_descending_ac(7) == 12   # leather
    assert normalize_descending_ac(2) == 17   # plate & shield


def test_profiles_registered():
    assert set(PROFILES.keys()) == {"dcc", "osr"}
    assert get_profile("dcc").label == "Dungeon Crawl Classics"
    with pytest.raises(KeyError):
        get_profile("gurps")


def test_armor_tiers_ascend():
    for profile in PROFILES.values():
        tiers = list(profile.armor_tiers.values())
        assert tiers == sorted(tiers), f"{profile.id} tiers must ascend"
        assert len(tiers) == 4


def test_dcc_anchor_matches_inline_statline():
    line = "Orc: Init +1; Atk claw +1 melee (1d4); AC 13; HD 1d8+1; MV 30'; Act 1d20; SV Fort +1, Ref +0, Will -1; AL C."
    assert get_profile("dcc").statline_anchor.search(line)


def test_osr_anchor_matches_block_statline():
    line = "AC 9 [10], HD 1d4, Att 1 x bite (poison), THAC0 19, MV 60' (20')"
    assert get_profile("osr").statline_anchor.search(line)
    assert not get_profile("osr").statline_anchor.search("The cave is dark and damp.")
