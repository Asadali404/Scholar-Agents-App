"""Groq (OpenAI-compatible) LLM wrapper usable by CrewAI agents.

Uses the OpenAI Python SDK pointed at Groq's OpenAI-compatible endpoint, so the model id
``openai/gpt-oss-120b`` is sent to Groq unchanged (no LiteLLM provider-prefix rewriting).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, BadRequestError, OpenAI, RateLimitError

from sh_app.core.config import Settings

try:  # CrewAI exports BaseLLM from the top level in recent releases
    from crewai import BaseLLM
except ImportError:  # pragma: no cover
    from crewai.llms.base_llm import BaseLLM

logger = logging.getLogger(__name__)


class LLMCallError(RuntimeError):
    """User-facing LLM failure (rate limit, connectivity, auth...)."""


def get_openai_client(settings: Settings) -> OpenAI:
    """OpenAI SDK client targeting Groq."""
    return OpenAI(api_key=settings.groq_api_key, base_url=settings.base_url, timeout=90, max_retries=0)


class GroqChatLLM(BaseLLM):
    """CrewAI-compatible chat model backed by the OpenAI SDK + Groq."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(model=settings.model, temperature=settings.temperature)
        self._client = get_openai_client(settings)
        self._max_tokens = settings.max_output_tokens
        self._reasoning = "gpt-oss" in settings.model

    def call(self, messages: Any, tools: Any = None, callbacks: Any = None,
             available_functions: Any = None, from_task: Any = None, from_agent: Any = None,
             **kwargs: Any) -> str:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        return self._complete(list(messages))

    def _complete(self, messages: list[dict]) -> str:
        delay, use_reasoning = 10.0, self._reasoning
        last = "unknown error"
        for attempt in range(4):
            try:
                extra = {"extra_body": {"reasoning_effort": "low"}} if use_reasoning else {}
                resp = self._client.chat.completions.create(
                    model=self.model, messages=messages, temperature=self.temperature,
                    max_tokens=self._max_tokens, **extra)
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    return content
                last = "empty response"
            except RateLimitError:
                last = "Groq rate limit reached"
                logger.warning("Rate limited; waiting %.0fs", delay)
                time.sleep(delay)
                delay *= 2
            except BadRequestError as exc:
                if use_reasoning:
                    use_reasoning = False  # retry without the optional parameter
                    continue
                raise LLMCallError(f"The model rejected the request ({type(exc).__name__}).") from exc
            except (APIConnectionError, APITimeoutError) as exc:
                last = "connection problem"
                logger.warning("LLM connection problem: %s", type(exc).__name__)
                time.sleep(3)
            except APIError as exc:
                raise LLMCallError(f"LLM API error ({type(exc).__name__}). Check GROQ_API_KEY and model name.") from exc
        raise LLMCallError(f"LLM request failed after retries: {last}. Please wait a minute and try again.")

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False

    def get_context_window_size(self) -> int:
        return 100000


def build_llm(settings: Settings) -> GroqChatLLM:
    """Create the shared LLM instance."""
    settings.require_api_key()
    return GroqChatLLM(settings)
