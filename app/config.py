"""Runtime configuration. Everything comes from the environment -- no secrets in code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _default_database_url() -> str:
    """Vercel's filesystem is read-only except /tmp, so SQLite has to live there."""
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit
    if os.environ.get("VERCEL"):
        return "sqlite:////tmp/tafseel.db"
    return "sqlite:///./tafseel.db"


@dataclass(frozen=True)
class Settings:
    app_name: str = "Tafseel"
    version: str = "1.0.0"
    environment: str = field(default_factory=lambda: os.environ.get("ENVIRONMENT", "development"))

    database_url: str = field(default_factory=_default_database_url)

    secret_key: str = field(
        default_factory=lambda: os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
    )
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = field(default_factory=lambda: _int("ACCESS_TOKEN_MINUTES", 1440))

    # Long-context limits. A "token" here is a 4-character estimate -- cheap and
    # good enough for chunk sizing, and it keeps the app dependency-free.
    chunk_size_tokens: int = field(default_factory=lambda: _int("CHUNK_SIZE_TOKENS", 700))
    chunk_overlap_tokens: int = field(default_factory=lambda: _int("CHUNK_OVERLAP_TOKENS", 80))
    max_document_chars: int = field(default_factory=lambda: _int("MAX_DOCUMENT_CHARS", 2_000_000))
    max_documents_per_analysis: int = field(default_factory=lambda: _int("MAX_DOCUMENTS_PER_ANALYSIS", 12))
    summary_sentences: int = field(default_factory=lambda: _int("SUMMARY_SENTENCES", 7))

    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in os.environ.get("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
            if o.strip()
        )
    )

    rate_limit_analysis: str = field(
        default_factory=lambda: os.environ.get("RATE_LIMIT_ANALYSIS", "20/minute")
    )
    rate_limit_auth: str = field(default_factory=lambda: os.environ.get("RATE_LIMIT_AUTH", "10/minute"))

    debug: bool = field(default_factory=lambda: _bool("DEBUG", False))

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def using_default_secret(self) -> bool:
        return self.secret_key == "dev-only-insecure-key-change-me"


settings = Settings()
