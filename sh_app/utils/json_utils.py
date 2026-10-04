"""Robust JSON extraction from LLM output."""
from __future__ import annotations

import json
import re
from typing import Any


def _balanced(text: str, start: int) -> str:
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start: i + 1]
    raise ValueError("Unbalanced JSON in model output")


def _cleanup(s: str) -> str:
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    return re.sub(r",\s*([}\]])", r"\1", s)  # trailing commas


def extract_json(text: str) -> Any:
    """Extract the first JSON object/array from ``text`` or raise ``ValueError``."""
    if not text or not text.strip():
        raise ValueError("Empty model output")
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    candidates = [m.start() for m in re.finditer(r"[\[{]", cleaned)]
    last_error: Exception | None = None
    for start in candidates[:6]:
        try:
            chunk = _balanced(cleaned, start)
        except ValueError as exc:
            last_error = exc
            continue
        for attempt in (chunk, _cleanup(chunk)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError as exc:
                last_error = exc
    raise ValueError(f"No valid JSON found in model output ({last_error})")
