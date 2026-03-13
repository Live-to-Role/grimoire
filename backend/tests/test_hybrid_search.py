"""Tests for hybrid search score fusion."""
from grimoire.services.hybrid_search import reciprocal_rank_fusion


def test_rrf_merges_two_ranked_lists():
    """reciprocal_rank_fusion merges two ranked lists, boosting items in both."""
    # (product_id, score) tuples, already sorted by score desc
    semantic_results = [(1, 0.95), (3, 0.80), (5, 0.70)]
    keyword_results = [(3, 5.0), (2, 4.0), (1, 3.0)]
    merged = reciprocal_rank_fusion(semantic_results, keyword_results, k=60)
    ids = [pid for pid, _ in merged]
    # Product 3 appears in both lists at good ranks — should be #1 or #2
    assert 3 in ids[:2]
    # All 4 unique products should appear
    assert set(ids) == {1, 2, 3, 5}


def test_rrf_empty_keyword_list():
    """reciprocal_rank_fusion works when keyword results are empty."""
    semantic = [(1, 0.9), (2, 0.8)]
    merged = reciprocal_rank_fusion(semantic, [], k=60)
    assert len(merged) == 2
    assert merged[0][0] == 1


def test_rrf_empty_semantic_list():
    """reciprocal_rank_fusion works when semantic results are empty."""
    keyword = [(1, 5.0), (2, 3.0)]
    merged = reciprocal_rank_fusion([], keyword, k=60)
    assert len(merged) == 2
    assert merged[0][0] == 1


def test_rrf_handles_duplicate_ids():
    """Items in both lists get boosted, not duplicated."""
    semantic = [(1, 0.9), (2, 0.8), (3, 0.7)]
    keyword = [(2, 5.0), (3, 4.0), (4, 3.0)]
    merged = reciprocal_rank_fusion(semantic, keyword)
    ids = [pid for pid, _ in merged]
    # No duplicates
    assert len(ids) == len(set(ids))
    # Product 2 is high in both — should rank well
    assert ids.index(2) <= 1
