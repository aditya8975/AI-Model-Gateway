"""
Admin endpoints for API key lifecycle management.
Protected by the ADMIN_MASTER_KEY (sent via the same X-API-Key header),
not by regular API keys.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_api_key, invalidate_key_cache, require_admin
from app.database import get_db
from app.models.db_models import APIKey
from app.models.schemas import APIKeyCreateRequest, APIKeyCreateResponse, APIKeyInfo

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.post("/api-keys", response_model=APIKeyCreateResponse, status_code=201)
async def create_api_key(
    body: APIKeyCreateRequest, db: AsyncSession = Depends(get_db)
) -> APIKeyCreateResponse:
    plaintext, key_hash, prefix = generate_api_key()

    key = APIKey(
        name=body.name,
        key_hash=key_hash,
        key_prefix=prefix,
        rate_limit=body.rate_limit,
        rate_window_seconds=body.rate_window_seconds,
        allowed_scopes=body.allowed_scopes,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    return APIKeyCreateResponse(
        id=key.id,
        name=key.name,
        api_key=plaintext,  # shown only once
        key_prefix=key.key_prefix,
        rate_limit=key.rate_limit,
        rate_window_seconds=key.rate_window_seconds,
        allowed_scopes=key.allowed_scopes,
    )


@router.get("/api-keys", response_model=list[APIKeyInfo])
async def list_api_keys(db: AsyncSession = Depends(get_db)) -> list[APIKeyInfo]:
    result = await db.execute(select(APIKey).order_by(APIKey.created_at.desc()))
    keys = result.scalars().all()
    return [
        APIKeyInfo(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            is_active=k.is_active,
            rate_limit=k.rate_limit,
            rate_window_seconds=k.rate_window_seconds,
            allowed_scopes=k.allowed_scopes,
            created_at=k.created_at.isoformat() if k.created_at else "",
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: str, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = False
    await db.commit()
    await invalidate_key_cache(key.key_hash)
