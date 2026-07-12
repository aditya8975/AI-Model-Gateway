"""
Standalone worker process for asynchronous jobs.

Run as its own container/process (see docker-compose `worker` service):
    python -m app.workers.queue_worker

Consumes from the Redis Stream via a consumer group so multiple worker
replicas can be scaled horizontally, and unacked jobs from a crashed
worker can be reclaimed.
"""
import asyncio
import base64
import json
import signal
import socket

from app.config import settings
from app.logging_config import configure_logging, get_logger
from app.metrics import JOBS_PROCESSED, QUEUE_DEPTH
from app.models.schemas import ChatMessage
from app.redis_client import redis_client
from app.services import asr_service, llm_service, ocr_service, tts_service, vision_service
from app.services.queue_service import ensure_consumer_group, get_job, update_job

logger = get_logger("queue_worker")

CONSUMER_NAME = f"worker-{socket.gethostname()}-{__import__('os').getpid()}"
_shutdown = asyncio.Event()


async def _process_llm(payload: dict) -> dict:
    messages = [ChatMessage(**m) for m in payload["messages"]]
    return await llm_service.chat_completion(
        messages=messages,
        model=payload.get("model"),
        temperature=payload.get("temperature", 0.7),
        max_tokens=payload.get("max_tokens", 512),
    )


async def _process_asr(payload: dict) -> dict:
    audio_bytes = base64.b64decode(payload["audio_b64"])
    return await asr_service.transcribe(
        audio_bytes, payload.get("filename", "audio.wav"), payload.get("content_type", "audio/wav")
    )


async def _process_tts(payload: dict) -> dict:
    audio_bytes, media_type, provider = await tts_service.synthesize(
        payload["text"], payload.get("voice"), payload.get("format", "wav")
    )
    return {
        "audio_b64": base64.b64encode(audio_bytes).decode(),
        "media_type": media_type,
        "provider": provider,
    }


async def _process_vision(payload: dict) -> dict:
    image_bytes = base64.b64decode(payload["image_b64"])
    return await vision_service.analyze(image_bytes, payload.get("prompt"))


async def _process_ocr(payload: dict) -> dict:
    image_bytes = base64.b64decode(payload["image_b64"])
    return await ocr_service.extract_text(image_bytes)


_HANDLERS = {
    "llm": _process_llm,
    "asr": _process_asr,
    "tts": _process_tts,
    "vision": _process_vision,
    "ocr": _process_ocr,
}


async def _handle_message(msg_id: str, fields: dict) -> None:
    job_id = fields.get("job_id")
    task = fields.get("task")

    job = await get_job(job_id)
    if job is None:
        logger.warning("Job %s not found (expired?), skipping", job_id)
        await redis_client.xack(settings.QUEUE_STREAM_KEY, settings.QUEUE_CONSUMER_GROUP, msg_id)
        return

    await update_job(job_id, "processing")
    payload = json.loads((await redis_client.hget(f"job:{job_id}", "payload")) or "{}")

    handler = _HANDLERS.get(task)
    try:
        if handler is None:
            raise ValueError(f"Unknown task type: {task}")
        result = await handler(payload)
        await update_job(job_id, "completed", result=result)
        JOBS_PROCESSED.labels(task_type=task, status="completed").inc()
        logger.info("Job completed", extra={"job_id": job_id, "task_type": task})
    except Exception as e:
        await update_job(job_id, "failed", error=str(e))
        JOBS_PROCESSED.labels(task_type=task, status="failed").inc()
        logger.exception("Job failed", extra={"job_id": job_id, "task_type": task})
    finally:
        await redis_client.xack(settings.QUEUE_STREAM_KEY, settings.QUEUE_CONSUMER_GROUP, msg_id)


async def run_worker() -> None:
    configure_logging()
    await ensure_consumer_group()
    logger.info("Worker %s started, listening on stream '%s'", CONSUMER_NAME, settings.QUEUE_STREAM_KEY)

    while not _shutdown.is_set():
        try:
            resp = await redis_client.xreadgroup(
                groupname=settings.QUEUE_CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={settings.QUEUE_STREAM_KEY: ">"},
                count=5,
                block=5000,
            )
            depth = await redis_client.xlen(settings.QUEUE_STREAM_KEY)
            QUEUE_DEPTH.set(depth)

            if not resp:
                continue

            for _stream_name, messages in resp:
                for msg_id, fields in messages:
                    await _handle_message(msg_id, fields)

        except Exception:
            logger.exception("Worker loop error; backing off 2s")
            await asyncio.sleep(2)


def _handle_signal(*_args):
    _shutdown.set()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass
    loop.run_until_complete(run_worker())
