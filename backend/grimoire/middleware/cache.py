"""Response caching middleware for frequently accessed endpoints."""

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from grimoire.config import settings


@dataclass
class CacheEntry:
    """A cached response entry."""
    content: bytes
    content_type: str
    status_code: int
    created_at: float
    ttl: int
    
    def is_expired(self) -> bool:
        return time.time() > self.created_at + self.ttl


class ResponseCache:
    """In-memory response cache with TTL support."""
    
    def __init__(self, max_size: int = 1000):
        self.cache: dict[str, CacheEntry] = {}
        self.max_size = max_size
    
    def get(self, key: str) -> CacheEntry | None:
        entry = self.cache.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            del self.cache[key]
            return None
        return entry
    
    def set(self, key: str, entry: CacheEntry) -> None:
        # Evict old entries if cache is full
        if len(self.cache) >= self.max_size:
            self._evict_expired()
        if len(self.cache) >= self.max_size:
            # Remove oldest entry
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k].created_at)
            del self.cache[oldest_key]
        self.cache[key] = entry
    
    def invalidate(self, pattern: str | None = None) -> int:
        """Invalidate cache entries matching pattern or all if None."""
        if pattern is None:
            count = len(self.cache)
            self.cache.clear()
            return count
        
        keys_to_delete = [k for k in self.cache if pattern in k]
        for key in keys_to_delete:
            del self.cache[key]
        return len(keys_to_delete)
    
    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self.cache.items() if v.is_expired()]
        for key in expired:
            del self.cache[key]


# Global cache instance
response_cache = ResponseCache()


# Paths that should be cached with their TTL in seconds
CACHEABLE_PATHS: dict[str, int] = {
    "/api/v1/folders/library/stats": 60,  # Library stats - 1 minute
    "/api/v1/collections": 30,  # Collections list - 30 seconds
    "/api/v1/tags": 30,  # Tags list - 30 seconds
}

# Paths that should never be cached
NEVER_CACHE_PATHS = frozenset([
    "/api/v1/health",
    "/api/v1/ai/",
    "/api/v1/structured/",
    "/api/v1/export/",
])


def get_cache_key(request: Request) -> str:
    """Generate a cache key from the request."""
    path = request.url.path
    query = str(sorted(request.query_params.items()))
    key_data = f"{request.method}:{path}:{query}"
    return hashlib.md5(key_data.encode()).hexdigest()


def should_cache(request: Request) -> tuple[bool, int]:
    """Check if request should be cached and return TTL."""
    if request.method != "GET":
        return False, 0
    
    path = request.url.path
    
    # Check never cache paths
    for never_cache in NEVER_CACHE_PATHS:
        if path.startswith(never_cache):
            return False, 0
    
    # Check exact matches first
    if path in CACHEABLE_PATHS:
        return True, CACHEABLE_PATHS[path]
    
    # Check prefix matches
    for cacheable_path, ttl in CACHEABLE_PATHS.items():
        if path.startswith(cacheable_path):
            return True, ttl
    
    return False, 0


class CacheMiddleware(BaseHTTPMiddleware):
    """Middleware that caches GET responses for configured endpoints."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cacheable, ttl = should_cache(request)
        
        if not cacheable:
            return await call_next(request)
        
        cache_key = get_cache_key(request)
        
        # Check cache
        cached = response_cache.get(cache_key)
        if cached:
            response = Response(
                content=cached.content,
                status_code=cached.status_code,
                media_type=cached.content_type,
            )
            response.headers["X-Cache"] = "HIT"
            response.headers["Cache-Control"] = f"max-age={ttl}"
            return response
        
        # Get fresh response
        response = await call_next(request)
        
        # Only cache successful responses
        if response.status_code == 200:
            # Read response body
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            
            # Store in cache
            entry = CacheEntry(
                content=body,
                content_type=response.media_type or "application/json",
                status_code=response.status_code,
                created_at=time.time(),
                ttl=ttl,
            )
            response_cache.set(cache_key, entry)
            
            # Return new response with body
            new_response = Response(
                content=body,
                status_code=response.status_code,
                media_type=response.media_type,
            )
            new_response.headers["X-Cache"] = "MISS"
            new_response.headers["Cache-Control"] = f"max-age={ttl}"
            return new_response
        
        return response


def invalidate_cache(pattern: str | None = None) -> int:
    """Invalidate cache entries. Call after data mutations."""
    return response_cache.invalidate(pattern)
