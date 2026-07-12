"""
Async Redis client singleton, used for:
  - rate limiting (sliding window counters)
  - request queue (Redis Streams)
  - job status / result cache
  - API key cache (avoid hitting Postgres on every request)
"""
import redis.asyncio as redis

from app.config import settings

redis_client: redis.Redis = redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
    max_connections=50,
)


async def ping_redis() -> bool:
    try:
        return await redis_client.ping()
    except Exception:
        return False
