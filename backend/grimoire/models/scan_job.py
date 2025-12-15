"""Scan job model for tracking library scan progress."""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from grimoire.database import Base


class ScanJobStatus(str, Enum):
    """Status of a scan job."""
    PENDING = "pending"
    SCANNING = "scanning"      # Discovering files
    HASHING = "hashing"        # Computing file hashes
    PROCESSING = "processing"  # Extracting covers, etc.
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanJob(Base):
    """Tracks progress of a library scan operation."""

    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Which folder is being scanned (null = all folders)
    watched_folder_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Status
    status: Mapped[str] = mapped_column(String(20), default=ScanJobStatus.PENDING.value)
    current_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    current_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Progress
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    new_products: Mapped[int] = mapped_column(Integer, default=0)
    updated_products: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_found: Mapped[int] = mapped_column(Integer, default=0)
    excluded_files: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    
    # Error details
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_files == 0:
            return 0.0
        return round((self.processed_files / self.total_files) * 100, 1)
    
    @property
    def is_running(self) -> bool:
        """Check if scan is currently running."""
        return self.status in (
            ScanJobStatus.PENDING.value,
            ScanJobStatus.SCANNING.value,
            ScanJobStatus.HASHING.value,
            ScanJobStatus.PROCESSING.value,
        )

    def __repr__(self) -> str:
        return f"<ScanJob(id={self.id}, status='{self.status}', progress={self.progress_percent}%)>"
