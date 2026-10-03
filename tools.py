import json
import time
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

CACHE = Path("data/search_cache.json")
MAX_SEARCHES = 5

def _load_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_cache(data):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def ddg_search(queries, max_queries=MAX_SEARCHES, max_results=5):
    queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:max_queries]
    cache = _load_cache()
    output = []
    seen = set()

    for q in queries:
        if q in cache:
            rows = cache[q]
        else:
            try:
                rows = []
                with DDGS() as ddgs:
                    for r in ddgs.text(q, max_results=max_results):
                        rows.append({
                            "title": r.get("title", ""),
                            "url": r.get("href", "") or r.get("url", ""),
                            "snippet": r.get("body", "") or r.get("snippet", "")
                        })
                cache[q] = rows
                _save_cache(cache)
                time.sleep(0.5)
            except Exception:
                rows = cache.get(q, [])

        for r in rows:
            url = r.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            output.append({
                "query": q,
                "title": r.get("title", ""),
                "url": url,
                "snippet": r.get("snippet", "")
            })

    return output

def fetch_page(url, timeout=8):
    try:
        host = urlparse(url).netloc.lower()
        if not host:
            return ""
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "ScholarHunterAgents/1.0"}
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.stripped_strings)
        return text[:12000]
    except Exception:
        return ""
