"""Tests for closed-form combat metrics."""

import json

import pytest

from grimoire.models import MonsterEntry
from grimoire.services.monster_metrics import compute_metrics


def make_entry(**kwargs):
    defaults = dict(
        product_id=1, name="Orc", system_profile="dcc", raw_text="x",
        ac=13, hd_dice="1d8+1", hd_value=1.0, hp_avg=5.5,
        attacks=json.dumps([{"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5}]),
        review_status="confirmed",
    )
    defaults.update(kwargs)
    return MonsterEntry(**defaults)


def test_hit_chance_and_dpr_vs_tiers():
    metrics = compute_metrics(make_entry())
    assert metrics["hp_avg"] == 5.5
    tiers = {t["tier"]: t for t in metrics["tiers"]}
    # DCC tiers: unarmored 10, leather 12, chain 15, plate & shield 19
    assert tiers["unarmored"]["attacks"][0]["hit_chance"] == pytest.approx(0.6)   # (21+1-10)/20
    assert tiers["unarmored"]["total_dpr"] == pytest.approx(1.5)                  # 0.6 * 2.5
    assert tiers["chain"]["attacks"][0]["hit_chance"] == pytest.approx(0.35)      # (21+1-15)/20
    assert tiers["plate & shield"]["attacks"][0]["hit_chance"] == pytest.approx(0.15)


def test_hit_chance_clamped():
    strong = make_entry(attacks=json.dumps([{"name": "bite", "bonus": 30, "damage_dice": "1d6", "damage_avg": 3.5}]))
    weak = make_entry(attacks=json.dumps([{"name": "peck", "bonus": -20, "damage_dice": "1", "damage_avg": 1.0}]))
    strong_tiers = compute_metrics(strong)["tiers"]
    weak_tiers = compute_metrics(weak)["tiers"]
    assert all(t["attacks"][0]["hit_chance"] == 0.95 for t in strong_tiers)
    assert all(t["attacks"][0]["hit_chance"] == 0.05 for t in weak_tiers)


def test_missing_bonus_yields_none_and_excluded_from_total():
    entry = make_entry(attacks=json.dumps([
        {"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5},
        {"name": "gaze", "bonus": None, "damage_dice": None, "damage_avg": None},
    ]))
    tiers = compute_metrics(entry)["tiers"]
    unarmored = tiers[0]
    assert unarmored["attacks"][1]["hit_chance"] is None
    assert unarmored["total_dpr"] == pytest.approx(1.5)


def test_no_attacks():
    metrics = compute_metrics(make_entry(attacks=json.dumps([])))
    assert metrics["tiers"][0]["total_dpr"] == 0.0


def test_bonus_present_damage_missing_yields_hit_chance_not_dpr():
    """Attack with real bonus but no damage_avg: hit_chance computed, dpr=None, excluded from total.

    This is the deliberate, owner-decided semantics: a known-to-hit with unknown damage
    (e.g. gaze, poison, save-or-die) still has meaningful hit probability to report,
    so we compute and surface it rather than suppressing a computable number.
    """
    entry = make_entry(attacks=json.dumps([
        {"name": "claw", "bonus": 1, "damage_dice": "1d4", "damage_avg": 2.5},
        {"name": "gaze", "bonus": 2, "damage_dice": None, "damage_avg": None},
    ]))
    tiers = compute_metrics(entry)["tiers"]
    unarmored = tiers[0]
    # Gaze attack should have computed hit_chance, no dpr
    assert unarmored["attacks"][1]["hit_chance"] == pytest.approx(0.65)  # (21+2-10)/20
    assert unarmored["attacks"][1]["dpr"] is None
    # Gaze attack's missing dpr should not contribute to total
    assert unarmored["total_dpr"] == pytest.approx(1.5)  # only claw's 0.6 * 2.5


def test_tier_order_unarmored_first():
    """Armor tier order is load-bearing: downstream code and UI rely on unarmored being first."""
    metrics = compute_metrics(make_entry())
    tiers = metrics["tiers"]
    assert tiers[0]["tier"] == "unarmored"
    # DCC has 4 tiers in order
    expected_order = ["unarmored", "leather", "chain", "plate & shield"]
    actual_order = [t["tier"] for t in tiers]
    assert actual_order == expected_order
