"""
Integration tests for the AI Model Gateway.

These run against a LIVE instance (the gateway must already be running --
e.g. `docker compose up -d` or `uvicorn app.main:app`). This mirrors how
you'd actually validate a deployed gateway, and avoids re-implementing
FastAPI's lifespan/DB-connection machinery inside the test suite.

Run with:
    BASE_URL=http://localhost:8000 ADMIN_MASTER_KEY=change-me-admin-master-key \
        pytest tests/ -v
"""
import io
import os
import wave

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
ADMIN_KEY = os.environ.get("ADMIN_MASTER_KEY", "change-me-admin-master-key")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.fixture(scope="module")
def api_key(client: httpx.Client) -> str:
    resp = client.post(
        "/v1/admin/api-keys",
        headers={"X-API-Key": ADMIN_KEY},
        json={"name": "pytest-key", "rate_limit": 1000, "rate_window_seconds": 60},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


def test_liveness(client: httpx.Client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readiness(client: httpx.Client):
    resp = client.get("/health/detailed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["components"]["postgres"] == "ok"
    assert body["components"]["redis"] == "ok"


def test_missing_api_key_rejected(client: httpx.Client):
    resp = client.post("/v1/llm/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 401


def test_invalid_admin_key_rejected(client: httpx.Client):
    resp = client.post(
        "/v1/admin/api-keys", headers={"X-API-Key": "not-the-admin-key"}, json={"name": "x"}
    )
    assert resp.status_code == 403


def test_llm_chat(client: httpx.Client, api_key: str):
    resp = client.post(
        "/v1/llm/chat",
        headers={"X-API-Key": api_key},
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "content" in body
    assert body["provider"] in ("mock", "openai")


def test_unified_gateway_endpoint(client: httpx.Client, api_key: str):
    resp = client.post(
        "/v1/gateway",
        headers={"X-API-Key": api_key},
        json={"task": "llm", "payload": {"messages": [{"role": "user", "content": "via gateway"}]}},
    )
    assert resp.status_code == 200
    assert "content" in resp.json()


def test_tts_returns_valid_wav(client: httpx.Client, api_key: str):
    resp = client.post(
        "/v1/tts/synthesize", headers={"X-API-Key": api_key}, json={"text": "hello world"}
    )
    assert resp.status_code == 200
    with wave.open(io.BytesIO(resp.content)) as w:
        assert w.getnframes() > 0


def test_ocr_extracts_text_from_generated_image(client: httpx.Client, api_key: str):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (300, 80), "white")
    ImageDraw.Draw(img).text((10, 25), "PYTEST OCR", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    resp = client.post(
        "/v1/ocr/extract",
        headers={"X-API-Key": api_key},
        files={"file": ("test.png", buf, "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "OCR" in body["text"].upper()


def test_async_job_flow(client: httpx.Client, api_key: str):
    resp = client.post(
        "/v1/llm/chat/async",
        headers={"X-API-Key": api_key},
        json={"messages": [{"role": "user", "content": "async please"}]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    resp = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert resp.json()["status"] in ("queued", "processing", "completed")


def test_rate_limiting_enforced(client: httpx.Client):
    resp = client.post(
        "/v1/admin/api-keys",
        headers={"X-API-Key": ADMIN_KEY},
        json={"name": "pytest-rate-limit-key", "rate_limit": 3, "rate_window_seconds": 30},
    )
    tight_key = resp.json()["api_key"]

    statuses = []
    for _ in range(5):
        r = client.post(
            "/v1/llm/chat",
            headers={"X-API-Key": tight_key},
            json={"messages": [{"role": "user", "content": "rl"}]},
        )
        statuses.append(r.status_code)

    assert statuses.count(200) == 3
    assert statuses.count(429) == 2


def test_metrics_endpoint_exposes_prometheus_format(client: httpx.Client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "gateway_requests_total" in resp.text
