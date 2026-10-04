"""Duplicate removal based on normalised name, university, country and official URL."""
from __future__ import annotations

from sh_app.core.models import Scholarship
from sh_app.utils.text import normalize_name, normalize_url

_FIELDS = ("university", "country", "degree_level", "field", "funding_type", "funding_details",
           "eligibility", "application_requirements", "official_url", "deadline_note")


def _keys(s: Scholarship) -> list[str]:
    name = normalize_name(s.scholarship_name)
    keys = [f"n:{name}|u:{normalize_name(s.university)}" if s.university else f"n:{name}|c:{normalize_name(s.country)}"]
    if s.official_url:
        keys.append("url:" + normalize_url(s.official_url))
    return keys


def _score(s: Scholarship) -> tuple:
    filled = sum(1 for f in _FIELDS if getattr(s, f) not in ("", None, "Unknown"))
    return (s.verified, s.source_tier == "official", s.deadline_status != "UNKNOWN", filled)


def _merge(a: Scholarship, b: Scholarship) -> Scholarship:
    best, other = (a, b) if _score(a) >= _score(b) else (b, a)
    for f in _FIELDS:
        if getattr(best, f) in ("", None, "Unknown") and getattr(other, f) not in ("", None):
            setattr(best, f, getattr(other, f))
    return best


def dedupe(items: list[Scholarship]) -> list[Scholarship]:
    """Merge duplicates, keeping the best-verified record and filling gaps from the others."""
    index: dict[str, int] = {}
    result: list[Scholarship] = []
    for s in items:
        keys = _keys(s)
        pos = next((index[k] for k in keys if k in index), None)
        if pos is None:
            result.append(s)
            pos = len(result) - 1
        else:
            result[pos] = _merge(result[pos], s)
        for k in keys + _keys(result[pos]):
            index[k] = pos
    return result
