"""Tag schemas for API validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class TagBase(BaseModel):
    """Base tag fields."""

    name: str = Field(..., min_length=1, max_length=100)
    category: str | None = Field(None, max_length=50)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TagCreate(TagBase):
    """Schema for creating a tag."""

    pass


class TagUpdate(BaseModel):
    """Schema for updating a tag."""

    name: str | None = Field(None, min_length=1, max_length=100)
    category: str | None = Field(None, max_length=50)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TagResponse(TagBase):
    """Schema for tag response."""

    id: int
    created_at: datetime
    product_count: int = 0

    class Config:
        from_attributes = True


class ProductTagAdd(BaseModel):
    """Schema for adding a tag to a product."""

    tag_id: int
