from __future__ import annotations

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

    # LLM Service Configuration
    llm_api_key: str = Field(
        default="dummy_key_if_missing",
        description="NVIDIA NIM or OpenAI API Key",
    )
    llm_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="Custom OpenAI-compatible base URL",
    )
    llm_model_name: str = Field(
        default="nvidia/nemotron-3.5-lightning-30b-a3b",
        description="LLM Model Name",
    )

    @property
    def LLM_API_KEY(self) -> str:
        return self.llm_api_key

    @property
    def LLM_BASE_URL(self) -> str:
        return self.llm_base_url

    @property
    def LLM_MODEL_NAME(self) -> str:
        return self.llm_model_name


settings = Settings()
