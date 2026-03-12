"""Tests for fast semantic search with averaged vectors."""
import numpy as np
import pytest
from grimoire.services.embeddings import search_product_vectors


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
