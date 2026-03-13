"""Tests for fast semantic search with averaged vectors."""
from types import SimpleNamespace

import numpy as np
import pytest
from grimoire.services.embeddings import build_metadata_preamble, search_product_vectors


def test_search_product_vectors_returns_top_k():
    """search_product_vectors returns top-k products by cosine similarity."""
    query = [1.0, 0.0, 0.0]
    product_vectors = {
        1: [1.0, 0.0, 0.0],   # exact match
        2: [0.0, 1.0, 0.0],   # orthogonal
        3: [0.7, 0.7, 0.0],   # partial match
    }
    results = search_product_vectors(query, product_vectors, top_k=2)
    assert len(results) == 2
    assert results[0][0] == 1  # best match
    assert results[1][0] == 3  # second best


def test_search_product_vectors_empty():
    """search_product_vectors handles empty input."""
    results = search_product_vectors([1.0, 0.0], {}, top_k=5)
    assert results == []


def test_search_product_vectors_threshold():
    """search_product_vectors filters by threshold."""
    query = [1.0, 0.0, 0.0]
    product_vectors = {
        1: [1.0, 0.0, 0.0],   # score = 1.0
        2: [0.0, 1.0, 0.0],   # score = 0.0
    }
    results = search_product_vectors(query, product_vectors, top_k=10, threshold=0.5)
    assert len(results) == 1
    assert results[0][0] == 1


def test_semantic_search_request_accepts_filters():
    """SemanticSearchRequest accepts optional filter fields."""
    from grimoire.api.routes.semantic import SemanticSearchRequest

    req = SemanticSearchRequest(
        query="undead adventure",
        game_system="Dungeon Crawl Classics",
        product_type="adventure",
        level_min=1,
        level_max=3,
        publisher="Goodman Games",
    )
    assert req.game_system == "Dungeon Crawl Classics"
    assert req.level_min == 1
    assert req.level_max == 3


def test_build_metadata_preamble_includes_fields():
    """build_metadata_preamble includes key product metadata."""
    product = SimpleNamespace(
        title="Sailors on the Starless Sea",
        game_system="Dungeon Crawl Classics",
        publisher="Goodman Games",
        product_type="adventure",
        author="Harley Stroh",
        setting=None,
        genre="fantasy",
        series=None,
        series_order=None,
        level_range_min=0,
        level_range_max=0,
        description="A zero-level funnel adventure",
        themes='["dungeon crawl", "undead"]',
        content_warnings=None,
    )
    preamble = build_metadata_preamble(product)
    assert "Dungeon Crawl Classics" in preamble
    assert "Goodman Games" in preamble
    assert "Sailors on the Starless Sea" in preamble
    assert "undead" in preamble
    assert "Level Range: 0-0" in preamble


def test_build_metadata_preamble_empty_product():
    """build_metadata_preamble returns empty string for product with no metadata."""
    product = SimpleNamespace(
        title=None, game_system=None, publisher=None, product_type=None,
        author=None, setting=None, genre=None, series=None, series_order=None,
        level_range_min=None, level_range_max=None, description=None,
        themes=None, content_warnings=None,
    )
    assert build_metadata_preamble(product) == ""
