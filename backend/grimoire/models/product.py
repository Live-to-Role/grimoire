"""Product model - represents a PDF in the library."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from grimoire.database import Base

if TYPE_CHECKING:
    from grimoire.models.collection import CollectionProduct
    from grimoire.models.folder import WatchedFolder
    from grimoire.models.tag import ProductTag


class Product(Base):
    """A PDF product in the library."""

    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_title", "title"),
        Index("ix_products_game_system", "game_system"),
        Index("ix_products_product_type", "product_type"),
        Index("ix_products_created_at", "created_at"),
        Index("ix_products_file_hash", "file_hash"),
        Index("ix_products_publisher", "publisher"),
        Index("ix_products_is_duplicate", "is_duplicate"),
        Index("ix_products_file_size", "file_size"),
        Index("ix_products_system_type", "game_system", "product_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # File information
    file_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    watched_folder_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("watched_folders.id"), nullable=True
    )

    # Basic metadata
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Classification
    game_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Adventure-specific
    level_range_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level_range_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    party_size_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    party_size_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_runtime: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Processing status
    cover_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    text_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    deep_indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_identified: Mapped[bool] = mapped_column(Boolean, default=False)

    # AI confidence scores
    identification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    system_detection_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Paths to extracted content
    cover_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Duplicate detection
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True
    )
    duplicate_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 'exact_hash', 'same_content'

    # Exclusion/missing status
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_by_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exclusion_override: Mapped[bool] = mapped_column(Boolean, default=False)  # User forced include
    is_missing: Mapped[bool] = mapped_column(Boolean, default=False)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    file_modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    watched_folder: Mapped["WatchedFolder | None"] = relationship(
        "WatchedFolder", back_populates="products"
    )
    product_tags: Mapped[list["ProductTag"]] = relationship(
        "ProductTag", back_populates="product", cascade="all, delete-orphan"
    )
    collection_products: Mapped[list["CollectionProduct"]] = relationship(
        "CollectionProduct", back_populates="product", cascade="all, delete-orphan"
    )
    
    # Self-referential relationship for duplicates
    duplicate_of: Mapped["Product | None"] = relationship(
        "Product", remote_side="Product.id", foreign_keys="Product.duplicate_of_id"
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, title='{self.title}', file_name='{self.file_name}')>"
