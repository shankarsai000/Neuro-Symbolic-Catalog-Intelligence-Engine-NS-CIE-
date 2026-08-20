from __future__ import annotations

import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="NS-CIE")
    environment: str = Field(default="development")
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)

    # NVIDIA NIM / OpenAI-compatible Service Configuration
    nvidia_api_key: str = Field(
        default=os.getenv("NVIDIA_API_KEY", os.getenv("LLM_API_KEY", "")),
        description="NVIDIA NIM API Key",
    )
    nvidia_base_url: str = Field(
        default=os.getenv("NVIDIA_BASE_URL", os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")),
        description="NVIDIA NIM Base URL",
    )
    nvidia_model: str = Field(
        default=os.getenv("NVIDIA_MODEL", os.getenv("LLM_MODEL_NAME", "nvidia/nemotron-3.5-lightning-30b-a3b")),
        description="NVIDIA NIM Model Name",
    )
    nvidia_timeout_sec: float = Field(default=float(os.getenv("NIM_REQUEST_TIMEOUT", "8.0")), description="HTTP timeout for NIM inference requests")
    nvidia_max_retries: int = Field(default=int(os.getenv("NIM_MAX_RETRIES", "3")), description="Maximum retries for NIM API errors")
    nim_max_concurrency: int = Field(default=int(os.getenv("NIM_MAX_CONCURRENCY", "10")), description="Maximum parallel in-flight NIM requests")
    nim_backoff_base: float = Field(default=float(os.getenv("NIM_BACKOFF_BASE", "1.0")), description="Base backoff delay in seconds")
    nim_backoff_max: float = Field(default=float(os.getenv("NIM_BACKOFF_MAX", "8.0")), description="Maximum backoff delay in seconds")
    nim_rate_limit_rpm: int = Field(default=int(os.getenv("NIM_RATE_LIMIT_RPM", "300")), description="Max NIM requests per minute")
    require_live_nim: bool = Field(default=False, description="Enforce hard failure if live NIM is unavailable in production")
    # Security Configuration
    secret_key: str = Field(default=os.getenv("SECRET_KEY", "nscie_default_secret_key_change_in_production"), description="Application secret key")
    allowed_cors_origins: str = Field(
        default=os.getenv("ALLOWED_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"),
        description="Comma-separated allowed CORS origins",
    )
    max_request_size_mb: int = Field(default=50, description="Max allowed request payload size in MB")
    rate_limit_per_minute: int = Field(default=120, description="Rate limit requests per minute per IP")
    enable_strict_ssrf_protection: bool = Field(default=True, description="Strict DNS resolution and IP filtering for SSRF")

    @property
    def cors_origins_list(self) -> list[str]:
        default_local = [
            "http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://localhost:3003", "http://localhost:3004", "http://localhost:3005", "http://localhost:5173", "http://localhost:8888",
            "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:3002", "http://127.0.0.1:3003", "http://127.0.0.1:3004", "http://127.0.0.1:5173", "http://127.0.0.1:8888",
        ]
        if not self.allowed_cors_origins:
            return default_local
        origins = [o.strip() for o in self.allowed_cors_origins.split(",") if o.strip()]
        for loc in default_local:
            if loc not in origins:
                origins.append(loc)
        return origins

    # Backward-compatible property aliases
    @property
    def LLM_API_KEY(self) -> str:
        return self.nvidia_api_key

    @property
    def LLM_BASE_URL(self) -> str:
        return self.nvidia_base_url

    @property
    def LLM_MODEL_NAME(self) -> str:
        return self.nvidia_model


settings = Settings()
