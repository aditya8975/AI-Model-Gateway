"""
ASR (Automatic Speech Recognition) backend.
Uses OpenAI Whisper API if ASR_PROVIDER_API_KEY is set, else a mock
transcriber that reports basic facts about the uploaded audio so the
endpoint is still meaningfully testable offline.
"""
import asyncio
import io
import wave

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.metrics import UPSTREAM_ERRORS

logger = get_logger("asr_service")


def _probe_wav_duration(audio_bytes: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return round(frames / float(rate), 2) if rate else None
    except Exception:
        return None


async def transcribe(audio_bytes: bytes, filename: str, content_type: str) -> dict:
    if not settings.ASR_PROVIDER_API_KEY:
        await asyncio.sleep(0.2)
        duration = _probe_wav_duration(audio_bytes) if filename.lower().endswith(".wav") else None
        return {
            "text": f"[mock-asr] Simulated transcription for uploaded file '{filename}' "
                    f"({len(audio_bytes)} bytes). Configure ASR_PROVIDER_API_KEY for real ASR.",
            "language": "en",
            "duration_seconds": duration,
            "provider": "mock",
        }

    url = f"{settings.OPENAI_BASE_URL}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.ASR_PROVIDER_API_KEY}"}
    files = {"file": (filename, audio_bytes, content_type or "audio/wav")}
    data = {"model": settings.ASR_DEFAULT_MODEL}

    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            result = resp.json()
            return {
                "text": result.get("text", ""),
                "language": result.get("language"),
                "duration_seconds": result.get("duration"),
                "provider": "openai-whisper",
            }
    except httpx.HTTPError as e:
        UPSTREAM_ERRORS.labels(task_type="asr", provider="openai-whisper").inc()
        logger.error("ASR upstream error: %s", e)
        raise
