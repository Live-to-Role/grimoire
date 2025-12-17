"""Common schemas used across the API."""

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""

    page: int = Field(default=1, ge=1, description="Page number")
    per_page: int = Field(default=50, ge=1, le=10000, description="Items per page")


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str
    success: bool = True


class PaginatedResponse(BaseModel):
    """Base class for paginated responses."""

    total: int
    page: int
    per_page: int
    pages: int
