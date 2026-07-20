"""Unit tests for shared monster stat derivation."""

from grimoire.services.monster_fields import derive_stats


def test_derives_hd_value_and_hp_avg():
    fields, flags = derive_stats(ac=13, hd_dice="3d6", attacks=[{"name": "bite", "damage_dice": "1d4"}])
    assert fields["hp_avg"] == 10.5
    assert fields["hd_value"] == 3.0
    assert fields["attacks"][0]["damage_avg"] == 2.5
    assert flags == []


def test_flags_no_attacks():
    _, flags = derive_stats(ac=13, hd_dice="1d8", attacks=[])
    assert flags == ["no_attacks"]


def test_flags_unparseable_hd_and_damage():
    fields, flags = derive_stats(
        ac=13, hd_dice="4d8 per 8 tentacles",
        attacks=[{"name": "sting", "damage_dice": "1d3 plus stun"}],
    )
    assert fields["hd_value"] is None
    assert fields["hp_avg"] is None
    assert fields["attacks"][0]["damage_avg"] is None
    assert flags == ["damage_unparseable", "hd_unparseable"]


def test_flags_ac_out_of_range():
    _, flags = derive_stats(ac=99, hd_dice="1d8", attacks=[{"name": "claw", "damage_dice": "1d4"}])
    assert flags == ["ac_out_of_range"]


def test_none_stats_are_tolerated():
    fields, flags = derive_stats(ac=None, hd_dice=None, attacks=None)
    assert fields["ac"] is None
    assert fields["hd_dice"] is None
    assert fields["hd_value"] is None
    assert fields["hp_avg"] is None
    assert fields["attacks"] == []
    assert flags == ["no_attacks"]


def test_attack_defaults_fill_missing_keys():
    fields, _ = derive_stats(ac=10, hd_dice="1d8", attacks=[{}])
    assert fields["attacks"][0] == {
        "name": "attack", "bonus": None, "damage_dice": None, "damage_avg": None,
    }
