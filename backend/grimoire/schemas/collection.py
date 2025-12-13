"""Collection schemas for API validation."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CollectionBase(BaseModel):
    """Base collection fields."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = None


class CollectionCreate(CollectionBase):
    """Schema for creating a collection."""

    pass


class CollectionUpdate(BaseModel):
    """Schema for updating a collection."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = None
    sort_order: int | None = None


class CollectionResponse(CollectionBase):
    """Schema for collection response."""

    id: int
    sort_order: int
    created_at: datetime
    updated_at: datetime
    product_count: int = 0

    class Config:
        from_attributes = True


class CollectionProductAdd(BaseModel):
    """Schema for adding a product to a collection."""

    product_id: int


class CollectionWithProducts(CollectionResponse):
    """Collection with its products."""

    products: list[Any] = []
