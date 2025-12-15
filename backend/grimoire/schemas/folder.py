"""Watched folder schemas for API validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class WatchedFolderBase(BaseModel):
    """Base watched folder fields."""

    path: str = Field(..., min_length=1)
    label: str | None = Field(None, max_length=255)


class WatchedFolderCreate(WatchedFolderBase):
    """Schema for creating a watched folder."""

    pass


class WatchedFolderUpdate(BaseModel):
    """Schema for updating a watched folder."""

    label: str | None = Field(None, max_length=255)
    enabled: bool | None = None
    is_source_of_truth: bool | None = None


class WatchedFolderResponse(WatchedFolderBase):
    """Schema for watched folder response."""

    id: int
    enabled: bool
    is_source_of_truth: bool = False
    last_scanned_at: datetime | None
    created_at: datetime
    product_count: int = 0

    class Config:
        from_attributes = True


class ScanRequest(BaseModel):
    """Request to scan library folders."""

    folder_id: int | None = Field(None, description="Specific folder to scan, or null for all")
    force: bool = Field(False, description="Re-scan unchanged files")


class ScanResponse(BaseModel):
    """Response after initiating a scan."""

    message: str
    folders_queued: int


class LibraryStats(BaseModel):
    """Library statistics."""

    total_products: int
    total_pages: int
    total_size_bytes: int
    by_system: dict[str, int]
    by_type: dict[str, int]
    by_genre: dict[str, int]
    by_author: dict[str, int]
    by_publisher: dict[str, int]
    processing_status: dict[str, int]
