"""Per-product averaged embedding for fast semantic search."""
from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String
from grimoire.database import Base
import numpy as np


def compute_average_vector(chunk_vectors: list[list[float]]) -> list[float]:
    """Average a list of chunk embedding vectors into one product vector."""
    matrix = np.array(chunk_vectors, dtype=np.float32)
    return np.mean(matrix, axis=0).tolist()


def compute_weighted_average_vector(
    vectors: list[list[float]],
    metadata_weight: float = 2.0,
) -> list[float]:
    """Compute weighted average of chunk vectors, boosting the first (metadata) chunk.

    Args:
        vectors: List of embedding vectors (first is assumed to contain metadata preamble)
        metadata_weight: Weight multiplier for the first chunk (default 2x)
    """
    if not vectors:
        return []
    if len(vectors) == 1:
        return vectors[0]

    arr = np.array(vectors, dtype=np.float32)
    weights = np.ones(len(vectors), dtype=np.float32)
    weights[0] = metadata_weight
    weighted = np.average(arr, axis=0, weights=weights)
    return weighted.tolist()


class ProductSearchVector(Base):
    """One averaged embedding per product for fast semantic search."""

    __tablename__ = "product_search_vectors"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    vector = Column(LargeBinary, nullable=False)
    embedding_model = Column(String(100), nullable=False)
    embedding_dim = Column(Integer, nullable=False)

    def get_vector(self) -> list[float]:
        if self.vector is not None:
            return np.frombuffer(self.vector, dtype=np.float32).tolist()
        return []

    def set_vector(self, vec: list[float]):
        self.vector = np.array(vec, dtype=np.float32).tobytes()
        self.embedding_dim = len(vec)
