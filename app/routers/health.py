"""
Health check endpoints, used by Docker healthchecks, Nginx upstream
checks, and Kubernetes-style liveness/readiness probes.
"""
import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import HealthStatus
from app.redis_client import ping_redis

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
async def liveness() -> HealthStatus:
    """Cheap liveness probe -- does not touch dependencies."""
    return HealthStatus(status="ok", components={"api": "ok"})


@router.get("/health/detailed", response_model=HealthStatus)
async def readiness(db: AsyncSession = Depends(get_db)) -> HealthStatus:
    """Readiness probe -- verifies Postgres and Redis are reachable."""
    components: dict[str, str] = {}

    async def check_db():
        try:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=3)
            components["postgres"] = "ok"
        except Exception as e:
            components["postgres"] = f"down: {e}"

    async def check_redis():
        ok = await ping_redis()
        components["redis"] = "ok" if ok else "down"

    await asyncio.gather(check_db(), check_redis())

    overall = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return HealthStatus(status=overall, components=components)
