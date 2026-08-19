from __future__ import annotations

import collections
import json
import logging
import time
from typing import Any, Callable
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.observability import StructuredLogEntry

logger = logging.getLogger(__name__)

# Sliding window rate limiter state
_RATE_LIMIT_STORE: dict[str, collections.deque[float]] = collections.defaultdict(collections.deque)
MAX_STORE_ENTRIES = 10000


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware rejecting request payloads exceeding configured size limit."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")
        max_bytes = settings.max_request_size_mb * 1024 * 1024

        if content_length:
            try:
                length = int(content_length)
                if length > max_bytes:
                    log_entry = StructuredLogEntry(
                        stage="security_request_size",
                        status="REJECTED",
                        duration_ms=0.0,
                        error=f"Payload length {length} bytes exceeds {max_bytes} bytes",
                        metadata={"content_length": length, "path": str(request.url.path)},
                    )
                    logger.warning(json.dumps(log_entry.to_dict()))
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "Payload Too Large",
                            "message": f"Request payload exceeds max allowed limit of {settings.max_request_size_mb} MB",
                        },
                    )
            except ValueError:
                pass

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing sliding window rate limits per client IP."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limit for internal health checks if needed
        path = request.url.path
        if path.endswith("/health") or path.endswith("/metrics"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        window_start = now - 60.0

        # Memory cleanup if store grows too large
        if len(_RATE_LIMIT_STORE) > MAX_STORE_ENTRIES:
            _RATE_LIMIT_STORE.clear()

        timestamps = _RATE_LIMIT_STORE[client_ip]

        # Evict timestamps older than 60 seconds
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        limit = settings.rate_limit_per_minute
        if len(timestamps) >= limit:
            log_entry = StructuredLogEntry(
                stage="security_rate_limit",
                status="BLOCKED",
                duration_ms=0.0,
                error=f"Client IP {client_ip} exceeded {limit} req/min limit",
                metadata={"client_ip": client_ip, "path": path},
            )
            logger.warning(json.dumps(log_entry.to_dict()))
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "60"},
                content={
                    "error": "Too Many Requests",
                    "message": f"Rate limit of {limit} requests per minute exceeded. Please retry later.",
                },
            )

        timestamps.append(now)
        return await call_next(request)


async def safe_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler suppressing internal stack traces in response payloads."""
    request_id = getattr(request.state, "request_id", "unknown")
    log_entry = StructuredLogEntry(
        stage="uncaught_exception",
        status="ERROR",
        duration_ms=0.0,
        request_id=request_id,
        error=str(exc),
        metadata={"path": str(request.url.path), "method": request.method, "exception_type": exc.__class__.__name__},
    )
    logger.error(json.dumps(log_entry.to_dict()), exc_info=exc)

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred while processing your request. Internal details have been securely logged.",
            "request_id": request_id,
        },
    )


def validate_uploaded_file_security(
    filename: str,
    file_bytes: bytes,
    content_type: str = "",
) -> None:
    """Validate uploaded file size, extension, MIME type, magic signatures, and content safety."""
    if not filename:
        raise HTTPException(status_code=400, detail="Filename must not be empty.")

    max_bytes = settings.max_request_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file size ({len(file_bytes)} bytes) exceeds maximum limit of {settings.max_request_size_mb} MB.",
        )

    fn_lower = filename.lower()
    allowed_exts = (".csv", ".xlsx")
    if not any(fn_lower.endswith(ext) for ext in allowed_exts):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{filename}'. Supported extensions are: {', '.join(allowed_exts)}",
        )

    # Executable signature validation (PE / ELF / Shell scripts)
    if file_bytes.startswith(b"MZ") or file_bytes.startswith(b"\x7fELF"):
        raise HTTPException(status_code=400, detail="Security policy violation: Executable binaries are prohibited.")

    if fn_lower.endswith(".xlsx"):
        # ZIP archive signature (PK\x03\x04)
        if not file_bytes.startswith(b"PK\x03\x04"):
            raise HTTPException(status_code=400, detail="Invalid XLSX file structure: Missing ZIP magic header.")
    elif fn_lower.endswith(".csv"):
        # CSV Script injection & malformed payload check
        snippet = file_bytes[:8192].decode("utf-8", errors="ignore").lower()
        dangerous_patterns = ["<script", "javascript:", "vbscript:", "=cmd|", "=exec|", "+cmd|", "-cmd|"]
        for pattern in dangerous_patterns:
            if pattern in snippet:
                raise HTTPException(
                    status_code=400,
                    detail="Security policy violation: Potentially malicious script or formula injection detected in CSV file.",
                )
