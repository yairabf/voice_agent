import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_KEYS or key.startswith("_"):
                continue
            payload[key] = value
        return json.dumps(payload, default=str, separators=(",", ":"))


_STANDARD_LOG_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, logger: logging.Logger) -> None:
        super().__init__(app)
        self._logger = logger

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            extra: Mapping[str, Any] = {
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "session_id": request.path_params.get("session_id"),
                "input_length": request.headers.get("content-length"),
            }
            self._logger.info("request_complete", extra=extra)


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("voice_agent")
    logger.setLevel(level.upper())
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger
