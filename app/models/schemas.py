"""
Pydantic schemas used across routers.
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

TaskType = Literal["llm", "asr", "tts", "vision", "ocr"]


# ---------- Unified gateway envelope ----------
class GatewayRequest(BaseModel):
    task: TaskType = Field(..., description="Which backend to route to")
    payload: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False
    async_job: bool = Field(False, description="If true, enqueue and return a job_id instead of blocking")


# ---------- LLM ----------
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 512
    stream: bool = False


class ChatResponse(BaseModel):
    model: str
    content: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)


# ---------- ASR ----------
class ASRResponse(BaseModel):
    text: str
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    provider: str


# ---------- TTS ----------
class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    format: Literal["wav", "mp3"] = "wav"


# ---------- Vision ----------
class VisionResponse(BaseModel):
    description: str
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None
    provider: str


# ---------- OCR ----------
class OCRResponse(BaseModel):
    text: str
    confidence: Optional[float] = None
    word_count: int
    provider: str


# ---------- Jobs / Queue ----------
class JobEnqueuedResponse(BaseModel):
    job_id: str
    status: Literal["queued"] = "queued"
    poll_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    task: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


# ---------- Admin / API keys ----------
class APIKeyCreateRequest(BaseModel):
    name: str
    rate_limit: int = 60
    rate_window_seconds: int = 60
    allowed_scopes: str = "*"


class APIKeyCreateResponse(BaseModel):
    id: str
    name: str
    api_key: str  # plaintext, shown ONCE
    key_prefix: str
    rate_limit: int
    rate_window_seconds: int
    allowed_scopes: str


class APIKeyInfo(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_active: bool
    rate_limit: int
    rate_window_seconds: int
    allowed_scopes: str
    created_at: str


# ---------- Health ----------
class HealthStatus(BaseModel):
    status: Literal["ok", "degraded", "down"]
    components: dict[str, str] = Field(default_factory=dict)
    version: str = "1.0.0"
