"""
LLM backend. If OPENAI_API_KEY (or any OpenAI-compatible endpoint) is
configured, requests are proxied there with real streaming support.
Otherwise a deterministic mock responder is used so the gateway is
fully demoable without any credentials.
"""
import asyncio
import json
import time
from collections.abc import AsyncGenerator

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.metrics import UPSTREAM_ERRORS
from app.models.schemas import ChatMessage

logger = get_logger("llm_service")


def _mock_reply(messages: list[ChatMessage]) -> str:
    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    return (
        "[mock-llm] This is a simulated completion because no upstream "
        f"LLM provider is configured. You said: {last_user!r}"
    )


async def chat_completion(
    messages: list[ChatMessage], model: str | None, temperature: float, max_tokens: int
) -> dict:
    model = model or settings.LLM_DEFAULT_MODEL

    if not settings.OPENAI_API_KEY:
        await asyncio.sleep(0.15)  # simulate latency
        return {
            "model": model,
            "content": _mock_reply(messages),
            "provider": "mock",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    url = f"{settings.OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    body = {
        "model": model,
        "messages": [m.model_dump() for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            return {
                "model": data.get("model", model),
                "content": data["choices"][0]["message"]["content"],
                "provider": "openai",
                "usage": data.get("usage", {}),
            }
    except httpx.HTTPError as e:
        UPSTREAM_ERRORS.labels(task_type="llm", provider="openai").inc()
        logger.error("LLM upstream error: %s", e)
        raise


async def chat_completion_stream(
    messages: list[ChatMessage], model: str | None, temperature: float, max_tokens: int
) -> AsyncGenerator[str, None]:
    """Yields Server-Sent-Event formatted chunks."""
    model = model or settings.LLM_DEFAULT_MODEL

    if not settings.OPENAI_API_KEY:
        text = _mock_reply(messages)
        for word in text.split(" "):
            await asyncio.sleep(0.04)
            chunk = {"choices": [{"delta": {"content": word + " "}}]}
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"
        return

    url = f"{settings.OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    body = {
        "model": model,
        "messages": [m.model_dump() for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        yield f"{line}\n\n"
    except httpx.HTTPError as e:
        UPSTREAM_ERRORS.labels(task_type="llm", provider="openai").inc()
        logger.error("LLM streaming upstream error: %s", e)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
