"""Deadline verification against the current date and the source page text."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from sh_app.utils.dates import (DeadlineInfo, find_dates, parse_deadline, refresh_status)

__all__ = ["check_deadline", "find_deadline_candidates", "refresh_status"]

_KEYWORDS = re.compile(
    r"application\s+deadline|deadline|apply\s+by|applications?\s+(?:close|due)|closing\s+date|"
    r"due\s+date|submit(?:ted)?\s+by", re.I)

_UNVERIFIED = "Deadline could not be independently verified."


def find_deadline_candidates(text: str) -> list[date]:
    """Concrete dates that appear shortly after deadline-style keywords on the page."""
    found: set[date] = set()
    for m in _KEYWORDS.finditer(text):
        for p in find_dates(text[m.end(): m.end() + 160]):
            d = p.to_date()
            if d:
                found.add(d)
    return sorted(found)


def check_deadline(raw: Optional[str], page_text: str, today: Optional[date] = None) -> DeadlineInfo:
    """Parse ``raw`` and confirm it really occurs on the source page.

    Anything that cannot be confirmed becomes UNKNOWN. Dates in the past are EXPIRED.
    """
    info = parse_deadline(raw, today)
    if info.status == "EXPIRED":
        return info
    unknown = DeadlineInfo("Not verified", None, "UNKNOWN", None, _UNVERIFIED)
    if info.deadline == "Rolling":
        if re.search(r"\brolling\b", page_text, re.I):
            return info
        return DeadlineInfo("Not verified", None, "UNKNOWN", None, "Rolling basis not confirmed on the source page.")
    page_dates = find_dates(page_text)
    if info.iso:
        concrete = {p.to_date() for p in page_dates if p.kind == "day"}
        return info if date.fromisoformat(info.iso) in concrete else unknown
    if info.deadline not in ("Not verified", ""):  # month-only deadline
        wanted = find_dates(info.deadline)
        if wanted and any(p.year == wanted[0].year and p.month == wanted[0].month for p in page_dates):
            return info
    return unknown
