"""
Global middleware: assigns a request ID, times every request, emits a
structured access log line, and records Prometheus metrics.
"""
import asyncio
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.logging_config import api_key_id_ctx, get_logger, request_id_ctx
from app.metrics import INFLIGHT_REQUESTS, REQUEST_COUNT, REQUEST_LATENCY

logger = get_logger("access")

_NOISY_PATHS = {"/metrics", "/health"}


async def _persist_audit_log(
    request_id: str, api_key_id: str, task_type: str,
    route: str, method: str, status_code: int, latency_ms: float,
) -> None:
    """Best-effort write to the request_logs table. Never raises -- a
    Postgres hiccup must not affect the actual API response."""
    try:
        from app.database import AsyncSessionLocal
        from app.models.db_models import RequestLog

        async with AsyncSessionLocal() as session:
            session.add(
                RequestLog(
                    request_id=request_id,
                    api_key_id=None if api_key_id == "-" else api_key_id,
                    task_type=task_type,
                    route=route,
                    method=method,
                    status_code=status_code,
                    latency_ms=latency_ms,
                )
            )
            await session.commit()
    except Exception:
        logger.debug("Skipped audit log persistence (DB unavailable)", exc_info=True)


def _infer_task_type(path: str) -> str:
    for task in ("llm", "asr", "tts", "vision", "ocr"):
        if f"/{task}" in path:
            return task
    if "/gateway" in path:
        return "gateway"
    return "system"


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_ctx.set(request_id)
        task_type = _infer_task_type(request.url.path)

        start = time.perf_counter()
        INFLIGHT_REQUESTS.labels(task_type=task_type).inc()

        try:
            response = await call_next(request)
        except Exception:
            INFLIGHT_REQUESTS.labels(task_type=task_type).dec()
            duration = time.perf_counter() - start
            REQUEST_COUNT.labels(
                task_type=task_type, route=request.url.path,
                method=request.method, status_code="500",
            ).inc()
            logger.exception(
                "Unhandled exception",
                extra={"path": request.url.path, "duration_ms": duration * 1000},
            )
            raise

        duration = time.perf_counter() - start
        INFLIGHT_REQUESTS.labels(task_type=task_type).dec()

        REQUEST_COUNT.labels(
            task_type=task_type,
            route=request.url.path,
            method=request.method,
            status_code=str(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(task_type=task_type, route=request.url.path).observe(duration)

        response.headers["X-Request-ID"] = request_id

        if request.url.path not in _NOISY_PATHS:
            logger.info(
                "request completed",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                    "task_type": task_type,
                },
            )
            asyncio.create_task(
                _persist_audit_log(
                    request_id=request_id,
                    api_key_id=api_key_id_ctx.get(),
                    task_type=task_type,
                    route=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    latency_ms=round(duration * 1000, 2),
                )
            )

        return response
