"""Tag models - flexible metadata for products."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from grimoire.database import Base

if TYPE_CHECKING:
    from grimoire.models.product import Product


class Tag(Base):
    """A tag for categorizing products."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    product_tags: Mapped[list["ProductTag"]] = relationship(
        "ProductTag", back_populates="tag", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name='{self.name}')>"


class ProductTag(Base):
    """Association table for products and tags."""

    __tablename__ = "product_tags"

    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(20), default="user")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="product_tags")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="product_tags")

    def __repr__(self) -> str:
        return f"<ProductTag(product_id={self.product_id}, tag_id={self.tag_id})>"
