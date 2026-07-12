"""
TTS endpoints: synchronous (returns raw audio bytes) and async (queued).
"""
import base64
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import AuthenticatedKey
from app.models.schemas import JobEnqueuedResponse, TTSRequest
from app.rate_limiter import enforce_rate_limit
from app.services import tts_service
from app.services.queue_service import enqueue_job

router = APIRouter(prefix="/v1/tts", tags=["tts"])


@router.post("/synthesize")
async def synthesize(
    body: TTSRequest, auth_key: AuthenticatedKey = Depends(enforce_rate_limit)
) -> StreamingResponse:
    if not auth_key.can_access("tts"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'tts' tasks.")

    audio_bytes, media_type, provider = await tts_service.synthesize(
        body.text, body.voice, body.format
    )
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type=media_type,
        headers={"X-TTS-Provider": provider, "Content-Disposition": "inline; filename=speech.wav"},
    )


@router.post("/synthesize/async", response_model=JobEnqueuedResponse, status_code=202)
async def synthesize_async(
    body: TTSRequest, auth_key: AuthenticatedKey = Depends(enforce_rate_limit)
) -> JobEnqueuedResponse:
    if not auth_key.can_access("tts"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'tts' tasks.")

    payload = {"text": body.text, "voice": body.voice, "format": body.format}
    job_id = await enqueue_job("tts", payload)
    return JobEnqueuedResponse(job_id=job_id, poll_url=f"/v1/jobs/{job_id}")
