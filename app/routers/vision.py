"""
Vision endpoints: synchronous analysis and async (queued) analysis.
"""
import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import AuthenticatedKey
from app.config import settings
from app.models.schemas import JobEnqueuedResponse, VisionResponse
from app.rate_limiter import enforce_rate_limit
from app.services import vision_service
from app.services.queue_service import enqueue_job

router = APIRouter(prefix="/v1/vision", tags=["vision"])


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_MB}MB limit.")
    return data


@router.post("/analyze", response_model=VisionResponse)
async def analyze(
    file: UploadFile = File(...),
    prompt: str | None = Form(None),
    auth_key: AuthenticatedKey = Depends(enforce_rate_limit),
) -> VisionResponse:
    if not auth_key.can_access("vision"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'vision' tasks.")

    image_bytes = await _read_upload(file)
    result = await vision_service.analyze(image_bytes, prompt)
    return VisionResponse(**result)


@router.post("/analyze/async", response_model=JobEnqueuedResponse, status_code=202)
async def analyze_async(
    file: UploadFile = File(...),
    prompt: str | None = Form(None),
    auth_key: AuthenticatedKey = Depends(enforce_rate_limit),
) -> JobEnqueuedResponse:
    if not auth_key.can_access("vision"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'vision' tasks.")

    image_bytes = await _read_upload(file)
    payload = {"image_b64": base64.b64encode(image_bytes).decode(), "prompt": prompt}
    job_id = await enqueue_job("vision", payload)
    return JobEnqueuedResponse(job_id=job_id, poll_url=f"/v1/jobs/{job_id}")
