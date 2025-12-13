"""Pydantic schemas for API request/response validation."""

from grimoire.schemas.product import (
    ProductCreate,
    ProductUpdate,
    ProductResponse,
    ProductListResponse,
    ProductProcessRequest,
)
from grimoire.schemas.collection import (
    CollectionCreate,
    CollectionUpdate,
    CollectionResponse,
    CollectionWithProducts,
)
from grimoire.schemas.tag import TagCreate, TagUpdate, TagResponse
from grimoire.schemas.folder import WatchedFolderCreate, WatchedFolderResponse
from grimoire.schemas.common import PaginationParams, MessageResponse

__all__ = [
    "ProductCreate",
    "ProductUpdate",
    "ProductResponse",
    "ProductListResponse",
    "ProductProcessRequest",
    "CollectionCreate",
    "CollectionUpdate",
    "CollectionResponse",
    "CollectionWithProducts",
    "TagCreate",
    "TagUpdate",
    "TagResponse",
    "WatchedFolderCreate",
    "WatchedFolderResponse",
    "PaginationParams",
    "MessageResponse",
]
