"""Structured JSON request logging and correlation ID middleware with secret redaction."""

import json
import logging
import re
import sys
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

SENSITIVE_KEYS = {
    "password",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "encrypted_token",
    "secret_key",
    "secret",
    "authorization",
    "cookie",
}

REDACTED_STR = "[REDACTED]"


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured application logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logging() -> None:
    """Initialize structured JSON logging for the application."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root_logger.addHandler(handler)


logger = logging.getLogger("taskflow")


def redact_sensitive_data(data: dict[str, object] | list[object] | str) -> object:
    """Recursively redact sensitive credentials and tokens."""
    if isinstance(data, dict):
        return {
            k: REDACTED_STR if k.lower() in SENSITIVE_KEYS else redact_sensitive_data(v)  # type: ignore[arg-type]
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]  # type: ignore[arg-type]
    elif isinstance(data, str):
        # Redact JWT patterns or bearer tokens in strings
        if re.search(r"Bearer\s+[A-Za-z0-9\-_.]+", data, re.IGNORECASE):
            return re.sub(r"Bearer\s+[A-Za-z0-9\-_.]+", "Bearer [REDACTED]", data)
    return data


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assigns or propagates X-Correlation-Id and logs request metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        start_time = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            status_code = response.status_code if response else 500

            # Add correlation ID to response headers if response exists
            if response is not None:
                response.headers["X-Correlation-Id"] = correlation_id

            # Skip health check logging in production noise
            if request.url.path != "/health":
                log_record = logging.LogRecord(
                    name="taskflow.request",
                    level=logging.INFO,
                    pathname=__file__,
                    lineno=0,
                    msg=(
                        f"{request.method} {request.url.path} "
                        f"- Status: {status_code} - {duration_ms}ms"
                    ),
                    args=(),
                    exc_info=None,
                )
                log_record.correlation_id = correlation_id
                logger.handle(log_record)
