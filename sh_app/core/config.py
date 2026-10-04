"""Configuration: Streamlit secrets first, then environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


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
        groq_api_key=(_read("GROQ_API_KEY", "") or "").strip(),
        model=(_read("LLM_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL).strip(),
        base_url=(_read("LLM_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).strip(),
        temperature=_num("LLM_TEMPERATURE", 0.2, float),
        max_output_tokens=_num("MAX_OUTPUT_TOKENS", 4096),
        max_pages=_num("MAX_PAGES", 12),
        max_results=_num("MAX_RESULTS", 12),
        results_per_query=_num("RESULTS_PER_QUERY", 8),
        max_queries=_num("MAX_QUERIES", 10),
    )
