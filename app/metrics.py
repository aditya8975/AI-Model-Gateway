"""
Prometheus metric definitions, scraped at GET /metrics.
"""
from prometheus_client import Counter, Gauge, Histogram

REQUEST_COUNT = Counter(
    "gateway_requests_total",
    "Total number of requests processed by the gateway",
    ["task_type", "route", "method", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "Request latency in seconds",
    ["task_type", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

INFLIGHT_REQUESTS = Gauge(
    "gateway_inflight_requests",
    "Number of requests currently being processed",
    ["task_type"],
)

RATE_LIMIT_REJECTIONS = Counter(
    "gateway_rate_limit_rejections_total",
    "Total number of requests rejected due to rate limiting",
    ["api_key_id"],
)

AUTH_FAILURES = Counter(
    "gateway_auth_failures_total",
    "Total number of authentication failures",
)

QUEUE_DEPTH = Gauge(
    "gateway_queue_depth",
    "Current number of pending jobs in the request queue",
)

JOBS_PROCESSED = Counter(
    "gateway_jobs_processed_total",
    "Total number of async jobs processed",
    ["task_type", "status"],
)

UPSTREAM_ERRORS = Counter(
    "gateway_upstream_errors_total",
    "Total number of errors from upstream AI providers",
    ["task_type", "provider"],
)
