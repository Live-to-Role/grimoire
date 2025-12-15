"""Model for tracking deleted duplicate files to prevent re-import."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from grimoire.database import Base


class DeletedDuplicate(Base):
    """Tracks file paths that were deleted as duplicates.
    
    When a duplicate is deleted (record only, not file), we record the path
    here so the scanner knows not to re-import it.
    """

    __tablename__ = "deleted_duplicates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<DeletedDuplicate {self.id}: {self.file_path}>"
