"""Heuristic query interpretation: levels, systems, types, stripping."""
import pytest

from grimoire.services.query_interpreter import (
    Interpretation,
    _validate_llm_result,
    interpret_heuristic,
)

SYSTEMS = ["D&D 5E", "Pathfinder 2E", "Dungeon Crawl Classics", "OSR"]
TYPES = ["Adventure", "Sourcebook", "Bestiary", "Setting", "Art/Maps"]


@pytest.mark.parametrize("query,lmin,lmax", [
    ("Undead adventure for 3rd level characters", 3, 3),
    ("undead adventure level 3", 3, 3),
    ("dungeon crawl levels 2-4", 2, 4),
    ("wilderness levels 5 to 7", 5, 7),
    ("funnel adventure for level 0 characters", 0, 0),
    ("swamp horror", None, None),
])
def test_level_extraction(query, lmin, lmax):
    r = interpret_heuristic(query, SYSTEMS, TYPES)
    assert r.level_min == lmin
    assert r.level_max == lmax


def test_level_phrase_stripped_from_semantic_query():
    r = interpret_heuristic("Undead adventure for 3rd level characters", SYSTEMS, TYPES)
    assert "3rd" not in r.semantic_query
    assert "level" not in r.semantic_query.lower()
    assert "undead" in r.semantic_query.lower()
    assert "adventure" in r.semantic_query.lower()  # topical word kept


def test_game_system_alias_dcc():
    r = interpret_heuristic("dcc funnel adventure", SYSTEMS, TYPES)
    assert r.game_system == "Dungeon Crawl Classics"
    assert "dcc" in r.semantic_query.lower()  # system word kept for content matching


def test_game_system_full_name_match():
    r = interpret_heuristic("pathfinder 2e bestiary of dragons", SYSTEMS, TYPES)
    assert r.game_system == "Pathfinder 2E"


def test_product_type_keyword_sets_filter_but_stays_in_query():
    r = interpret_heuristic("undead adventure", SYSTEMS, TYPES)
    assert r.product_type == "Adventure"
    assert "adventure" in r.semantic_query.lower()


def test_unknown_system_not_invented():
    r = interpret_heuristic("shadowdark ruins", SYSTEMS, TYPES)
    assert r.game_system is None


def test_semantic_query_never_empty():
    r = interpret_heuristic("level 3", SYSTEMS, TYPES)
    assert r.semantic_query.strip()  # falls back to the original query


def test_validate_llm_result_clamps_and_drops():
    base = Interpretation(semantic_query="orig")
    out = _validate_llm_result(
        {"level_min": -5, "level_max": 99, "game_system": "Nonsense RPG",
         "product_type": "Adventure", "semantic_query": "undead crypts"},
        base, SYSTEMS, TYPES,
    )
    assert out.level_min == 0
    assert out.level_max == 30
    assert out.game_system is None       # not a known value -> dropped
    assert out.product_type == "Adventure"
    assert out.semantic_query == "undead crypts"
    assert out.source == "llm"


def test_validate_llm_result_empty_semantic_query_keeps_heuristic():
    base = Interpretation(semantic_query="orig words")
    out = _validate_llm_result({"semantic_query": "  "}, base, SYSTEMS, TYPES)
    assert out.semantic_query == "orig words"
