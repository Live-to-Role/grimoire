# backend/tests/test_monster_normalizer.py
"""Tests for LLM output normalization and validation (LLM mocked)."""

import json

import pytest

from grimoire.processors.monster_normalizer import build_entry_from_llm, normalize_candidate
from grimoire.processors.monster_segmenter import Candidate
from grimoire.processors.system_profiles import get_profile


def make_candidate(**kwargs):
    defaults = {"name_guess": "Orc", "page": 12, "raw_text": "Orc: Init +1; ... AC 13; HD 1d8+1"}
    defaults.update(kwargs)
    return Candidate(**defaults)


def test_ascending_ac_passthrough_and_derived_fields():
    llm = {
        "is_monster": True, "name": "Orc", "ac": 13, "ac_style": "ascending",
        "thac0": None, "hd_dice": "1d8+1",
        "attacks": [{"name": "claw", "bonus": 1, "damage_dice": "1d4"}],
        "move": "30'", "special_abilities": [], "environments": ["wilderness"],
        "confidence": 0.9,
    }
    entry = build_entry_from_llm(llm, make_candidate(), get_profile("dcc"))
    assert entry["ac"] == 13
    assert entry["hp_avg"] == 5.5
    assert entry["hd_value"] == 1.0
    attacks = json.loads(entry["attacks"])
    assert attacks[0]["bonus"] == 1
    assert attacks[0]["damage_avg"] == 2.5
    assert json.loads(entry["flags"]) == []
    assert entry["review_status"] == "pending"
    assert entry["page_number"] == 12
    assert entry["system_profile"] == "dcc"


def test_descending_ac_and_thac0_are_normalized():
    llm = {
        "is_monster": True, "name": "Peryton", "ac": 7, "ac_style": "descending",
        "thac0": 15, "hd_dice": "4d8",
        "attacks": [{"name": "antlers", "bonus": None, "damage_dice": "2d4"}],
        "move": "240'", "special_abilities": ["heart-eating"],
        "environments": ["mountains"], "confidence": 0.8,
    }
    entry = build_entry_from_llm(llm, make_candidate(name_guess="Peryton", page=142), get_profile("osr"))
    assert entry["ac"] == 12            # 19 - 7
    attacks = json.loads(entry["attacks"])
    assert attacks[0]["bonus"] == 5     # 20 - 15


def test_validation_flags():
    llm = {
        "is_monster": True, "name": "Weird Thing", "ac": 45, "ac_style": "ascending",
        "thac0": None, "hd_dice": "special", "attacks": [],
        "move": None, "special_abilities": [], "environments": [], "confidence": 0.4,
    }
    entry = build_entry_from_llm(llm, make_candidate(), get_profile("dcc"))
    flags = json.loads(entry["flags"])
    assert "ac_out_of_range" in flags
    assert "hd_unparseable" in flags
    assert "no_attacks" in flags
    assert entry["review_status"] == "pending"


async def test_normalize_candidate_calls_llm(monkeypatch):
    captured = {}

    async def fake_llm(text, prompt_template, api_key, model):
        captured["text"] = text
        return {
            "is_monster": True, "name": "Orc", "ac": 13, "ac_style": "ascending",
            "thac0": None, "hd_dice": "1d8+1",
            "attacks": [{"name": "claw", "bonus": 1, "damage_dice": "1d4"}],
            "move": "30'", "special_abilities": [], "environments": [],
            "confidence": 0.9,
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.processors.monster_normalizer.extract_with_anthropic", fake_llm)

    entry = await normalize_candidate(make_candidate(), get_profile("dcc"))
    assert entry["name"] == "Orc"
    assert "AC 13" in captured["text"]


async def test_normalize_candidate_skips_non_monster(monkeypatch):
    async def fake_llm(text, prompt_template, api_key, model):
        return {"is_monster": False}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.processors.monster_normalizer.extract_with_anthropic", fake_llm)

    assert await normalize_candidate(make_candidate(), get_profile("dcc")) is None


def test_build_entry_from_llm_damage_unparseable():
    """Verify damage_unparseable flag when attack has unparseable damage_dice."""
    llm = {
        "is_monster": True, "name": "Test Beast", "ac": 15, "ac_style": "ascending",
        "thac0": None, "hd_dice": "2d8+2",
        "attacks": [
            {"name": "bite", "bonus": 2, "damage_dice": "1d6+1"},
            {"name": "special attack", "bonus": None, "damage_dice": "special"},
        ],
        "move": "40'", "special_abilities": [], "environments": ["mountains"],
        "confidence": 0.8,
    }
    entry = build_entry_from_llm(llm, make_candidate(), get_profile("dcc"))
    flags = json.loads(entry["flags"])

    # Verify damage_unparseable is present
    assert "damage_unparseable" in flags
    # Verify no_attacks is NOT present (we have attacks)
    assert "no_attacks" not in flags
    # Verify review_status is still pending
    assert entry["review_status"] == "pending"
    # Verify the second attack has None for damage_avg
    attacks = json.loads(entry["attacks"])
    assert attacks[1]["damage_avg"] is None
    assert attacks[0]["damage_avg"] == 4.5  # 1d6+1 should parse


async def test_normalize_candidate_no_provider_configured(monkeypatch):
    """Verify normalize_candidate returns None when no API keys are configured."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = await normalize_candidate(make_candidate(), get_profile("dcc"))
    assert result is None


async def test_normalize_candidate_propagates_llm_error(monkeypatch):
    """Verify exceptions from the LLM helper propagate out of normalize_candidate."""
    async def failing_llm(text, prompt_template, api_key, model):
        raise ValueError("LLM transport error")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("grimoire.processors.monster_normalizer.extract_with_anthropic", failing_llm)

    with pytest.raises(ValueError, match="LLM transport error"):
        await normalize_candidate(make_candidate(), get_profile("dcc"))
