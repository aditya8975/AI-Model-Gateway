"""
Poll status/result of an asynchronously-queued job.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.auth import AuthenticatedKey
from app.models.schemas import JobStatusResponse
from app.rate_limiter import enforce_rate_limit
from app.services.queue_service import get_job

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobStatusResponse)
async def job_status(
    job_id: str, auth_key: AuthenticatedKey = Depends(enforce_rate_limit)
) -> JobStatusResponse:
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return JobStatusResponse(**job)
