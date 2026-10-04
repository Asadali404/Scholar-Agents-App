"""Deterministic (non-LLM) validation of scholarship records against fetched pages."""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

from sh_app.core.models import Scholarship
from sh_app.tools.deadline_checker import check_deadline, find_deadline_candidates
from sh_app.utils.dates import parse_deadline
from sh_app.utils.text import get_domain, name_tokens, normalize_url

logger = logging.getLogger(__name__)

_OFFICIAL_TLD = re.compile(
    r"(\.edu(\.[a-z]{2})?|\.ac\.[a-z]{2}|\.gov(\.[a-z]{2})?|\.go\.[a-z]{2}|\.gouv\.[a-z]{2}|"
    r"\.gob\.[a-z]{2}|\.bund\.de|\.europa\.eu|\.mil)$")
_OFFICIAL_PATTERNS = re.compile(r"(^|\.)((uni|tu|fh|hs)-[a-z0-9-]+\.de|univ-[a-z0-9-]+\.fr)$")
_OFFICIAL_HOSTS = {
    "daad.de", "chevening.org", "fulbright.org", "fulbrightprogram.org", "gatescambridge.org",
    "ethz.ch", "epfl.ch", "kth.se", "lu.se", "uu.se", "su.se", "chalmers.se", "liu.se",
    "helsinki.fi", "aalto.fi", "utu.fi", "oulu.fi", "tuni.fi", "studyinfinland.fi",
    "studyinsweden.se", "si.se", "studyinkorea.go.kr", "csc.edu.cn", "campuschina.org",
    "vanier.gc.ca", "educanada.gc.ca", "jasso.go.jp", "jsps.go.jp", "mext.go.jp",
    "erasmus-plus.ec.europa.eu",
}
_UNRELIABLE = {
    "quora.com", "reddit.com", "facebook.com", "twitter.com", "x.com", "youtube.com", "pinterest.com",
    "instagram.com", "tiktok.com", "linkedin.com", "medium.com", "scribd.com", "slideshare.net",
    "blogspot.com", "wordpress.com", "t.me", "telegram.org", "whatsapp.com",
}
_CLOSED = re.compile(
    r"(applications?|admissions?)\s+(?:are\s+|is\s+|have\s+been\s+)?(?:now\s+)?closed|"
    r"deadline\s+(?:has\s+)?passed", re.I)


def classify_source(url: str) -> str:
    """Return ``official`` | ``secondary`` | ``unreliable`` from the host name."""
    host = get_domain(url)
    if not host:
        return "unreliable"
    if any(host == d or host.endswith("." + d) for d in _UNRELIABLE):
        return "unreliable"
    if (_OFFICIAL_TLD.search(host) or _OFFICIAL_PATTERNS.search(host)
            or any(host == d or host.endswith("." + d) for d in _OFFICIAL_HOSTS)):
        return "official"
    return "secondary"


def name_in_text(name: str, text: str) -> bool:
    """True when most significant tokens of ``name`` occur on the page."""
    tokens = name_tokens(name)
    if not tokens:
        return False
    low = text.lower()
    hits = sum(1 for t in tokens if t in low)
    return hits / len(tokens) >= 0.6


def validate_scholarship_ex(s: Scholarship, page: dict,
                            today: Optional[date] = None) -> tuple[Optional[Scholarship], str]:
    """Return ``(record, "")`` or ``(None, reason)`` explaining why the record was discarded."""
    today = today or date.today()
    text = page["text"]
    tier = classify_source(page["url"])
    if tier == "unreliable" or not s.scholarship_name.strip():
        return None, "unreliable source or empty name"
    if not name_in_text(s.scholarship_name, text + " " + page.get("title", "")):
        return None, "name not found on page"  # likely hallucinated

    raw = s.deadline
    note = ""
    if parse_deadline(raw, today).status == "UNKNOWN" and parse_deadline(raw, today).deadline == "Not verified":
        cands = find_deadline_candidates(text)
        futures = [d for d in cands if d >= today]
        if len(futures) == 1:
            raw = futures[0].isoformat()
        elif len(cands) > 1:
            note = "Multiple deadline dates found on the source page; none could be assigned confidently."
    info = check_deadline(raw, text, today)
    if info.status == "EXPIRED":
        return None, "deadline already passed"
    if info.status == "UNKNOWN" and _CLOSED.search(text):
        return None, "page says applications are closed"
    # NOTE: records with an unconfirmed deadline are KEPT (clearly labelled "Not verified",
    # sorted last, never counted as verified). Only confirmed-expired records are removed.

    out = s.model_copy(deep=True)
    out.source_url = s.source_url or page["url"]
    out.source_tier = tier
    out.deadline = info.deadline
    out.deadline_iso = info.iso
    out.deadline_status = info.status
    out.days_remaining = info.days_remaining
    out.deadline_note = " ".join(x for x in (info.note, note) if x)

    allowed = {normalize_url(u) for u in page.get("links", [])} | {normalize_url(page["url"])}
    cand = out.official_url
    if cand and normalize_url(cand) in allowed and classify_source(cand) == "official":
        out.official_url = cand
    elif tier == "official":
        out.official_url = page["url"]
    else:
        out.official_url = None
    out.verified = tier == "official" and info.status != "UNKNOWN"
    if out.verified:
        out.verification_notes = "Details and deadline found on an official page."
    elif tier == "official":
        out.verification_notes = "Found on an official page, but the deadline could not be confirmed."
    else:
        out.verification_notes = "Found on a secondary source only; confirm on the official website."
    return out, ""


def validate_scholarship(s: Scholarship, page: dict, today: Optional[date] = None) -> Optional[Scholarship]:
    """Return the verified/annotated record, or None if it must be discarded."""
    return validate_scholarship_ex(s, page, today)[0]
