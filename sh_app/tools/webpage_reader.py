"""Fetch public web pages and extract text/links for verification."""
from __future__ import annotations

import ipaddress
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from sh_app.utils.text import clean_whitespace, get_domain, is_valid_url, normalize_url, truncate

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ScholarHunter/1.0; research assistant)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "en",
}
MAX_BYTES = 1_500_000
CACHE_TTL_SECONDS = 3600
_CACHE: dict[str, tuple[float, Optional[dict]]] = {}

KEYWORDS = re.compile(
    r"deadline|apply by|closing date|due date|eligib|funding|funded|tuition|stipend|scholarship|"
    r"master|ph\.?d|postdoc|rolling|applications? (?:open|close)", re.I)
LINK_HINT = re.compile(r"appl|scholar|admission|funding|fellowship|program", re.I)


def _safe_host(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host in {"localhost", ""} or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return True


def fetch_page(url: str, timeout: int = 12) -> Optional[dict]:
    """Return ``{"url","title","text","links"}`` or None if unavailable/blocked/non-HTML."""
    if not is_valid_url(url) or not _safe_host(url):
        return None
    key = normalize_url(url)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    page: Optional[dict] = None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True, allow_redirects=True)
        ctype = resp.headers.get("Content-Type", "").lower()
        if resp.status_code < 400 and (not ctype or "html" in ctype or "text" in ctype):
            chunks, size = [], 0
            for chunk in resp.iter_content(65536):
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    break
            html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
            page = _parse(resp.url, html)
        else:
            logger.info("Skipped page (status %s, type %s)", resp.status_code, ctype[:30])
    except requests.RequestException as exc:
        logger.info("Page unavailable: %s", type(exc).__name__)
    _CACHE[key] = (time.time(), page)
    return page


def _parse(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"].strip())
        if href.startswith(("http://", "https://")) and href not in seen:
            seen.add(href)
            links.append(href)
    for tag in soup(["script", "style", "noscript", "svg", "form", "iframe"]):
        tag.decompose()
    title = clean_whitespace(soup.title.get_text(" ")) if soup.title else ""
    return {"url": url, "title": title, "text": clean_whitespace(soup.get_text("\n")), "links": links[:400]}


def fetch_pages(urls: list[str], workers: int = 4) -> dict[str, dict]:
    """Fetch several pages concurrently. Returns ``{final_or_requested_url: page}``."""
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for url, page in zip(urls, pool.map(fetch_page, urls)):
            if page and len(page["text"]) > 200:
                out[url] = page
    return out


def build_excerpt(page: dict, max_chars: int = 3000) -> str:
    """Head of the page plus keyword-bearing lines (deadlines are often deep in the page)."""
    text = page["text"]
    head = truncate(text, 1200)
    picked, used = [], len(head)
    for line in text[1200:].split("\n"):
        line = line.strip()
        if 15 < len(line) < 400 and KEYWORDS.search(line) and line not in picked:
            if used + len(line) > max_chars:
                break
            picked.append(line)
            used += len(line)
    return head + ("\n...\n" + "\n".join(picked) if picked else "")


def evidence_lines(page: dict, max_chars: int = 700) -> str:
    """Short evidence snippet (deadline/eligibility/funding lines) for the verifier."""
    out, used = [], 0
    for line in page["text"].split("\n"):
        line = line.strip()
        if 15 < len(line) < 300 and KEYWORDS.search(line):
            if used + len(line) > max_chars:
                break
            out.append(line)
            used += len(line)
    return "\n".join(out)


def apply_links(page: dict, limit: int = 8) -> list[str]:
    """Links on the page that look like application/scholarship pages (real URLs only)."""
    dom = get_domain(page["url"])
    scored = [(0 if get_domain(u) == dom else 1, u) for u in page["links"] if LINK_HINT.search(u)]
    return [u for _, u in sorted(scored)[:limit]]
