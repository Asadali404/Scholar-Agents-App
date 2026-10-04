"""Deadline parsing utilities. Never invents days, months or years."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

CLOSING_SOON_DAYS = 30

MONTHS: dict[str, int] = {n.lower(): i for i, n in enumerate(calendar.month_name) if n}
MONTHS.update({n.lower(): i for i, n in enumerate(calendar.month_abbr) if n})
MONTHS["sept"] = 9
_M = "|".join(sorted(MONTHS, key=len, reverse=True))
_ORD = r"(?:st|nd|rd|th)?"

P_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
P_MDY = re.compile(rf"\b({_M})\.?\s+(\d{{1,2}}){_ORD}\s*,?\s+(\d{{4}})\b", re.I)
P_DMY = re.compile(rf"\b(\d{{1,2}}){_ORD}\s+(?:of\s+)?({_M})\.?,?\s+(\d{{4}})\b", re.I)
P_NUM = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
P_MY = re.compile(rf"\b({_M})\.?,?\s+(\d{{4}})\b", re.I)

UNKNOWN_WORDS = {"", "unknown", "not verified", "n/a", "na", "none", "null",
                 "information unavailable", "not available", "tbd"}


@dataclass(frozen=True)
class ParsedDate:
    """A date found in text. ``kind`` is ``day`` or ``month``."""

    kind: str
    year: int
    month: int
    day: Optional[int] = None
    start: int = 0

    def to_date(self) -> Optional[date]:
        """Return a concrete date, or None when only month/year is known."""
        if self.kind != "day" or self.day is None:
            return None
        try:
            return date(self.year, self.month, self.day)
        except ValueError:
            return None


@dataclass(frozen=True)
class DeadlineInfo:
    """Result of interpreting a deadline string."""

    deadline: str
    iso: Optional[str]
    status: str  # OPEN | CLOSING_SOON | UNKNOWN | EXPIRED (EXPIRED is internal only)
    days_remaining: Optional[int]
    note: str = ""


def find_dates(text: str) -> list[ParsedDate]:
    """Find all unambiguous dates in ``text`` (ambiguous 03/04/2026 style are skipped)."""
    found: list[ParsedDate] = []
    taken: list[tuple[int, int]] = []

    def add(m: re.Match, kind: str, y: int, mo: int, d: Optional[int]) -> None:
        if not (2000 <= y <= 2100) or not (1 <= mo <= 12):
            return
        if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
            return
        if kind == "day":
            try:
                date(y, mo, d or 0)
            except ValueError:
                return
        taken.append((m.start(), m.end()))
        found.append(ParsedDate(kind, y, mo, d, m.start()))

    for m in P_ISO.finditer(text):
        add(m, "day", int(m[1]), int(m[2]), int(m[3]))
    for m in P_MDY.finditer(text):
        add(m, "day", int(m[3]), MONTHS[m[1].lower()], int(m[2]))
    for m in P_DMY.finditer(text):
        add(m, "day", int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    for m in P_NUM.finditer(text):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12 >= b or (a <= 12 and b <= 12 and a == b):
            add(m, "day", y, b, a)  # day-first
        elif b > 12 >= a:
            add(m, "day", y, a, b)  # month-first
    for m in P_MY.finditer(text):
        add(m, "month", int(m[2]), MONTHS[m[1].lower()], None)
    found.sort(key=lambda p: p.start)
    return found


def _fmt(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def classify(dt: date, today: date) -> tuple[str, int]:
    """Return (status, days_remaining) for a concrete date."""
    days = (dt - today).days
    if days < 0:
        return "EXPIRED", days
    return ("CLOSING_SOON" if days <= CLOSING_SOON_DAYS else "OPEN"), days


def parse_deadline(raw: Optional[str], today: Optional[date] = None) -> DeadlineInfo:
    """Interpret a deadline string. Falls back to UNKNOWN when not confident."""
    today = today or date.today()
    raw = (raw or "").strip()
    unknown = DeadlineInfo("Not verified", None, "UNKNOWN", None,
                           "Deadline could not be independently verified.")
    if raw.lower() in UNKNOWN_WORDS:
        return unknown
    if re.search(r"\brolling\b", raw, re.I):
        return DeadlineInfo("Rolling", None, "OPEN", None, "Rolling admissions.")
    dates = find_dates(raw)
    if not dates:
        return unknown
    day_dates = [d for d in dates if d.kind == "day"]
    if day_dates:
        dt = day_dates[-1].to_date()  # for ranges, the later date is the closing date
        if dt is None:
            return unknown
        status, days = classify(dt, today)
        if status == "EXPIRED":
            return DeadlineInfo(_fmt(dt), dt.isoformat(), "EXPIRED", days, "Deadline has passed.")
        return DeadlineInfo(_fmt(dt), dt.isoformat(), status, days)
    d = dates[0]
    last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    label = f"{calendar.month_name[d.month]} {d.year}"
    if last < today:
        return DeadlineInfo(label, None, "EXPIRED", None, "Deadline month has passed.")
    return DeadlineInfo(label, None, "UNKNOWN", None,
                        "Only the month is known; the exact day was not verified.")


def refresh_status(iso: Optional[str], deadline: str, status: str,
                   today: Optional[date] = None) -> tuple[str, Optional[int]]:
    """Recompute status/days from a stored ISO date (used at display time)."""
    today = today or date.today()
    if iso:
        try:
            return classify(date.fromisoformat(iso), today)
        except ValueError:
            return "UNKNOWN", None
    if (deadline or "").strip().lower() == "rolling":
        return "OPEN", None
    return "UNKNOWN", None
