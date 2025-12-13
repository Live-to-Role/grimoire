"""Collection models - user-created groupings of products."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from grimoire.database import Base

if TYPE_CHECKING:
    from grimoire.models.product import Product


class Collection(Base):
    """A user-created collection of products."""

    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    collection_products: Mapped[list["CollectionProduct"]] = relationship(
        "CollectionProduct", back_populates="collection", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Collection(id={self.id}, name='{self.name}')>"


class CollectionProduct(Base):
    """Association table for collections and products."""

    __tablename__ = "collection_products"

    collection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    collection: Mapped["Collection"] = relationship(
        "Collection", back_populates="collection_products"
    )
    product: Mapped["Product"] = relationship("Product", back_populates="collection_products")

    def __repr__(self) -> str:
        return f"<CollectionProduct(collection_id={self.collection_id}, product_id={self.product_id})>"
