"""
Vision backend. Uses an OpenAI-compatible vision model (via image_url /
base64) if VISION_PROVIDER_API_KEY is set. Otherwise falls back to a
real (non-mocked) local image analysis using Pillow: dimensions,
format, mode, and dominant color -- genuinely computed from the
uploaded bytes, no external calls required.
"""
import asyncio
import base64
import io

import httpx
from PIL import Image

from app.config import settings
from app.logging_config import get_logger
from app.metrics import UPSTREAM_ERRORS

logger = get_logger("vision_service")


def _local_analyze(image_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((64, 64))  # cheap downsample for dominant color calc
    rgb = img.convert("RGB")
    pixels = list(rgb.getdata())
    avg = tuple(sum(c[i] for c in pixels) // len(pixels) for i in range(3))

    full = Image.open(io.BytesIO(image_bytes))
    return {
        "width": full.width,
        "height": full.height,
        "format": full.format,
        "description": (
            f"[local-analysis] {full.format} image, {full.width}x{full.height}px, "
            f"mode={full.mode}, approximate dominant RGB={avg}. "
            "Configure VISION_PROVIDER_API_KEY for AI-generated captions."
        ),
    }


async def analyze(image_bytes: bytes, prompt: str | None) -> dict:
    if not settings.VISION_PROVIDER_API_KEY:
        await asyncio.sleep(0.1)
        result = _local_analyze(image_bytes)
        result["provider"] = "local-pillow"
        return result

    b64 = base64.b64encode(image_bytes).decode()
    url = f"{settings.OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.VISION_PROVIDER_API_KEY}"}
    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or "Describe this image."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 300,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            local = _local_analyze(image_bytes)
            return {
                "description": data["choices"][0]["message"]["content"],
                "width": local["width"],
                "height": local["height"],
                "format": local["format"],
                "provider": "openai-vision",
            }
    except httpx.HTTPError as e:
        UPSTREAM_ERRORS.labels(task_type="vision", provider="openai-vision").inc()
        logger.error("Vision upstream error: %s", e)
        raise
