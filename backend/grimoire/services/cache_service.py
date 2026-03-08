"""Redis cache service for filter options and other frequently accessed data."""

import logging
from typing import Any

import redis.asyncio as redis
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.config import settings
from grimoire.models import Product

logger = logging.getLogger(__name__)


class CacheService:
    """Service for caching frequently accessed data in Redis."""
    
    def __init__(self):
        self.redis_client: redis.Redis | None = None
        self._connected = False
        
    async def connect(self):
        """Connect to Redis."""
        try:
            self.redis_client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
            )
            # Test connection
            await self.redis_client.ping()
            self._connected = True
            logger.info("Connected to Redis successfully")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Cache will be disabled.")
            self._connected = False
            self.redis_client = None
    
    async def disconnect(self):
        """Disconnect from Redis."""
        if self.redis_client:
            await self.redis_client.close()
            self._connected = False
            logger.info("Disconnected from Redis")
    
    def is_available(self) -> bool:
        """Check if Redis is available."""
        return self._connected and self.redis_client is not None
    
    async def get_filter_options(
        self,
        db: AsyncSession,
        field: str,
    ) -> list[str]:
        """Get filter options for a field, using cache if available.
        
        Args:
            db: Database session
            field: Field name (game_system, publisher, author, genre, product_type)
            
        Returns:
            List of unique values for the field
        """
        cache_key = f"filters:{field}"
        
        # Try to get from cache
        if self.is_available():
            try:
                cached = await self.redis_client.get(cache_key)
                if cached:
                    # Redis stores as JSON string
                    import json
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"Redis get failed for {cache_key}: {e}")
        
        # Cache miss or Redis unavailable - query database
        values = await self._query_filter_options(db, field)
        
        # Store in cache
        if self.is_available():
            try:
                import json
                await self.redis_client.setex(
                    cache_key,
                    3600,  # 1 hour TTL
                    json.dumps(values)
                )
            except Exception as e:
                logger.warning(f"Redis set failed for {cache_key}: {e}")
        
        return values
    
    async def _query_filter_options(
        self,
        db: AsyncSession,
        field: str,
    ) -> list[str]:
        """Query database for unique filter values.
        
        Args:
            db: Database session
            field: Field name to query
            
        Returns:
            List of unique non-null values
        """
        column = getattr(Product, field, None)
        if column is None:
            logger.error(f"Invalid field name: {field}")
            return []
        
        query = (
            select(column)
            .where(column.isnot(None))
            .distinct()
            .order_by(column)
        )
        
        result = await db.execute(query)
        values = [row[0] for row in result.fetchall()]
        return values
    
    async def invalidate_filter_options(self):
        """Invalidate all filter option caches.
        
        Called when products are added, updated, or deleted.
        """
        if not self.is_available():
            return
        
        try:
            # Delete all filter cache keys
            keys = await self.redis_client.keys("filters:*")
            if keys:
                await self.redis_client.delete(*keys)
                logger.info(f"Invalidated {len(keys)} filter cache keys")
        except Exception as e:
            logger.warning(f"Failed to invalidate filter caches: {e}")
    
    async def clear_all(self):
        """Clear all cached data (admin function)."""
        if not self.is_available():
            return
        
        try:
            await self.redis_client.flushdb()
            logger.info("Cleared all Redis cache")
        except Exception as e:
            logger.warning(f"Failed to clear Redis cache: {e}")


# Global cache service instance
_cache_service: CacheService | None = None


async def get_cache_service() -> CacheService:
    """Get the global cache service instance."""
    global _cache_service
    
    if _cache_service is None:
        _cache_service = CacheService()
        await _cache_service.connect()
    
    return _cache_service


async def shutdown_cache_service():
    """Shutdown the cache service."""
    global _cache_service
    
    if _cache_service:
        await _cache_service.disconnect()
        _cache_service = None
