"""
Request queue built on Redis Streams.

Flow:
  1. API enqueues a job: writes job metadata to a Redis hash `job:{id}`
     and appends an entry to the stream `settings.QUEUE_STREAM_KEY`.
  2. One or more worker processes (see app/workers/queue_worker.py)
     consume the stream via a consumer group, process the job by
     calling the relevant service, then update the job hash with the
     result and ACK the stream entry.
  3. Clients poll GET /v1/jobs/{job_id} to retrieve status/result.

Using a consumer group (rather than a plain list) gives us: multiple
workers can share the load, unacked messages can be re-claimed if a
worker crashes mid-job, and the stream retains a replayable history.
"""
import json
import time
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.logging_config import get_logger
from app.metrics import QUEUE_DEPTH
from app.redis_client import redis_client

logger = get_logger("queue_service")


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


async def enqueue_job(task_type: str, payload: dict) -> str:
    depth = await redis_client.xlen(settings.QUEUE_STREAM_KEY)
    QUEUE_DEPTH.set(depth)
    if depth >= settings.MAX_QUEUE_DEPTH:
        raise RuntimeError(f"Queue is full ({depth} pending jobs). Try again shortly.")

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    job_record = {
        "job_id": job_id,
        "task": task_type,
        "status": "queued",
        "payload": json.dumps(payload),
        "result": "",
        "error": "",
        "created_at": now,
        "completed_at": "",
    }
    await redis_client.hset(_job_key(job_id), mapping=job_record)
    await redis_client.expire(_job_key(job_id), settings.JOB_RESULT_TTL_SECONDS)

    await redis_client.xadd(
        settings.QUEUE_STREAM_KEY,
        {"job_id": job_id, "task": task_type, "enqueued_at": str(time.time())},
    )
    logger.info("Job enqueued", extra={"job_id": job_id, "task_type": task_type})
    return job_id


async def get_job(job_id: str) -> dict | None:
    data = await redis_client.hgetall(_job_key(job_id))
    if not data:
        return None

    result = data.get("result")
    parsed_result = None
    if result:
        try:
            parsed_result = json.loads(result)
        except json.JSONDecodeError:
            parsed_result = result

    return {
        "job_id": data.get("job_id"),
        "status": data.get("status"),
        "task": data.get("task"),
        "result": parsed_result,
        "error": data.get("error") or None,
        "created_at": data.get("created_at") or None,
        "completed_at": data.get("completed_at") or None,
    }


async def update_job(
    job_id: str, status: str, result: dict | None = None, error: str | None = None
) -> None:
    updates = {"status": status}
    if result is not None:
        updates["result"] = json.dumps(result)
    if error is not None:
        updates["error"] = error
    if status in ("completed", "failed"):
        updates["completed_at"] = datetime.now(timezone.utc).isoformat()
    await redis_client.hset(_job_key(job_id), mapping=updates)


async def ensure_consumer_group() -> None:
    try:
        await redis_client.xgroup_create(
            settings.QUEUE_STREAM_KEY, settings.QUEUE_CONSUMER_GROUP, id="0", mkstream=True
        )
        logger.info("Created consumer group %s", settings.QUEUE_CONSUMER_GROUP)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            raise
