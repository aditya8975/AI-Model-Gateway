"""
Centralized configuration for the AI Model Gateway.
All values are overridable via environment variables / .env file.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Service ---
    APP_NAME: str = "AI Model Gateway"
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://gateway:gateway@postgres:5432/gateway"

    # --- Redis ---
    REDIS_URL: str = "redis://redis:6379/0"

    # --- Auth ---
    ADMIN_MASTER_KEY: str = "change-me-admin-master-key"
    API_KEY_HEADER: str = "X-API-Key"

    # --- Rate limiting defaults (requests per window) ---
    DEFAULT_RATE_LIMIT: int = 60          # requests
    DEFAULT_RATE_WINDOW_SECONDS: int = 60  # per this many seconds
    BURST_MULTIPLIER: float = 1.5

    # --- Request queue ---
    QUEUE_STREAM_KEY: str = "gateway:jobs"
    QUEUE_CONSUMER_GROUP: str = "gateway-workers"
    JOB_RESULT_TTL_SECONDS: int = 3600
    MAX_QUEUE_DEPTH: int = 1000

    # --- Upstream providers (all optional; mock fallback used if unset) ---
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_DEFAULT_MODEL: str = "gpt-4o-mini"

    ASR_PROVIDER_API_KEY: Optional[str] = None
    ASR_DEFAULT_MODEL: str = "whisper-1"

    TTS_PROVIDER_API_KEY: Optional[str] = None
    TTS_DEFAULT_VOICE: str = "default"

    VISION_PROVIDER_API_KEY: Optional[str] = None

    # --- Misc ---
    REQUEST_TIMEOUT_SECONDS: int = 60
    MAX_UPLOAD_MB: int = 25


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
