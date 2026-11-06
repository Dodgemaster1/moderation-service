from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MetricFlow Moderation Service"
    database_url: str = Field(
        default="postgresql+psycopg://moderation:moderation@localhost:5432/moderation",
        validation_alias="DATABASE_URL",
    )
    debug: bool = False
    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    llm_base_url: str = Field(
        default="https://api.openai.com/v1/chat/completions",
        validation_alias="LLM_BASE_URL",
    )
    llm_model: str = Field(default="gpt-4o-mini", validation_alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=30.0, validation_alias="LLM_TIMEOUT_SECONDS", gt=0)
    helpdesk_timeout_seconds: float = Field(default=5.0, validation_alias="HELPDESK_TIMEOUT_SECONDS", gt=0)
    worker_poll_seconds: float = Field(default=1.0, validation_alias="WORKER_POLL_SECONDS", gt=0)
    worker_concurrency: int = Field(default=20, validation_alias="WORKER_CONCURRENCY", gt=0)
    mock_failure_rate: float = Field(default=0.2, validation_alias="MOCK_FAILURE_RATE", ge=0, le=1)
    mock_timeout_rate: float = Field(default=0.1, validation_alias="MOCK_TIMEOUT_RATE", ge=0, le=1)
    mock_timeout_seconds: float = Field(default=6.0, validation_alias="MOCK_TIMEOUT_SECONDS", gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
