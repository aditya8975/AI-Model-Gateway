"""
AI Model Gateway -- single-entry FastAPI application.

Wires together: routers, auth, rate limiting, request queue, logging,
metrics, and startup/shutdown lifecycle (DB table creation, consumer
group setup, connectivity checks).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.config import settings
from app.database import init_models
from app.logging_config import configure_logging, get_logger
from app.metrics import AUTH_FAILURES, RATE_LIMIT_REJECTIONS
from app.middleware.logging_middleware import LoggingMiddleware
from app.redis_client import redis_client
from app.routers import admin, asr, gateway, health, jobs, llm, ocr, tts, vision
from app.services.queue_service import ensure_consumer_group

configure_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s (env=%s)", settings.APP_NAME, settings.ENV)
    try:
        await init_models()
        logger.info("Database tables verified/created")
    except Exception:
        logger.exception("Could not initialize database tables on startup")

    try:
        await ensure_consumer_group()
    except Exception:
        logger.exception("Could not initialize Redis consumer group on startup")

    yield

    logger.info("Shutting down %s", settings.APP_NAME)
    await redis_client.aclose()


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "A single API gateway that authenticates, rate-limits, queues, "
        "and routes requests to LLM, ASR, TTS, Vision, and OCR backends."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        AUTH_FAILURES.inc()
    if exc.status_code == 429:
        RATE_LIMIT_REJECTIONS.labels(api_key_id="unknown").inc()
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
        headers=getattr(exc, "headers", None) or {},
    )


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root() -> dict:
    return {
        "service": settings.APP_NAME,
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "unified_gateway": "POST /v1/gateway",
            "llm": "/v1/llm/chat, /v1/llm/chat/stream, /v1/llm/chat/async",
            "asr": "/v1/asr/transcribe, /v1/asr/transcribe/async",
            "tts": "/v1/tts/synthesize, /v1/tts/synthesize/async",
            "vision": "/v1/vision/analyze, /v1/vision/analyze/async",
            "ocr": "/v1/ocr/extract, /v1/ocr/extract/async",
            "jobs": "/v1/jobs/{job_id}",
            "admin": "/v1/admin/api-keys",
            "health": "/health, /health/detailed",
            "metrics": "/metrics",
        },
    }


app.include_router(health.router)
app.include_router(gateway.router)
app.include_router(llm.router)
app.include_router(asr.router)
app.include_router(tts.router)
app.include_router(vision.router)
app.include_router(ocr.router)
app.include_router(jobs.router)
app.include_router(admin.router)
