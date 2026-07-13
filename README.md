# AI Model Gateway

A single API gateway that authenticates, rate-limits, queues, logs, and
routes requests to multiple AI backends — **LLM, ASR (speech-to-text),
TTS (text-to-speech), Vision, and OCR** — behind one consistent
interface. This is the same shape of system that powers multi-model AI
platforms like Sarvam's API layer.

Everything in this repo runs out of the box with **zero external API
keys**: LLM/ASR/TTS/Vision fall back to functional local/mock
implementations, and **OCR is fully real** (genuine Tesseract OCR, no
mocking). Drop in `OPENAI_API_KEY` (or any OpenAI-compatible provider
key) via `.env` and the LLM/ASR/TTS/Vision backends transparently
switch to the real thing — no code changes required.

---
![Project Home](doc2.png)
---

---
![Project Home](doc1.png)
---

## Architecture

```
                     ┌────────────┐
   client ─────────▶ │   Nginx    │  reverse proxy, edge rate limit,
                     │ (port 80)  │  SSE-aware streaming passthrough
                     └─────┬──────┘
                           │
                     ┌─────▼──────┐        ┌───────────┐
                     │  FastAPI    │◀──────▶│PostgreSQL │  API keys,
                     │  Gateway    │        │           │  audit logs
                     │ (app:8000)  │        └───────────┘
                     └──┬───────┬─┘
                        │       │             ┌───────────┐
             ┌──────────┘       └────────────▶│   Redis   │  rate limits,
             │                                │           │  job queue,
             ▼                                └─────┬─────┘  API-key cache
      ┌──────────────┐                              │
      │ LLM / ASR /  │                        ┌──────▼──────┐
      │ TTS / Vision │                        │   Worker    │  consumes
      │ / OCR        │                        │  (async     │  queued jobs
      │ services     │                        │   jobs)     │
      └──────────────┘                        └─────────────┘

      Prometheus scrapes /metrics  →  Grafana dashboards
```

**Two ways to call the gateway:**
1. **Unified endpoint** — `POST /v1/gateway` with `{"task": "llm|asr|tts|vision|ocr", "payload": {...}}`. One endpoint, one contract, route by field.
2. **Dedicated REST endpoints** — `/v1/llm/chat`, `/v1/asr/transcribe`, `/v1/tts/synthesize`, `/v1/vision/analyze`, `/v1/ocr/extract` — better ergonomics for multipart file uploads and native SSE streaming.

Every endpoint also has an `/async` variant that enqueues the job to
Redis and returns a `job_id` immediately; poll `GET /v1/jobs/{job_id}`
for the result.

## Features

| Requirement | Implementation |
|---|---|
| Single API endpoint | `POST /v1/gateway` routes by `task` field to LLM/ASR/TTS/Vision/OCR |
| API Key Authentication | SHA-256-hashed keys in Postgres, Redis-cached lookups, `X-API-Key` header |
| Rate Limiting | Per-key sliding-window limiter on Redis sorted sets (accurate, no boundary bursting) |
| Streaming Responses | Server-Sent Events for `/v1/llm/chat/stream` and unified gateway with `"stream": true` |
| Request Queue | Redis Streams + consumer group; standalone, horizontally-scalable worker process |
| Health Checks | `/health` (liveness) and `/health/detailed` (Postgres + Redis readiness) |
| Metrics | Prometheus `/metrics`: request rate, latency histograms, in-flight gauge, queue depth, rate-limit rejections, auth failures |
| Logging | Structured JSON access logs (stdout) + best-effort audit trail persisted to Postgres |

## Quick start

```bash
cp .env.example .env
# edit .env if you want to set a real ADMIN_MASTER_KEY or provider keys

docker compose up -d --build

# Wait ~15s for healthchecks, then create your first API key:
curl -X POST http://localhost:8080/v1/admin/api-keys \
  -H "X-API-Key: <your ADMIN_MASTER_KEY from .env>" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-first-key", "rate_limit": 100, "rate_window_seconds": 60}'
# => {"api_key": "gw_xxxxxxxx...", ...}   <- save this, shown only once
```

Everything is now reachable through Nginx on `http://localhost:8080`.
Direct service ports for debugging: Prometheus `:9090`, Grafana `:3000`
(default admin/admin), Postgres/Redis are internal-only.

## API examples

**Unified gateway endpoint:**
```bash
curl -X POST http://localhost:8080/v1/gateway \
  -H "X-API-Key: gw_xxx" -H "Content-Type: application/json" \
  -d '{"task":"llm","payload":{"messages":[{"role":"user","content":"Hello!"}]}}'
```

**LLM chat, streaming:**
```bash
curl -N -X POST http://localhost:8080/v1/llm/chat/stream \
  -H "X-API-Key: gw_xxx" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Tell me a short story"}]}'
```

**OCR (real Tesseract, works with zero config):**
```bash
curl -X POST http://localhost:8080/v1/ocr/extract \
  -H "X-API-Key: gw_xxx" -F "file=@invoice.png"
```

**TTS → real playable WAV file:**
```bash
curl -X POST http://localhost:8080/v1/tts/synthesize \
  -H "X-API-Key: gw_xxx" -H "Content-Type: application/json" \
  -d '{"text":"Hello from the gateway"}' -o speech.wav
```

**Async job (any task): enqueue, then poll**
```bash
JOB=$(curl -s -X POST http://localhost:8080/v1/ocr/extract/async \
  -H "X-API-Key: gw_xxx" -F "file=@invoice.png" | jq -r .job_id)

curl http://localhost:8080/v1/jobs/$JOB -H "X-API-Key: gw_xxx"
```

## Local development (without Docker)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Point at any Postgres/Redis you have running, e.g. locally:
export DATABASE_URL="postgresql+asyncpg://gateway:gateway@localhost:5432/gateway"
export REDIS_URL="redis://localhost:6379/0"
export ADMIN_MASTER_KEY="dev-admin-key"

uvicorn app.main:app --reload

# In a second terminal, run the async job worker:
python -m app.workers.queue_worker
```

Interactive API docs: `http://localhost:8000/docs`

## Running tests

Tests are integration tests that run against a live instance:
```bash
uvicorn app.main:app &          # or: docker compose up -d
BASE_URL=http://localhost:8000 ADMIN_MASTER_KEY=dev-admin-key pytest tests/ -v
```

## Scaling

```bash
docker compose up -d --scale gateway=3 --scale worker=5
```
Nginx re-resolves the `gateway` service name at runtime (Docker's
embedded DNS) so traffic spreads across all API replicas. Workers pull
from a shared Redis Streams consumer group, so adding replicas
increases queue throughput linearly with no coordination needed.

## Configuration reference

See `.env.example` for the full list. Key ones:

| Variable | Purpose |
|---|---|
| `ADMIN_MASTER_KEY` | Required header value for `/v1/admin/*` endpoints |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | Enables real LLM + Vision responses (any OpenAI-compatible endpoint) |
| `ASR_PROVIDER_API_KEY` | Enables real Whisper-compatible transcription |
| `TTS_PROVIDER_API_KEY` | Enables real speech synthesis |
| `DEFAULT_RATE_LIMIT` / `DEFAULT_RATE_WINDOW_SECONDS` | Fallback rate-limit tier for new keys |

## Project layout

```
app/
  main.py               FastAPI app, middleware, router wiring, lifespan
  config.py              Settings (env-var driven)
  auth.py                 API-key hashing, verification, Redis cache
  rate_limiter.py         Sliding-window limiter (Redis sorted sets)
  metrics.py               Prometheus metric definitions
  logging_config.py         Structured JSON logging + request-id context
  database.py               Async SQLAlchemy engine/session
  models/
    db_models.py             APIKey, RequestLog ORM tables
    schemas.py                 Pydantic request/response schemas
  routers/
    gateway.py                  POST /v1/gateway (unified endpoint)
    llm.py / asr.py / tts.py /   dedicated REST endpoints per modality
    vision.py / ocr.py
    jobs.py                       async job status polling
    admin.py                       API key CRUD
    health.py                       liveness/readiness
  services/
    llm_service.py, asr_service.py, tts_service.py,   provider adapters
    vision_service.py, ocr_service.py                  (real or mock)
    queue_service.py                                     Redis Streams
  middleware/
    logging_middleware.py    request-id, timing, structured logs, metrics
  workers/
    queue_worker.py            standalone async job consumer process
scripts/
  seed_demo_key.py              creates a demo API key on first run
nginx/nginx.conf                reverse proxy config
prometheus/prometheus.yml       scrape config
grafana/provisioning/           datasource + prebuilt dashboard
tests/test_gateway.py           integration test suite
```
