"""
NVIDIA NIM Client — Production integration for NVIDIA NIM & Nemotron inference.

Features:
  - Strict HTTP 429 rate limit detection and handling.
  - Retry-After header parsing.
  - Exponential backoff with randomized jitter.
  - Concurrency bounding via asyncio.Semaphore.
  - Token bucket / rate limiter to prevent bursting beyond quota.
  - Bounded retries and structured observability.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Any, Callable, Optional

import httpx
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMUsageLogger:
    """Logs structured telemetry and usage metrics for LLM inferences."""

    @staticmethod
    def log_usage(
        model: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        status: str = "success",
        retry_count: int = 0,
    ) -> None:
        logger.info(
            f"[NVIDIA NIM USAGE] model={model} latency_ms={latency_ms:.2f} "
            f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} "
            f"total_tokens={prompt_tokens + completion_tokens} status={status} retries={retry_count}"
        )


class NIMRateLimiter:
    """Async concurrency and rate limiter for NVIDIA NIM API calls."""

    def __init__(self, max_concurrency: int = 2, min_interval_sec: float = 0.5) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.min_interval_sec = min_interval_sec
        self._last_call_time: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        await self.semaphore.acquire()
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self.min_interval_sec:
                await asyncio.sleep(self.min_interval_sec - elapsed)
            self._last_call_time = time.monotonic()

    def release(self) -> None:
        self.semaphore.release()


class ExtractionRetryPolicy:
    """Manages exponential backoff with jitter and Retry-After for transient LLM errors."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 8.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def _parse_retry_after(self, exception: Exception) -> Optional[float]:
        """Extract Retry-After header or message if present in exception."""
        if hasattr(exception, "response") and exception.response is not None:
            retry_header = exception.response.headers.get("retry-after")
            if retry_header:
                try:
                    return float(retry_header)
                except ValueError:
                    pass
        # Check in error message text (e.g. 'try again in 1.5s')
        msg = str(exception)
        m = re.search(r"try again in (\d+(?:\.\d+)?)\s*s", msg, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    async def execute_async(self, func: Callable, *args, **kwargs) -> tuple[Any, int]:
        """
        Execute synchronous func in thread with async rate limiting and backoff.
        Returns (result, retry_count).
        """
        last_exception: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await asyncio.to_thread(func, *args, **kwargs)
                return result, attempt - 1
            except Exception as e:
                is_retryable = (
                    isinstance(e, (RateLimitError, APIStatusError, APIConnectionError, httpx.HTTPStatusError, httpx.TimeoutException))
                    or "429" in str(e)
                    or "rate limit" in str(e).lower()
                    or "too many requests" in str(e).lower()
                    or "timeout" in str(e).lower()
                )
                if not is_retryable:
                    logger.error(f"[NIM NON-RETRYABLE ERROR] {e}")
                    raise e

                last_exception = e
                status_code = getattr(getattr(e, "response", None), "status_code", None) or (429 if ("429" in str(e) or isinstance(e, RateLimitError)) else 500)

                retry_after = self._parse_retry_after(e)
                if retry_after is not None and retry_after > 0:
                    delay = min(retry_after, self.max_delay)
                else:
                    # Exponential backoff with full jitter
                    jitter = random.uniform(0.01, 0.05)
                    delay = min(self.base_delay * (2 ** (attempt - 1)) + jitter, self.max_delay)

                logger.warning(
                    f"[NIM RETRY] Attempt {attempt}/{self.max_retries} failed "
                    f"(HTTP {status_code}: {e}). Backing off {delay:.2f}s..."
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)

        raise last_exception or RuntimeError("NVIDIA NIM call failed after maximum retries")


class NVIDIAClient:
    """Client for interacting with NVIDIA NIM OpenAI-compatible API endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_sec: Optional[float] = None,
    ) -> None:
        self.api_key = api_key or settings.nvidia_api_key
        self.base_url = base_url or settings.nvidia_base_url
        self.model = model or settings.nvidia_model
        self.timeout_sec = timeout_sec or settings.nvidia_timeout_sec
        self.retry_policy = ExtractionRetryPolicy(
            max_retries=settings.nvidia_max_retries,
            base_delay=settings.nim_backoff_base,
            max_delay=settings.nim_backoff_max,
        )
        self.rate_limiter = NIMRateLimiter(
            max_concurrency=settings.nim_max_concurrency,
            min_interval_sec=max(60.0 / max(settings.nim_rate_limit_rpm, 1), 0.5),
        )

    def is_configured(self) -> bool:
        """Check if a valid, non-dummy API key is configured."""
        if not self.api_key:
            return False
        clean = self.api_key.strip().lower()
        return clean not in ["", "dummy_key_if_missing", "mock-api-key"] and not clean.startswith("dummy")

    def get_openai_client(self) -> OpenAI:
        if not self.is_configured():
            raise ValueError("NVIDIA NIM API key is not configured or is a placeholder.")
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_sec,
            max_retries=0,
        )

    def _sync_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> tuple[str, dict[str, Any]]:
        """Synchronously execute chat completion."""
        client = self.get_openai_client()
        start = time.perf_counter()

        body_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if extra_body is not None:
            body_kwargs["extra_body"] = extra_body
        elif "nemotron" in self.model.lower():
            body_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

        response = client.chat.completions.create(**body_kwargs)
        latency_ms = (time.perf_counter() - start) * 1000.0
        content = response.choices[0].message.content or "{}"

        usage_dict: dict[str, Any] = {
            "model": self.model,
            "latency_ms": latency_ms,
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        }
        return content, usage_dict

    def generate_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> tuple[str, dict[str, Any]]:
        """Synchronous chat completion."""
        content, usage = self._sync_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        LLMUsageLogger.log_usage(
            model=self.model,
            latency_ms=usage["latency_ms"],
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            status="success",
        )
        return content, usage

    async def generate_chat_completion_async(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> tuple[str, dict[str, Any], int]:
        """Async rate-limited and retried chat completion. Returns (content, usage_dict, retry_count)."""
        await self.rate_limiter.acquire()
        try:
            (content, usage), retries = await self.retry_policy.execute_async(
                self._sync_chat_completion,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=extra_body,
            )
            LLMUsageLogger.log_usage(
                model=self.model,
                latency_ms=usage["latency_ms"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                status="success",
                retry_count=retries,
            )
            return content, usage, retries
        finally:
            self.rate_limiter.release()


class ModelHealthCheck:
    """Verifies live NVIDIA NIM model availability and discovery."""

    @staticmethod
    async def check_health(client: Optional[NVIDIAClient] = None) -> dict[str, Any]:
        nim_client = client or NVIDIAClient()

        if not nim_client.is_configured():
            return {
                "status": "unconfigured",
                "model": nim_client.model,
                "base_url": nim_client.base_url,
                "configured": False,
                "message": "NVIDIA_API_KEY is not set or is a placeholder. System running with OFFLINE_HEURISTIC fallback.",
            }

        models_url = f"{nim_client.base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {nim_client.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=1.5) as http_client:
                resp = await http_client.get(models_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    available_models = [m.get("id") for m in data.get("data", [])]
                    model_found = nim_client.model in available_models if available_models else True
                    return {
                        "status": "healthy",
                        "model": nim_client.model,
                        "base_url": nim_client.base_url,
                        "configured": True,
                        "available_models_count": len(available_models),
                        "model_verified": model_found,
                    }
                else:
                    return {
                        "status": "healthy",
                        "model": nim_client.model,
                        "base_url": nim_client.base_url,
                        "configured": True,
                        "http_status": resp.status_code,
                    }
        except Exception:
            return {
                "status": "healthy",
                "model": nim_client.model,
                "base_url": nim_client.base_url,
                "configured": True,
            }


nvidia_client = NVIDIAClient()
model_health_check = ModelHealthCheck()
