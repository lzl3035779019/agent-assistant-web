from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "PMAA Web"
    api_prefix: str = "/api/v1"
    backend_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    auth_enabled: bool = False

    task_execution_mode: Literal["local", "arq"] = "local"
    database_url: str = "postgresql+asyncpg://pmaa:pmaa@127.0.0.1:5432/pmaa"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_event_stream_maxlen: int = 2000
    redis_publish_timeout_seconds: float = 0.3

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    deepseek_api_key: str = ""

    embedding_provider: Literal[
        "disabled", "fastembed", "openai_compatible"
    ] = "fastembed"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dimensions: int = 512
    embedding_batch_size: int = 64
    fastembed_cache_dir: str = ".cache/fastembed"
    fastembed_threads: int | None = None

    web_search_provider: Literal["disabled", "tavily"] = "disabled"
    tavily_base_url: str = "https://api.tavily.com/search"
    tavily_api_key: str = ""
    tavily_max_results: int = 5
    agent_runtime_max_concurrency: int = 4
    web_research_max_rounds: int = 2
    web_research_max_queries: int = 3

    email_enabled: bool = False
    email_provider: Literal["qq"] = "qq"
    qq_email_address: str = ""
    qq_email_auth_code: str = ""
    qq_imap_host: str = "imap.qq.com"
    qq_imap_port: int = 993
    qq_smtp_host: str = "smtp.qq.com"
    qq_smtp_port: int = 465
    email_poll_interval_seconds: int = 300

    github_monitor_enabled: bool = False
    github_token: str = ""
    github_api_base_url: str = "https://api.github.com"
    automation_scheduler_enabled: bool = False
    automation_poll_interval_seconds: int = 60

    feishu_calendar_enabled: bool = False
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_redirect_uri: str = (
        "http://127.0.0.1:8000/api/v1/calendar/feishu/callback"
    )
    feishu_oauth_state_ttl_seconds: int = 600
    feishu_token_encryption_key: str = ""

    jwt_secret_key: str = "change-this-before-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    qdrant_url: str = "http://127.0.0.1:16333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "pmaa_documents"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_secure: bool = False
    minio_access_key: str = "pmaa"
    minio_secret_key: str = "change-me"
    minio_bucket: str = "pmaa-documents"
    max_upload_size_mb: int = 50
    chunk_size: int = 900
    chunk_overlap: int = 150
    retrieval_top_k: int = 8

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.app_env == "production":
            if not self.auth_enabled:
                raise ValueError("AUTH_ENABLED must be true in production")
            if self.jwt_secret_key == "change-this-before-production" or len(self.jwt_secret_key) < 32:
                raise ValueError("JWT_SECRET_KEY must be replaced with at least 32 characters")
            if self.task_execution_mode != "arq":
                raise ValueError("TASK_EXECUTION_MODE must be arq in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
