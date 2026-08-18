from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional
import httpx
from openai import OpenAI

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
    ) -> None:
        logger.info(
            f"[NVIDIA NIM USAGE] model={model} latency_ms={latency_ms:.2f} "
            f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} "
            f"total_tokens={prompt_tokens + completion_tokens} status={status}"
        )


class ExtractionRetryPolicy:
    """Manages exponential backoff retries for transient LLM errors (429, 503, timeouts)."""

    def __init__(self, max_retries: int = 2, base_delay: float = 0.5) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay

    async def execute_with_retry(self, func, *args, **kwargs) -> Any:
        last_exception: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"NVIDIA NIM call attempt {attempt}/{self.max_retries} failed ({e})"
                )
                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
        raise last_exception or RuntimeError("NVIDIA NIM call failed after retries")


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
        self.retry_policy = ExtractionRetryPolicy(max_retries=settings.nvidia_max_retries)

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
        )

    def generate_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 600,
    ) -> tuple[str, dict[str, Any]]:
        """Synchronously execute chat completion against the NIM endpoint."""
        client = self.get_openai_client()
        start = time.perf_counter()

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        latency_ms = (time.perf_counter() - start) * 1000.0
        content = response.choices[0].message.content or "{}"

        usage_dict: dict[str, Any] = {
            "model": self.model,
            "latency_ms": latency_ms,
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        }
        LLMUsageLogger.log_usage(
            model=self.model,
            latency_ms=latency_ms,
            prompt_tokens=usage_dict["prompt_tokens"],
            completion_tokens=usage_dict["completion_tokens"],
            status="success",
        )

        return content, usage_dict


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

        # Query /v1/models endpoint via httpx to verify connectivity
        models_url = f"{nim_client.base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {nim_client.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=3.0) as http_client:
                resp = await http_client.get(models_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    available_models = [m.get("id") for m in data.get("data", [])]
                    model_found = nim_client.model in available_models if available_models else True
                    return {
                        "status": "healthy" if model_found else "model_not_found",
                        "model": nim_client.model,
                        "base_url": nim_client.base_url,
                        "configured": True,
                        "available_models_count": len(available_models),
                        "model_verified": model_found,
                    }
                else:
                    return {
                        "status": "degraded",
                        "model": nim_client.model,
                        "base_url": nim_client.base_url,
                        "configured": True,
                        "http_status": resp.status_code,
                        "message": f"NIM endpoint returned status {resp.status_code}",
                    }
        except Exception as e:
            return {
                "status": "offline",
                "model": nim_client.model,
                "base_url": nim_client.base_url,
                "configured": True,
                "error": str(e),
                "message": f"Failed to connect to NVIDIA NIM endpoint ({e})",
            }


nvidia_client = NVIDIAClient()
model_health_check = ModelHealthCheck()
