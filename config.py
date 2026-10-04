"""Configuration: Streamlit secrets first, then environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
# Tried automatically (in order) if Groq denies access (HTTP 403/404) to the main model.
DEFAULT_FALLBACK_MODELS = "openai/gpt-oss-20b"


class MissingAPIKeyError(RuntimeError):
    """Raised when GROQ_API_KEY is not configured."""


def _read(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file / not running in Streamlit
        pass
    return os.getenv(name, default)


def _clean_key(value: Optional[str]) -> str:
    """Remove whitespace, wrapping quotes and an accidental 'Bearer ' prefix from the key."""
    key = (value or "").strip().strip("\"'").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def _num(name: str, default: float, cast=int):
    try:
        return cast(_read(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Runtime settings."""

    groq_api_key: str
    model: str
    base_url: str
    fallback_models: tuple
    temperature: float
    max_output_tokens: int
    max_pages: int
    max_results: int
    results_per_query: int
    max_queries: int

    def require_api_key(self) -> None:
        if not self.groq_api_key:
            raise MissingAPIKeyError(
                "GROQ_API_KEY is not configured. Add it in Streamlit Cloud: App settings → Secrets."
            )


def get_settings() -> Settings:
    """Build settings from secrets/environment (API key is never hard-coded)."""
    return Settings(
        groq_api_key=_clean_key(_read("GROQ_API_KEY", "")),
        model=(_read("LLM_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL).strip(),
        base_url=(_read("LLM_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).strip(),
        fallback_models=tuple(
            m.strip() for m in (_read("LLM_FALLBACK_MODELS", DEFAULT_FALLBACK_MODELS) or "").split(",") if m.strip()),
        temperature=_num("LLM_TEMPERATURE", 0.2, float),
        max_output_tokens=_num("MAX_OUTPUT_TOKENS", 3000),
        max_pages=_num("MAX_PAGES", 12),
        max_results=_num("MAX_RESULTS", 12),
        results_per_query=_num("RESULTS_PER_QUERY", 8),
        max_queries=_num("MAX_QUERIES", 10),
    )
