"""API dependencies for dependency injection."""

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.database import get_db
from grimoire.schemas.common import PaginationParams

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_pagination(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=50, ge=1, le=100, description="Items per page"),
) -> PaginationParams:
    """Get pagination parameters from query string."""
    return PaginationParams(page=page, per_page=per_page)


Pagination = Annotated[PaginationParams, Depends(get_pagination)]
