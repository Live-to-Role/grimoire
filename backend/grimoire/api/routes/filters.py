"""Filter options API endpoints with Redis caching."""

from fastapi import APIRouter, Depends

from grimoire.api.deps import DbSession
from grimoire.services.cache_service import get_cache_service, CacheService

router = APIRouter()


@router.get("/game-systems")
async def get_game_systems(
    db: DbSession,
    cache: CacheService = Depends(get_cache_service),
) -> list[str]:
    """Get all unique game systems (cached)."""
    return await cache.get_filter_options(db, "game_system")


@router.get("/publishers")
async def get_publishers(
    db: DbSession,
    cache: CacheService = Depends(get_cache_service),
) -> list[str]:
    """Get all unique publishers (cached)."""
    return await cache.get_filter_options(db, "publisher")


@router.get("/authors")
async def get_authors(
    db: DbSession,
    cache: CacheService = Depends(get_cache_service),
) -> list[str]:
    """Get all unique authors (cached)."""
    return await cache.get_filter_options(db, "author")


@router.get("/genres")
async def get_genres(
    db: DbSession,
    cache: CacheService = Depends(get_cache_service),
) -> list[str]:
    """Get all unique genres (cached)."""
    return await cache.get_filter_options(db, "genre")


@router.get("/product-types")
async def get_product_types(
    db: DbSession,
    cache: CacheService = Depends(get_cache_service),
) -> list[str]:
    """Get all unique product types (cached)."""
    return await cache.get_filter_options(db, "product_type")


@router.post("/clear-cache")
async def clear_filter_cache(
    cache: CacheService = Depends(get_cache_service),
) -> dict:
    """Clear all filter caches (admin endpoint)."""
    await cache.invalidate_filter_options()
    return {"message": "Filter caches cleared successfully"}
