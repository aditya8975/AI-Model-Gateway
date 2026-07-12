"""
Sliding-window rate limiter backed by Redis sorted sets.

For each API key we keep a ZSET keyed `ratelimit:{key_id}` where each
member is a unique request token and the score is the request's Unix
timestamp (ms). On every request we:
  1. Drop entries older than the window.
  2. Count remaining entries.
  3. If count >= limit -> reject with 429 (+ Retry-After).
  4. Otherwise add the new entry and allow.

This is accurate (no fixed-window boundary bursting) and O(log N) per
request. TTL on the key ensures idle keys don't leak memory.
"""
import time
import uuid

from fastapi import Depends, HTTPException, Request, status

from app.auth import AuthenticatedKey, get_current_api_key
from app.logging_config import get_logger
from app.redis_client import redis_client

logger = get_logger("rate_limiter")


async def enforce_rate_limit(
    request: Request,
    auth_key: AuthenticatedKey = Depends(get_current_api_key),
) -> AuthenticatedKey:
    limit = auth_key.rate_limit
    window = auth_key.rate_window_seconds
    redis_key = f"ratelimit:{auth_key.id}"

    now_ms = time.time() * 1000
    window_start_ms = now_ms - (window * 1000)

    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(redis_key, 0, window_start_ms)
    pipe.zcard(redis_key)
    _, current_count = await pipe.execute()

    if current_count >= limit:
        oldest = await redis_client.zrange(redis_key, 0, 0, withscores=True)
        retry_after = 1
        if oldest:
            oldest_ts = oldest[0][1]
            retry_after = max(1, int(((oldest_ts + window * 1000) - now_ms) / 1000))

        logger.warning(
            "Rate limit exceeded",
            extra={"api_key_id": auth_key.id, "limit": limit, "window": window},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {limit} requests per {window}s.",
            headers={"Retry-After": str(retry_after)},
        )

    member = f"{now_ms}:{uuid.uuid4().hex[:8]}"
    pipe = redis_client.pipeline()
    pipe.zadd(redis_key, {member: now_ms})
    pipe.expire(redis_key, window * 2)
    await pipe.execute()

    request.state.rate_limit_remaining = max(0, limit - current_count - 1)
    request.state.rate_limit_limit = limit

    return auth_key
