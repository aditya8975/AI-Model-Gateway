"""
API Key authentication.

Keys are generated as `gw_<32 random url-safe chars>`, stored in Postgres
as a SHA-256 hash (never plaintext), and cached in Redis for fast lookups
so hot-path requests don't hit Postgres every time.
"""
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import api_key_id_ctx, get_logger
from app.models.db_models import APIKey
from app.redis_client import redis_client

logger = get_logger("auth")

_api_key_header = APIKeyHeader(name=settings.API_KEY_HEADER, auto_error=False)

CACHE_TTL_SECONDS = 300


def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext_key, sha256_hash, prefix_for_display)."""
    plaintext = f"gw_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    prefix = plaintext[:10]
    return plaintext, key_hash, prefix


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


@dataclass
class AuthenticatedKey:
    id: str
    name: str
    rate_limit: int
    rate_window_seconds: int
    allowed_scopes: str
    is_active: bool

    def can_access(self, task: str) -> bool:
        if self.allowed_scopes == "*":
            return True
        return task in {s.strip() for s in self.allowed_scopes.split(",")}


async def _lookup_key_cached(key_hash: str, db: AsyncSession) -> AuthenticatedKey | None:
    cache_key = f"apikey:{key_hash}"
    cached = await redis_client.get(cache_key)
    if cached is not None:
        if cached == "__missing__":
            return None
        data = json.loads(cached)
        return AuthenticatedKey(**data)

    result = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash))
    row = result.scalar_one_or_none()

    if row is None or not row.is_active:
        await redis_client.set(cache_key, "__missing__", ex=CACHE_TTL_SECONDS)
        return None

    auth_key = AuthenticatedKey(
        id=row.id,
        name=row.name,
        rate_limit=row.rate_limit,
        rate_window_seconds=row.rate_window_seconds,
        allowed_scopes=row.allowed_scopes,
        is_active=row.is_active,
    )
    await redis_client.set(
        cache_key, json.dumps(auth_key.__dict__), ex=CACHE_TTL_SECONDS
    )

    # Fire-and-forget last_used_at update (best effort)
    await db.execute(
        update(APIKey)
        .where(APIKey.id == row.id)
        .values(last_used_at=datetime.now(timezone.utc))
    )
    await db.commit()

    return auth_key


async def get_current_api_key(
    api_key: str | None = Security(_api_key_header),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedKey:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing API key. Provide it via the '{settings.API_KEY_HEADER}' header.",
        )

    key_hash = hash_key(api_key)
    auth_key = await _lookup_key_cached(key_hash, db)

    if auth_key is None:
        logger.warning("Rejected request: invalid API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )

    api_key_id_ctx.set(auth_key.id)
    return auth_key


async def require_admin(api_key: str | None = Security(_api_key_header)) -> None:
    if not api_key or not secrets.compare_digest(api_key, settings.ADMIN_MASTER_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin master key required for this endpoint.",
        )


async def invalidate_key_cache(key_hash: str) -> None:
    await redis_client.delete(f"apikey:{key_hash}")
