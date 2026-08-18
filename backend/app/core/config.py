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
    nvidia_timeout_sec: float = Field(default=5.0, description="HTTP timeout for NIM inference requests")
    nvidia_max_retries: int = Field(default=2, description="Maximum retries for NIM API errors")
    require_live_nim: bool = Field(default=False, description="Enforce hard failure if live NIM is unavailable in production")

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
