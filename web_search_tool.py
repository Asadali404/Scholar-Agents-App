"""Free DuckDuckGo search via the ``ddgs`` package (no API key, no paid service)."""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_CACHE: dict[tuple[str, int], tuple[float, list[dict]]] = {}
CACHE_TTL_SECONDS = 1800


def web_search(query: str, max_results: int = 8) -> list[dict]:
    """Return ``[{"title", "url", "snippet"}]``. Returns ``[]`` on failure (never raises)."""
    key = (query.strip().lower(), max_results)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("ddgs is not installed")
        return []
    raw: list[dict] = []
    for attempt in range(2):
        try:
            raw = list(DDGS().text(query, max_results=max_results) or [])
            break
        except Exception as exc:  # network, rate limit, parser changes
            logger.warning("Search failed (attempt %d): %s", attempt + 1, type(exc).__name__)
            time.sleep(1.5)
    results = []
    for r in raw:
        url = r.get("href") or r.get("url") or ""
        if url.startswith(("http://", "https://")):
            results.append({"title": r.get("title", ""), "url": url, "snippet": r.get("body", "")})
    if results:
        _CACHE[key] = (time.time(), results)
    return results
