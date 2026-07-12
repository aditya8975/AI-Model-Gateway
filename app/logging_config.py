"""
Structured logging configuration.

Produces JSON logs (one object per line) suitable for ingestion by
Loki / ELK / CloudWatch etc. Falls back to plain text if LOG_JSON=False.
Every log line automatically includes the current request_id (if any),
set via contextvars by the logging middleware.
"""
import logging
import sys
from contextvars import ContextVar
from pythonjsonlogger import jsonlogger

from app.config import settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
api_key_id_ctx: ContextVar[str] = ContextVar("api_key_id", default="-")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.api_key_id = api_key_id_ctx.get()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())

    # Remove pre-existing handlers (uvicorn adds its own)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())

    if settings.LOG_JSON:
        fmt = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "%(request_id)s %(api_key_id)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
        )
    else:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | "
            "req=%(request_id)s key=%(api_key_id)s | %(message)s"
        )

    handler.setFormatter(fmt)
    root.addHandler(handler)

    # Tame noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
