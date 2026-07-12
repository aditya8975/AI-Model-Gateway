"""
ASR endpoints: synchronous transcription and async (queued) transcription.
"""
import base64

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from app.auth import AuthenticatedKey
from app.config import settings
from app.models.schemas import ASRResponse, JobEnqueuedResponse
from app.rate_limiter import enforce_rate_limit
from app.services import asr_service
from app.services.queue_service import enqueue_job

router = APIRouter(prefix="/v1/asr", tags=["asr"])


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_MB}MB limit.")
    return data


@router.post("/transcribe", response_model=ASRResponse)
async def transcribe(
    file: UploadFile = File(...),
    auth_key: AuthenticatedKey = Depends(enforce_rate_limit),
) -> ASRResponse:
    if not auth_key.can_access("asr"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'asr' tasks.")

    audio_bytes = await _read_upload(file)
    result = await asr_service.transcribe(audio_bytes, file.filename or "audio", file.content_type or "")
    return ASRResponse(**result)


@router.post("/transcribe/async", response_model=JobEnqueuedResponse, status_code=202)
async def transcribe_async(
    file: UploadFile = File(...),
    auth_key: AuthenticatedKey = Depends(enforce_rate_limit),
) -> JobEnqueuedResponse:
    if not auth_key.can_access("asr"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'asr' tasks.")

    audio_bytes = await _read_upload(file)
    payload = {
        "audio_b64": base64.b64encode(audio_bytes).decode(),
        "filename": file.filename or "audio.wav",
        "content_type": file.content_type or "audio/wav",
    }
    job_id = await enqueue_job("asr", payload)
    return JobEnqueuedResponse(job_id=job_id, poll_url=f"/v1/jobs/{job_id}")
