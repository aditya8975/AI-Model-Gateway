"""
LLM endpoints: synchronous, streaming (SSE), and async (queued).
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import AuthenticatedKey
from app.models.schemas import ChatRequest, ChatResponse, JobEnqueuedResponse
from app.rate_limiter import enforce_rate_limit
from app.services import llm_service
from app.services.queue_service import enqueue_job

router = APIRouter(prefix="/v1/llm", tags=["llm"])


def _check_scope(auth_key: AuthenticatedKey):
    if not auth_key.can_access("llm"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'llm' tasks.")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest, auth_key: AuthenticatedKey = Depends(enforce_rate_limit)
) -> ChatResponse:
    _check_scope(auth_key)

    if body.stream:
        raise HTTPException(
            status_code=400,
            detail="For streaming, call POST /v1/llm/chat/stream instead.",
        )

    result = await llm_service.chat_completion(
        messages=body.messages, model=body.model,
        temperature=body.temperature, max_tokens=body.max_tokens,
    )
    return ChatResponse(**result)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest, auth_key: AuthenticatedKey = Depends(enforce_rate_limit)
) -> StreamingResponse:
    _check_scope(auth_key)

    generator = llm_service.chat_completion_stream(
        messages=body.messages, model=body.model,
        temperature=body.temperature, max_tokens=body.max_tokens,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/async", response_model=JobEnqueuedResponse, status_code=202)
async def chat_async(
    body: ChatRequest, auth_key: AuthenticatedKey = Depends(enforce_rate_limit)
) -> JobEnqueuedResponse:
    """Enqueue a chat completion job and return immediately with a job_id
    to poll via GET /v1/jobs/{job_id}. Useful for long-running requests
    or to decouple client latency from LLM latency."""
    _check_scope(auth_key)

    payload = {
        "messages": [m.model_dump() for m in body.messages],
        "model": body.model,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
    }
    job_id = await enqueue_job("llm", payload)
    return JobEnqueuedResponse(job_id=job_id, poll_url=f"/v1/jobs/{job_id}")
