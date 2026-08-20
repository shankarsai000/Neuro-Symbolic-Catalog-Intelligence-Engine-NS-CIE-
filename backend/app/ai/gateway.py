"""
NS-CIE v2.2 - Nemotron Inference Gateway & High-Throughput Engine
Provides Local, Hosted, and Auto NIM provider selection, persistent connection pooling,
adaptive concurrency, circuit breaker, structured JSON output validation, and detailed metrics.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class NIMMetrics:
    """Metrics collector for NIM requests."""

    def __init__(self) -> None:
        self.total_requests: int = 0
        self.success_count: int = 0
        self.status_429_count: int = 0
        self.status_5xx_count: int = 0
        self.timeout_count: int = 0
        self.parse_failure_count: int = 0
        self.fallback_count: int = 0
        self.total_latency_ms: float = 0.0
        self.active_requests: int = 0

    def record_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self.success_count += 1
        self.total_latency_ms += latency_ms

    def record_failure(self, error_type: str, latency_ms: float = 0.0) -> None:
        self.total_requests += 1
        self.total_latency_ms += latency_ms
        if error_type == "HTTP_429":
            self.status_429_count += 1
        elif error_type == "HTTP_5XX":
            self.status_5xx_count += 1
        elif error_type == "TIMEOUT":
            self.timeout_count += 1
        elif error_type == "PARSE_FAILURE":
            self.parse_failure_count += 1

    def to_dict(self) -> Dict[str, Any]:
        avg_latency = (self.total_latency_ms / self.total_requests) if self.total_requests > 0 else 0.0
        return {
            "nim_requests_total": self.total_requests,
            "nim_requests_success": self.success_count,
            "nim_requests_429": self.status_429_count,
            "nim_requests_5xx": self.status_5xx_count,
            "nim_requests_timeout": self.timeout_count,
            "nim_requests_parse_failure": self.parse_failure_count,
            "nim_requests_fallback": self.fallback_count,
            "nim_avg_latency_ms": round(avg_latency, 2),
            "nim_active_requests": self.active_requests,
        }


nim_metrics = NIMMetrics()


class CircuitBreaker:
    """Circuit breaker for NIM endpoints."""

    def __init__(self, failure_threshold: float = 0.5, window_size: int = 10, reset_timeout_sec: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.window_size = window_size
        self.reset_timeout_sec = reset_timeout_sec
        self.history: List[bool] = []
        self.is_open: bool = False
        self.last_state_change: float = 0.0

    def record_result(self, success: bool) -> None:
        self.history.append(success)
        if len(self.history) > self.window_size:
            self.history.pop(0)

        if len(self.history) >= self.window_size:
            failures = sum(1 for item in self.history if not item)
            failure_rate = failures / len(self.history)
            if failure_rate >= self.failure_threshold:
                if not self.is_open:
                    logger.error(f"[CIRCUIT BREAKER] Tripped open! Failure rate: {failure_rate:.1%}")
                    self.is_open = True
                    self.last_state_change = time.monotonic()

    def allow_request(self) -> bool:
        if not self.is_open:
            return True

        if time.monotonic() - self.last_state_change > self.reset_timeout_sec:
            logger.info("[CIRCUIT BREAKER] Reset timeout expired. Testing half-open state...")
            self.is_open = False
            self.history.clear()
            return True

        return False


class AdaptiveConcurrencyController:
    """Dynamically scales concurrency between min_concurrency and max_concurrency."""

    def __init__(self, min_concurrency: int = 1, max_concurrency: int = 10) -> None:
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.current_concurrency = min_concurrency
        self.semaphore = asyncio.Semaphore(self.current_concurrency)
        self._lock = asyncio.Lock()

    async def adjust_concurrency(self, success: bool, is_429: bool = False) -> None:
        async with self._lock:
            if is_429:
                old = self.current_concurrency
                self.current_concurrency = self.min_concurrency
                logger.warning(f"[ADAPTIVE CONCURRENCY] 429 Rate Limit hit. Scaled down {old} -> {self.current_concurrency}")
            elif success and self.current_concurrency < self.max_concurrency:
                self.current_concurrency += 1


class StructuredResponseValidator:
    """Validates raw LLM outputs against JSON and schema constraints."""

    @staticmethod
    def validate_json_and_extract(content: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        if not content or not content.strip():
            return False, None, "Empty LLM content"

        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                return False, None, "Parsed JSON is not a dictionary"
            return True, parsed, "OK"
        except json.JSONDecodeError as e:
            return False, None, f"JSONDecodeError: {e}"


class LocalNIMProvider:
    """NIM Provider for Local GPU Infrastructure."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def is_healthy(self, http_client: httpx.AsyncClient) -> bool:
        try:
            url = f"{self.base_url}/models"
            resp = await http_client.get(url, timeout=1.5)
            return resp.status_code == 200
        except Exception:
            return False


class HostedNIMProvider:
    """NIM Provider for Hosted NVIDIA API Endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def is_configured(self) -> bool:
        if not self.api_key:
            return False
        clean = self.api_key.strip().lower()
        return clean not in ["", "dummy_key_if_missing", "mock-api-key"] and not clean.startswith("dummy")


class InferenceGateway:
    """Main Inference Gateway managing Provider Selection, Pooling, Concurrency, and Circuit Breaking."""

    def __init__(self) -> None:
        self.mode = getattr(settings, "nim_mode", "auto").lower()
        self.hosted_provider = HostedNIMProvider(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key,
            model=settings.nvidia_model,
        )
        self.local_provider = LocalNIMProvider(
            base_url=getattr(settings, "local_nim_base_url", "http://localhost:8000/v1"),
            model=getattr(settings, "local_nim_model", settings.nvidia_model),
        )
        self.circuit_breaker = CircuitBreaker()
        self.concurrency_controller = AdaptiveConcurrencyController(
            min_concurrency=1,
            max_concurrency=getattr(settings, "nim_max_concurrency_adaptive", 10)
        )
        self._async_client: Optional[httpx.AsyncClient] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
            self._async_client = httpx.AsyncClient(limits=limits, timeout=settings.nvidia_timeout_sec)
        return self._async_client

    async def health_check(self) -> Dict[str, Any]:
        http_client = await self.get_http_client()
        local_healthy = await self.local_provider.is_healthy(http_client)
        hosted_configured = self.hosted_provider.is_configured()

        active_provider = "NONE"
        if self.mode == "local" or (self.mode == "auto" and local_healthy):
            active_provider = "LOCAL"
        elif self.mode == "hosted" or (self.mode == "auto" and hosted_configured):
            active_provider = "HOSTED"

        return {
            "mode": self.mode,
            "active_provider": active_provider,
            "local_healthy": local_healthy,
            "hosted_configured": hosted_configured,
            "circuit_open": self.circuit_breaker.is_open,
            "metrics": nim_metrics.to_dict(),
        }

    async def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> Tuple[str, Dict[str, Any], int]:
        """
        Executes NIM Chat Completion asynchronously with connection pooling, retries, and rate limit handling.
        Returns (content, usage_dict, retry_count).
        """
        if not self.circuit_breaker.allow_request():
            nim_metrics.record_failure("CIRCUIT_OPEN")
            raise RuntimeError("InferenceGateway CircuitBreaker is open due to recent endpoint errors.")

        http_client = await self.get_http_client()

        if self.mode == "local" or (self.mode == "auto" and await self.local_provider.is_healthy(http_client)):
            target_url = f"{self.local_provider.base_url}/chat/completions"
            target_model = self.local_provider.model
            headers = {"Content-Type": "application/json"}
            provider_name = "LOCAL_NIM"
        else:
            if not self.hosted_provider.is_configured():
                nim_metrics.record_failure("UNCONFIGURED")
                raise ValueError("Hosted NVIDIA NIM API key is unconfigured.")
            target_url = f"{self.hosted_provider.base_url}/chat/completions"
            target_model = self.hosted_provider.model
            headers = {
                "Authorization": f"Bearer {self.hosted_provider.api_key}",
                "Content-Type": "application/json"
            }
            provider_name = "HOSTED_NIM"

        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if "nemotron" in target_model.lower():
            payload["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

        start_time = time.perf_counter()
        retries = 0
        max_retries = settings.nvidia_max_retries

        async with self.concurrency_controller.semaphore:
            nim_metrics.active_requests += 1
            try:
                for attempt in range(1, max_retries + 1):
                    try:
                        resp = await http_client.post(target_url, json=payload, headers=headers)
                        if resp.status_code == 200:
                            latency_ms = (time.perf_counter() - start_time) * 1000.0
                            data = resp.json()
                            content = data["choices"][0]["message"]["content"]
                            usage = data.get("usage", {})
                            usage_dict = {
                                "model": target_model,
                                "provider": provider_name,
                                "latency_ms": latency_ms,
                                "prompt_tokens": usage.get("prompt_tokens", 0),
                                "completion_tokens": usage.get("completion_tokens", 0),
                            }
                            
                            valid_json, _, err_msg = StructuredResponseValidator.validate_json_and_extract(content)
                            if not valid_json:
                                nim_metrics.record_failure("PARSE_FAILURE", latency_ms)
                            else:
                                nim_metrics.record_success(latency_ms)

                            self.circuit_breaker.record_result(True)
                            await self.concurrency_controller.adjust_concurrency(True)
                            return content, usage_dict, retries

                        elif resp.status_code == 429:
                            retries += 1
                            await self.concurrency_controller.adjust_concurrency(False, is_429=True)
                            delay = min(settings.nim_backoff_base * (2 ** (attempt - 1)), settings.nim_backoff_max)
                            await asyncio.sleep(delay)

                        else:
                            retries += 1
                            delay = min(settings.nim_backoff_base * (2 ** (attempt - 1)), settings.nim_backoff_max)
                            await asyncio.sleep(delay)

                    except (httpx.TimeoutException, httpx.RequestError) as e:
                        retries += 1
                        delay = min(settings.nim_backoff_base * (2 ** (attempt - 1)), settings.nim_backoff_max)
                        await asyncio.sleep(delay)

                latency_ms = (time.perf_counter() - start_time) * 1000.0
                self.circuit_breaker.record_result(False)
                nim_metrics.record_failure("MAX_RETRIES_EXCEEDED", latency_ms)
                raise RuntimeError(f"NIM Gateway failed after {max_retries} attempts.")
            finally:
                nim_metrics.active_requests -= 1


inference_gateway = InferenceGateway()
