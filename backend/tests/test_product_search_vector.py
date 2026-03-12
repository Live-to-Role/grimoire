"""Tests for per-product search vector computation."""
import numpy as np
import pytest
from grimoire.models.product_search_vector import ProductSearchVector, compute_average_vector


def test_search_vector_roundtrip():
    """Vector can be stored and retrieved."""
    vec = ProductSearchVector(product_id=1, embedding_model="test", embedding_dim=3)
    original = [0.1, 0.2, 0.3]
    vec.set_vector(original)
    retrieved = vec.get_vector()
    np.testing.assert_array_almost_equal(retrieved, original)


def test_average_vectors():
    """Average of chunk vectors produces correct result."""
    chunks = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    avg = compute_average_vector(chunks)
    expected = [1/3, 1/3, 1/3]
    np.testing.assert_array_almost_equal(avg, expected)
