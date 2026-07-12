"""
Async SQLAlchemy engine/session management.
Engine creation is lazy (no connection made at import time), so the
app can boot even if Postgres is briefly unavailable; it will retry
on first actual query / on startup healthcheck.
"""
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create tables if they don't exist. For production, prefer Alembic
    migrations; this is provided so the demo works out-of-the-box."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
