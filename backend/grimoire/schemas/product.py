"""Product schemas for API validation."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from grimoire.schemas.tag import TagResponse


class ProcessingStatus(BaseModel):
    """Processing status for a product."""

    cover_extracted: bool
    text_extracted: bool
    deep_indexed: bool
    ai_identified: bool


class ProductBase(BaseModel):
    """Base product fields."""

    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    publication_year: int | None = None
    game_system: str | None = None
    genre: str | None = None
    product_type: str | None = None
    level_range_min: int | None = None
    level_range_max: int | None = None
    party_size_min: int | None = None
    party_size_max: int | None = None
    estimated_runtime: str | None = None


class ProductCreate(ProductBase):
    """Schema for creating a product (internal use - products are created via scanning)."""

    file_path: str
    file_name: str
    file_size: int
    file_hash: str
    watched_folder_id: int | None = None


class ProductUpdate(BaseModel):
    """Schema for updating product metadata."""

    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    publication_year: int | None = None
    game_system: str | None = None
    genre: str | None = None
    product_type: str | None = None
    level_range_min: int | None = None
    level_range_max: int | None = None
    party_size_min: int | None = None
    party_size_max: int | None = None
    estimated_runtime: str | None = None


class RunStatus(BaseModel):
    """Run tracking status for a product."""

    status: str | None = None  # want_to_run, running, completed
    rating: int | None = None  # 1-5 stars
    difficulty: str | None = None  # easier, as_written, harder
    completed_at: datetime | None = None


class ProductResponse(ProductBase):
    """Schema for product response."""

    id: int
    file_path: str
    file_name: str
    file_size: int
    page_count: int | None
    cover_url: str | None = None
    tags: list[TagResponse] = []
    processing_status: ProcessingStatus
    run_status: RunStatus | None = None
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None = None

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    """Paginated list of products."""

    items: list[ProductResponse]
    total: int
    page: int
    per_page: int
    pages: int


class ProductProcessRequest(BaseModel):
    """Request to process a product."""

    tasks: list[Literal["cover", "text", "deep_index", "identify", "extract"]] = Field(
        default=["cover"], description="Processing tasks to run"
    )


class ProductProcessResponse(BaseModel):
    """Response after queuing processing tasks."""

    queue_ids: list[int]
    message: str
