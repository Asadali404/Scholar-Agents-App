"""Groq (OpenAI-compatible) LLM wrapper usable by CrewAI agents.

Uses the OpenAI Python SDK pointed at Groq's OpenAI-compatible endpoint, so the model id
``openai/gpt-oss-120b`` is sent to Groq unchanged (no LiteLLM provider-prefix rewriting).

Error handling
--------------
* 401 (bad/missing key)            -> clear message, no retry.
* 403 / 404 (model blocked, org restricted, model not found) -> the next model in
  ``LLM_FALLBACK_MODELS`` is tried automatically; if every model fails, the *real* Groq
  message is shown to the user (the API key is never included in any message).
* 429 (rate limit)                 -> exponential back-off, then retry.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from sh_app.core.config import Settings

try:  # CrewAI exports BaseLLM from the top level in recent releases
    from crewai import BaseLLM
except ImportError:  # pragma: no cover
    from crewai.llms.base_llm import BaseLLM

logger = logging.getLogger(__name__)

CONSOLE_HINT = (
    "Fix: open https://console.groq.com → Settings → Limits (check both Organization and "
    "Project) and make sure the model is allowed, and that your API key was created in that "
    "same project. Also check the account is not restricted and that you are not using a "
    "VPN/proxy from an unsupported network."
)


class LLMCallError(RuntimeError):
    """User-facing LLM failure (rate limit, connectivity, auth...)."""


class _ModelUnavailable(Exception):
    """Internal: this model cannot be used with this key (403 / 404 / decommissioned)."""


def get_openai_client(settings: Settings) -> OpenAI:
    """OpenAI SDK client targeting Groq."""
    return OpenAI(api_key=settings.groq_api_key, base_url=settings.base_url, timeout=90, max_retries=0)


def _retry_after(exc: Exception, default: float) -> float:
    """Seconds Groq asks us to wait (Retry-After header or 'try again in 6.5s' text), capped at 60."""
    try:
        hdr = exc.response.headers.get("retry-after")  # type: ignore[attr-defined]
        if hdr:
            return min(float(hdr) + 1.0, 60.0)
    except Exception:
        pass
    m = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)s", str(getattr(exc, "message", "") or exc), re.I)
    if m:
        return min(float(m.group(1) or 0) * 60 + float(m.group(2)) + 1.0, 60.0)
    return min(default, 60.0)


def describe_error(exc: Exception) -> str:
    """Short, safe description of an API error: HTTP status + the provider's own message."""
    status = getattr(exc, "status_code", None)
    msg = ""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            msg = str(err.get("message") or "")
            code = err.get("code")
            if code and code not in msg:
                msg = f"{msg} [{code}]" if msg else str(code)
    if not msg:
        msg = str(getattr(exc, "message", "") or exc)
    if "<html" in msg.lower() or "<!doctype" in msg.lower():
        msg = "blocked by a firewall/CDN (HTML page returned instead of an API response)"
    msg = re.sub(r"gsk_[A-Za-z0-9]+", "gsk_***", msg)  # never leak a key
    msg = " ".join(msg.split())[:350]
    return f"HTTP {status}: {msg}" if status else msg


class GroqChatLLM(BaseLLM):
    """CrewAI-compatible chat model backed by the OpenAI SDK + Groq."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(model=settings.model, temperature=settings.temperature)
        self._client = get_openai_client(settings)
        self._max_tokens = settings.max_output_tokens
        self._models = [settings.model] + [m for m in settings.fallback_models if m != settings.model]
        self._unavailable: dict[str, str] = {}
        self.active_model = settings.model

    # ------------------------------------------------------------------ CrewAI API
    def call(self, messages: Any, tools: Any = None, callbacks: Any = None,
             available_functions: Any = None, from_task: Any = None, from_agent: Any = None,
             **kwargs: Any) -> str:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        return self._complete(list(messages))

    # ------------------------------------------------------------------ internals
    def _complete(self, messages: list[dict]) -> str:
        """Try the primary model, then fall back to other models if access is denied."""
        for model in self._models:
            if model in self._unavailable:
                continue
            try:
                text = self._complete_with(model, messages)
            except _ModelUnavailable as exc:
                self._unavailable[model] = str(exc)
                logger.warning("Model %s unavailable (%s)", model, exc)
                continue
            if model != self.active_model:
                logger.warning("Using fallback model %s instead of %s", model, self.active_model)
                self.active_model = model
            return text
        tried = ", ".join(self._models)
        first = next(iter(self._unavailable.values()), "access denied")
        raise LLMCallError(f"Groq refused access to every model tried ({tried}). Groq said: {first}. {CONSOLE_HINT}")

    def _complete_with(self, model: str, messages: list[dict]) -> str:
        delay, use_reasoning = 10.0, "gpt-oss" in model
        last = "unknown error"
        for _ in range(6):
            try:
                extra = {"extra_body": {"reasoning_effort": "low"}} if use_reasoning else {}
                resp = self._client.chat.completions.create(
                    model=model, messages=messages, temperature=self.temperature,
                    max_tokens=self._max_tokens, **extra)
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    return content
                last = "empty response"
            except RateLimitError as exc:
                last = f"Groq rate limit reached ({describe_error(exc)})"
                wait = _retry_after(exc, delay)
                logger.warning("Rate limited; waiting %.0fs", wait)
                time.sleep(wait)
                delay *= 2
            except AuthenticationError as exc:
                raise LLMCallError(
                    f"Groq rejected the API key ({describe_error(exc)}). Create a new key at "
                    "https://console.groq.com/keys and paste it into Secrets as GROQ_API_KEY "
                    "(no quotes/spaces inside the key).") from exc
            except (PermissionDeniedError, NotFoundError) as exc:
                raise _ModelUnavailable(f"{model}: {describe_error(exc)}") from exc
            except BadRequestError as exc:
                desc = describe_error(exc)
                if "decommission" in desc.lower():
                    raise _ModelUnavailable(f"{model}: {desc}") from exc
                if use_reasoning:
                    use_reasoning = False  # retry without the optional parameter
                    continue
                raise LLMCallError(f"The model rejected the request ({desc}).") from exc
            except (APIConnectionError, APITimeoutError) as exc:
                last = "connection problem"
                logger.warning("LLM connection problem: %s", type(exc).__name__)
                time.sleep(3)
            except APIStatusError as exc:
                if getattr(exc, "status_code", None) == 413:
                    raise LLMCallError(
                        f"The request is too large for your Groq plan's per-minute token limit ({describe_error(exc)}). "
                        "Lower MAX_PAGES / MAX_OUTPUT_TOKENS in Secrets, or upgrade the Groq tier.") from exc
                raise LLMCallError(f"LLM API error ({type(exc).__name__}): {describe_error(exc)}") from exc
            except APIError as exc:
                raise LLMCallError(f"LLM API error ({type(exc).__name__}): {describe_error(exc)}") from exc
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


def check_connection(settings: Settings) -> tuple[str, str]:
    """Send a tiny test prompt. Returns (model_used, reply). Raises LLMCallError with details."""
    llm = build_llm(settings)
    reply = llm._complete([{"role": "user", "content": "Reply with the single word: ok"}])
    return llm.active_model, reply
