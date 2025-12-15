"""WatchedFolder model - directories to scan for PDFs."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from grimoire.database import Base

if TYPE_CHECKING:
    from grimoire.models.product import Product


class WatchedFolder(Base):
    """A folder being watched for PDF files."""

    __tablename__ = "watched_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_source_of_truth: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    products: Mapped[list["Product"]] = relationship(
        "Product", back_populates="watched_folder"
    )

    def __repr__(self) -> str:
        return f"<WatchedFolder(id={self.id}, path='{self.path}')>"
