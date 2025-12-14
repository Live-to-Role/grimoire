"""Embedding storage model for semantic search."""

from datetime import datetime, UTC

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, LargeBinary
from sqlalchemy.orm import relationship

from grimoire.database import Base


class ProductEmbedding(Base):
    """Stores vector embeddings for product content chunks."""

    __tablename__ = "product_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    
    embedding = Column(LargeBinary, nullable=False)  # Stored as numpy bytes
    embedding_model = Column(String(100), nullable=False)
    embedding_dim = Column(Integer, nullable=False)
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    product = relationship("Product", backref="embeddings")

    def get_embedding_vector(self) -> list[float]:
        """Deserialize embedding from bytes."""
        import numpy as np
        return np.frombuffer(self.embedding, dtype=np.float32).tolist()

    def set_embedding_vector(self, vector: list[float]):
        """Serialize embedding to bytes."""
        import numpy as np
        self.embedding = np.array(vector, dtype=np.float32).tobytes()
        self.embedding_dim = len(vector)
