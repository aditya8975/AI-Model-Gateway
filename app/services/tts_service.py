"""
TTS (Text-to-Speech) backend.
Uses an OpenAI-compatible TTS endpoint if TTS_PROVIDER_API_KEY is set.
Otherwise falls back to a genuinely-functional offline synthesizer:
it generates a real WAV file (sine-wave tones mapped from the input
text) using only the Python standard library, so the endpoint returns
real, playable audio bytes with zero external dependencies.
"""
import asyncio
import io
import math
import struct
import wave

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.metrics import UPSTREAM_ERRORS

logger = get_logger("tts_service")

_SAMPLE_RATE = 16000
_BASE_FREQ = 220.0  # Hz


def _synthesize_mock_wav(text: str) -> bytes:
    """Maps each character to a short sine-wave tone, concatenated into
    one WAV file. Not real speech, but a real, valid, playable audio
    artifact -- useful for demoing the full request/response pipeline
    (auth, rate-limit, queue, streaming headers, metrics) without needing
    a paid TTS provider."""
    duration_per_char = 0.06
    n_samples_per_char = int(_SAMPLE_RATE * duration_per_char)
    frames = bytearray()

    for ch in text[:400] or " ":
        freq = _BASE_FREQ + (ord(ch) % 40) * 15
        for i in range(n_samples_per_char):
            t = i / _SAMPLE_RATE
            envelope = math.sin(math.pi * i / n_samples_per_char)  # avoid clicks
            sample = int(8000 * envelope * math.sin(2 * math.pi * freq * t))
            frames += struct.pack("<h", sample)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(bytes(frames))
    return buf.getvalue()


async def synthesize(text: str, voice: str | None, fmt: str) -> tuple[bytes, str, str]:
    """Returns (audio_bytes, media_type, provider)."""
    voice = voice or settings.TTS_DEFAULT_VOICE

    if not settings.TTS_PROVIDER_API_KEY:
        await asyncio.sleep(0.1)
        return _synthesize_mock_wav(text), "audio/wav", "mock"

    url = f"{settings.OPENAI_BASE_URL}/audio/speech"
    headers = {"Authorization": f"Bearer {settings.TTS_PROVIDER_API_KEY}"}
    body = {"model": "tts-1", "voice": voice, "input": text, "response_format": fmt}

    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            media_type = "audio/mpeg" if fmt == "mp3" else "audio/wav"
            return resp.content, media_type, "openai"
    except httpx.HTTPError as e:
        UPSTREAM_ERRORS.labels(task_type="tts", provider="openai").inc()
        logger.error("TTS upstream error: %s", e)
        raise
