"""Per-product averaged embedding for fast semantic search."""
from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String
from grimoire.database import Base
import numpy as np


def compute_average_vector(chunk_vectors: list[list[float]]) -> list[float]:
    """Average a list of chunk embedding vectors into one product vector."""
    matrix = np.array(chunk_vectors, dtype=np.float32)
    return np.mean(matrix, axis=0).tolist()


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
