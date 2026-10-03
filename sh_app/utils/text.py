"""Text and URL helpers."""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Optional
from urllib.parse import urlparse, urlunparse

STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "in", "at", "to", "program", "programme",
    "scholarship", "scholarships", "fellowship", "award", "funded", "fully", "partially",
    "international", "students", "student", "masters", "master", "msc", "ms", "phd", "grant",
}


def clean_whitespace(text: str) -> str:
    """Collapse runs of spaces and blank lines."""
    text = re.sub(r"[ \t\r\f\v\u00a0]+", " ", text or "")
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def truncate(text: str, limit: int) -> str:
    """Truncate text to ``limit`` characters."""
    text = text or ""
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def name_tokens(name: str) -> list[str]:
    """Normalised, stop-word-free tokens of a name."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", ascii_name.lower())
    return [t for t in tokens if t not in STOPWORDS and not re.fullmatch(r"(19|20)\d\d", t)]


def normalize_name(name: str) -> str:
    """Canonical form used for duplicate detection."""
    return " ".join(name_tokens(name))


def esc(value: object) -> str:
    """HTML-escape any value (all web/LLM text must pass through this before HTML)."""
    return html.escape(str(value or ""), quote=True)


def is_valid_url(url: Optional[str]) -> bool:
    """True for plain http(s) URLs with a host and no whitespace."""
    if not url or not isinstance(url, str) or re.search(r"\s", url):
        return False
    p = urlparse(url)
    return p.scheme in {"http", "https"} and bool(p.netloc) and "." in p.netloc


def normalize_url(url: str) -> str:
    """Lower-case host, drop fragment and trailing slash."""
    p = urlparse((url or "").strip())
    path = p.path.rstrip("/")
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))


def get_domain(url: str) -> str:
    """Host name without ``www.``."""
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host
