"""
ORM models: API keys (auth + rate-limit tier) and request logs (audit trail).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12), index=True)  # shown to user for reference
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Rate-limit tier for this key
    rate_limit: Mapped[int] = mapped_column(Integer, default=60)
    rate_window_seconds: Mapped[int] = mapped_column(Integer, default=60)

    # Which task types this key may access (comma-separated, "*" = all)
    allowed_scopes: Mapped[str] = mapped_column(String(255), default="*")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    api_key_id: Mapped[str] = mapped_column(String(36), index=True, nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)  # llm/asr/tts/vision/ocr
    route: Mapped[str] = mapped_column(String(255))
    method: Mapped[str] = mapped_column(String(10))
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    upstream_provider: Mapped[str] = mapped_column(String(64), nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
