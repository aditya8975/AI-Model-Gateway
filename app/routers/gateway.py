"""
The single unified gateway endpoint: POST /v1/gateway

Accepts a task type + JSON payload and routes internally to the
correct backend (LLM / ASR / TTS / Vision / OCR). Binary inputs (audio/
image) are passed base64-encoded inside the payload. This is the
"one endpoint to rule them all" entry point; dedicated REST endpoints
under /v1/llm, /v1/asr, /v1/tts, /v1/vision, /v1/ocr are also available
for clients that prefer multipart uploads or task-specific ergonomics
(e.g. native SSE streaming for chat).
"""
import base64

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import AuthenticatedKey
from app.models.schemas import ChatMessage, GatewayRequest, JobEnqueuedResponse
from app.rate_limiter import enforce_rate_limit
from app.services import asr_service, llm_service, ocr_service, tts_service, vision_service
from app.services.queue_service import enqueue_job

router = APIRouter(prefix="/v1", tags=["gateway"])


@router.post("/gateway")
async def gateway(
    body: GatewayRequest, auth_key: AuthenticatedKey = Depends(enforce_rate_limit)
):
    if not auth_key.can_access(body.task):
        raise HTTPException(
            status_code=403, detail=f"This API key is not scoped for '{body.task}' tasks."
        )

    if body.async_job:
        job_id = await enqueue_job(body.task, body.payload)
        return JobEnqueuedResponse(job_id=job_id, poll_url=f"/v1/jobs/{job_id}")

    if body.task == "llm":
        messages = [ChatMessage(**m) for m in body.payload.get("messages", [])]
        if not messages:
            raise HTTPException(status_code=422, detail="payload.messages is required for task=llm")

        if body.stream:
            generator = llm_service.chat_completion_stream(
                messages=messages,
                model=body.payload.get("model"),
                temperature=body.payload.get("temperature", 0.7),
                max_tokens=body.payload.get("max_tokens", 512),
            )
            return StreamingResponse(generator, media_type="text/event-stream")

        return await llm_service.chat_completion(
            messages=messages,
            model=body.payload.get("model"),
            temperature=body.payload.get("temperature", 0.7),
            max_tokens=body.payload.get("max_tokens", 512),
        )

    if body.task == "asr":
        if "audio_b64" not in body.payload:
            raise HTTPException(status_code=422, detail="payload.audio_b64 is required for task=asr")
        audio_bytes = base64.b64decode(body.payload["audio_b64"])
        return await asr_service.transcribe(
            audio_bytes,
            body.payload.get("filename", "audio.wav"),
            body.payload.get("content_type", "audio/wav"),
        )

    if body.task == "tts":
        if "text" not in body.payload:
            raise HTTPException(status_code=422, detail="payload.text is required for task=tts")
        audio_bytes, media_type, provider = await tts_service.synthesize(
            body.payload["text"], body.payload.get("voice"), body.payload.get("format", "wav")
        )
        return {
            "audio_b64": base64.b64encode(audio_bytes).decode(),
            "media_type": media_type,
            "provider": provider,
        }

    if body.task == "vision":
        if "image_b64" not in body.payload:
            raise HTTPException(status_code=422, detail="payload.image_b64 is required for task=vision")
        image_bytes = base64.b64decode(body.payload["image_b64"])
        return await vision_service.analyze(image_bytes, body.payload.get("prompt"))

    if body.task == "ocr":
        if "image_b64" not in body.payload:
            raise HTTPException(status_code=422, detail="payload.image_b64 is required for task=ocr")
        image_bytes = base64.b64decode(body.payload["image_b64"])
        return await ocr_service.extract_text(image_bytes)

    raise HTTPException(status_code=400, detail=f"Unsupported task: {body.task}")
