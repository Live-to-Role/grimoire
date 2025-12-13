"""Rate limiting middleware for API endpoints."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from grimoire.config import settings


@dataclass
class RateLimitBucket:
    """Token bucket for rate limiting."""
    requests: list[float] = field(default_factory=list)
    
    def is_allowed(self, max_requests: int, window_seconds: int) -> bool:
        """Check if request is allowed and record it."""
        now = time.time()
        cutoff = now - window_seconds
        
        # Remove old requests outside the window
        self.requests = [t for t in self.requests if t > cutoff]
        
        if len(self.requests) >= max_requests:
            return False
        
        self.requests.append(now)
        return True
    
    def time_until_reset(self, window_seconds: int) -> float:
        """Get seconds until oldest request expires."""
        if not self.requests:
            return 0
        return max(0, self.requests[0] + window_seconds - time.time())


class RateLimiter:
    """In-memory rate limiter using sliding window."""
    
    def __init__(self):
        self.buckets: dict[str, RateLimitBucket] = defaultdict(RateLimitBucket)
    
    def is_allowed(
        self, 
        key: str, 
        max_requests: int, 
        window_seconds: int
    ) -> tuple[bool, float]:
        """
        Check if request is allowed.
        
        Returns:
            Tuple of (is_allowed, seconds_until_reset)
        """
        bucket = self.buckets[key]
        allowed = bucket.is_allowed(max_requests, window_seconds)
        reset_time = bucket.time_until_reset(window_seconds)
        return allowed, reset_time


# Global rate limiter instance
rate_limiter = RateLimiter()


# Paths that should use stricter AI rate limits
AI_PATHS = frozenset([
    "/api/v1/ai/",
    "/api/v1/structured/",
    "/api/v1/semantic/",
])


def get_client_ip(request: Request) -> str:
    """Get client IP address from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that applies rate limiting to API requests."""
    
    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        if not settings.rate_limit_enabled:
            return await call_next(request)
        
        # Skip rate limiting for non-API paths
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        
        # Determine rate limit based on path
        is_ai_path = any(path.startswith(p) for p in AI_PATHS)
        if is_ai_path:
            max_requests = settings.ai_rate_limit_requests
            window = settings.ai_rate_limit_window
        else:
            max_requests = settings.rate_limit_requests
            window = settings.rate_limit_window
        
        # Get client identifier
        client_ip = get_client_ip(request)
        key = f"{client_ip}:{path.split('/')[3] if len(path.split('/')) > 3 else 'api'}"
        
        # Check rate limit
        allowed, reset_time = rate_limiter.is_allowed(key, max_requests, window)
        
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": round(reset_time, 1),
                },
                headers={
                    "Retry-After": str(int(reset_time) + 1),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + reset_time)),
                },
            )
        
        # Process request and add rate limit headers
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, max_requests - len(rate_limiter.buckets[key].requests))
        )
        
        return response
