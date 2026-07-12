"""
OCR endpoints: synchronous extraction and async (queued) extraction.
"""
import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.auth import AuthenticatedKey
from app.config import settings
from app.models.schemas import JobEnqueuedResponse, OCRResponse
from app.rate_limiter import enforce_rate_limit
from app.services import ocr_service
from app.services.queue_service import enqueue_job

router = APIRouter(prefix="/v1/ocr", tags=["ocr"])


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_MB}MB limit.")
    return data


@router.post("/extract", response_model=OCRResponse)
async def extract(
    file: UploadFile = File(...),
    auth_key: AuthenticatedKey = Depends(enforce_rate_limit),
) -> OCRResponse:
    if not auth_key.can_access("ocr"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'ocr' tasks.")

    image_bytes = await _read_upload(file)
    result = await ocr_service.extract_text(image_bytes)
    return OCRResponse(**result)


@router.post("/extract/async", response_model=JobEnqueuedResponse, status_code=202)
async def extract_async(
    file: UploadFile = File(...),
    auth_key: AuthenticatedKey = Depends(enforce_rate_limit),
) -> JobEnqueuedResponse:
    if not auth_key.can_access("ocr"):
        raise HTTPException(status_code=403, detail="This API key is not scoped for 'ocr' tasks.")

    image_bytes = await _read_upload(file)
    payload = {"image_b64": base64.b64encode(image_bytes).decode()}
    job_id = await enqueue_job("ocr", payload)
    return JobEnqueuedResponse(job_id=job_id, poll_url=f"/v1/jobs/{job_id}")
