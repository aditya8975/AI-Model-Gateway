"""
Creates a demo API key on first startup so you can try the gateway
immediately without manually calling the admin endpoint first.

Usage (from repo root, inside the app container or a venv with the
same dependencies installed):
    python -m scripts.seed_demo_key

Idempotent: if a key named "demo" already exists, it does nothing.
"""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select

from app.auth import generate_api_key
from app.database import AsyncSessionLocal, init_models
from app.models.db_models import APIKey


async def main() -> None:
    await init_models()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(APIKey).where(APIKey.name == "demo"))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Demo key already exists (id={existing.id}, prefix={existing.key_prefix}...)")
            return

        plaintext, key_hash, prefix = generate_api_key()
        key = APIKey(
            name="demo",
            key_hash=key_hash,
            key_prefix=prefix,
            rate_limit=120,
            rate_window_seconds=60,
            allowed_scopes="*",
        )
        session.add(key)
        await session.commit()

        print("=" * 70)
        print("Demo API key created. Save this -- it will not be shown again:")
        print(f"\n    {plaintext}\n")
        print(f"Use it via header: X-API-Key: {plaintext}")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
