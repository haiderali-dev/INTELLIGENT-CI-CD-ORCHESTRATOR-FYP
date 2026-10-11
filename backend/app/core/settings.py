"""Application settings, read from the environment and validated at import time.

Every setting BUILD_PROMPT 4.4.2 names lives here. The class fails fast when a required value is
missing, because a backend that starts without a database URL and then 500s on the first request is
harder to diagnose than one that refuses to boot.
"""

from __future__ import annotations

import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmMode(StrEnum):
    """How the AI core reaches a model.

    ``fake`` and ``replay`` exist so every test and the whole demo can run with no API key and no
    network, which is what keeps the free-tier quota out of the critical path.
    """

    LIVE = "live"
    REPLAY = "replay"
    FAKE = "fake"


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Validated application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Environment.DEV

    # --- Database -------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://orchestrator:orchestrator@localhost:5432/orchestrator",
        description="SQLAlchemy async URL. asyncpg for PostgreSQL, aiosqlite in tests.",
    )

    # --- Jenkins --------------------------------------------------------------
    jenkins_url: str = "http://localhost:8087"
    jenkins_user: str = "orchestrator-bot"
    jenkins_token: str = ""

    # --- Security -------------------------------------------------------------
    jwt_secret: str = Field(default="", description="HS256 signing key. Required outside tests.")
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    metrics_token: str = Field(
        default="", description="Bearer token the plugin uses for POST /api/metrics."
    )

    # --- LLM ------------------------------------------------------------------
    groq_api_key: str = ""
    llm_model_chain: str = "openai/gpt-oss-120b,openai/gpt-oss-20b"
    llm_mode: LlmMode = LlmMode.FAKE

    # --- Application ----------------------------------------------------------
    catalog_path: Path = Path("catalog/services.yaml")
    frontend_origin: str = "http://localhost:5173"
    high_urgency_daily_quota: int = 3

    # --- Seed -----------------------------------------------------------------
    seed_admin_email: str = "admin@example.com"
    seed_admin_password: str = ""

    @field_validator("llm_model_chain")
    @classmethod
    def _chain_not_empty(cls, value: str) -> str:
        if not [model for model in value.split(",") if model.strip()]:
            raise ValueError("LLM_MODEL_CHAIN must name at least one model")
        return value

    @field_validator("access_token_minutes", "refresh_token_days", "high_urgency_daily_quota")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be at least 1")
        return value

    @model_validator(mode="after")
    def _require_secrets_outside_tests(self) -> Settings:
        """Fail fast on a missing secret, except in tests where a generated one is fine.

        Defaulting a JWT secret in production would be worse than refusing to start: every
        deployment would silently share a signing key.
        """
        if self.environment is Environment.TEST:
            if not self.jwt_secret:
                object.__setattr__(self, "jwt_secret", secrets.token_urlsafe(32))
            if not self.metrics_token:
                object.__setattr__(self, "metrics_token", secrets.token_urlsafe(16))
            return self

        missing = [
            name
            for name, value in (
                ("JWT_SECRET", self.jwt_secret),
                ("METRICS_TOKEN", self.metrics_token),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"missing required setting(s): {', '.join(missing)}. "
                "Copy .env.example to .env and fill them in."
            )
        if self.llm_mode is LlmMode.LIVE and not self.groq_api_key:
            raise ValueError("LLM_MODE=live needs GROQ_API_KEY; use fake or replay without a key")
        return self

    @property
    def model_chain(self) -> list[str]:
        """The model chain as a list, in fallback order."""
        return [model.strip() for model in self.llm_model_chain.split(",") if model.strip()]

    @property
    def is_sqlite(self) -> bool:
        """True when running against SQLite, which the unit tests use."""
        return self.database_url.startswith("sqlite")

    @property
    def cors_origins(self) -> list[str]:
        return [self.frontend_origin]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, read once.

    Cached so a misconfiguration surfaces at the first call rather than intermittently, and so
    tests can clear the cache deliberately with ``get_settings.cache_clear()``.
    """
    return Settings()
