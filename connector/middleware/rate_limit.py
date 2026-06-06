"""Redis-based rate limiting middleware."""
from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, Request, status

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
_redis: Any = None


def _get_redis() -> Any:
    global _redis  # noqa: PLW0603
    if _redis is None:
        try:
            import redis.asyncio as aioredis  # type: ignore[import]
            _redis = aioredis.from_url(_REDIS_URL, decode_responses=True)
        except ImportError:
            return None
    return _redis


async def rate_limit(request: Request, limit: int = 100, window: int = 60) -> None:
    """Sliding-window rate limiter using Redis INCR + EXPIRE.

    limit: max requests per window
    window: window size in seconds
    """
    r = _get_redis()
    if r is None:
        return  # Redis not available — skip rate limiting (dev mode)

    key = f"rl:{request.client.host if request.client else 'anon'}:{request.url.path}"
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window)
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({limit} req/{window}s)",
                headers={"Retry-After": str(window)},
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass  # Redis error — degrade gracefully, don't block the request
