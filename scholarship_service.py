"""Search → extract → verify → match → plan. Web access/validation stays outside the LLM layer."""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sh_app.core.models import (ApplicationPlan, ApplicationStrategy, CandidateProfile, CVAssessment,
                         ExtractionResult, MatchResult, PlanResult, Scholarship, ScholarshipMatch,
                         SearchPreferences, VerificationResult)
from sh_app.services.cv_service import profile_json
from sh_app.tasks.improvement_tasks import build_overall_strategy_task, build_plan_task
from sh_app.tasks.matching_tasks import build_matching_task
from sh_app.tasks.scholarship_tasks import build_extraction_task
from sh_app.tasks.verification_tasks import build_verification_task
from sh_app.tools.deduplication import dedupe
from sh_app.tools.scholarship_validator import classify_source, name_in_text, validate_scholarship_ex
from sh_app.tools.web_search_tool import web_search
from sh_app.tools.webpage_reader import apply_links, build_excerpt, evidence_lines, fetch_pages
from sh_app.utils.text import get_domain, is_valid_url, normalize_url, truncate

logger = logging.getLogger(__name__)

LEVEL_WORDS = {"MS": "master's", "PhD": "PhD", "Postdoctoral": "postdoctoral"}
COUNTRY_ALIASES = {
    "usa": {"usa", "united states", "u.s.", "us", "america"},
    "uk": {"uk", "united kingdom", "england", "scotland", "wales", "britain"},
    "south korea": {"south korea", "korea", "republic of korea"},
}
BATCH_PAGES, BATCH_MATCH = 3, 5


@dataclass
class Discovery:
    """Candidate scholarships plus the pages they came from."""

    candidates: list[Scholarship] = field(default_factory=list)
    pages: dict[str, dict] = field(default_factory=dict)


def prefs_summary(prefs: SearchPreferences) -> str:
    """One-line description of the search request."""
    where = "any country" if prefs.any_country else ", ".join(prefs.countries)
    return (f"{LEVEL_WORDS.get(prefs.degree_level, prefs.degree_level)} level, field '{prefs.department}', "
            f"country: {where}, funding: {prefs.funding_type}")


def build_queries(prefs: SearchPreferences, today: date, limit: int = 10) -> list[str]:
    """Several query variations per country, interleaved so every country gets coverage."""
    yr = str(today.year + 1 if today.month >= 7 else today.year)
    lvl, dept = LEVEL_WORDS.get(prefs.degree_level, prefs.degree_level), prefs.department.strip()
    fund = {"Fully Funded": "fully funded", "Partially Funded": "partially funded"}.get(prefs.funding_type, "funded")
    targets = [""] if prefs.any_country else prefs.countries
    templates = [
        "{c} {lvl} {dept} scholarship {yr}",
        "{c} {fund} {lvl} {dept} scholarship {yr} deadline",
        "{c} university {lvl} {dept} funding {yr}",
        "{c} {dept} {fund} {lvl} program",
        "{c} {lvl} scholarship application deadline {yr}",
        "{c} government scholarship international students {lvl} {yr}",
    ]
    queries: list[str] = []
    for t in templates:
        for c in targets:
            q = " ".join(t.format(c=c, lvl=lvl, dept=dept, fund=fund, yr=yr).split())
            if q not in queries:
                queries.append(q)
    queries.append(f"{dept} {lvl} {fund} scholarship {yr}")
    return queries[:limit]


def _resolve_source(s: Scholarship, pages: dict[str, dict]) -> Optional[str]:
    """Map the URL the LLM reported back to a page we really fetched (tolerant of / www. # differences)."""
    if not pages:
        return None
    if s.source_url in pages:
        return s.source_url
    wanted = normalize_url(s.source_url or "")
    by_norm = {normalize_url(u): u for u in pages}
    if wanted in by_norm:
        return by_norm[wanted]
    host = get_domain(s.source_url or "")
    same_host = [u for u in pages if host and get_domain(u) == host]
    if len(same_host) == 1:
        return same_host[0]
    # last resort: the single page whose text actually contains the scholarship name
    named = [u for u, pg in pages.items() if name_in_text(s.scholarship_name, pg["text"] + " " + pg.get("title", ""))]
    return named[0] if len(named) == 1 else None


def _err(exc: Exception) -> str:
    """Safe, short reason for the run log (our own error classes never contain secrets)."""
    return str(exc)[:220] if exc.__class__.__name__ in {"StageError", "LLMCallError"} else type(exc).__name__


def _country_ok(s: Scholarship, prefs: SearchPreferences) -> bool:
    if prefs.any_country or not s.country:
        return True
    have = s.country.lower()
    for c in prefs.countries:
        names = COUNTRY_ALIASES.get(c.lower(), {c.lower()})
        if any(n in have or have in n for n in names):
            return True
    return False


def discover_scholarships(crew, profile: CandidateProfile, prefs: SearchPreferences,
                          warnings: list[str]) -> Discovery:
    """Free web search → fetch pages → Researcher extracts records from the page text."""
    st = crew.settings
    today = date.today()
    seen: set[str] = set()
    hits: list[dict] = []
    queries = build_queries(prefs, today, st.max_queries)
    raw_results = 0
    for q in queries:
        found = web_search(q, st.results_per_query)
        raw_results += len(found)
        for r in found:
            key = normalize_url(r["url"])
            tier = classify_source(r["url"])
            if key in seen or tier == "unreliable" or r["url"].lower().endswith((".pdf", ".doc", ".docx")):
                continue
            seen.add(key)
            hits.append({**r, "tier": tier})
        time.sleep(0.5)
    crew.diag.append(f"Search: {len(queries)} queries → {raw_results} raw results → {len(hits)} usable links.")
    if not hits:
        warnings.append("Web search returned no usable results (DuckDuckGo may be blocking or rate-limiting this server). "
                        "Try again in a few minutes.")
        return Discovery()

    hits.sort(key=lambda h: 0 if h["tier"] == "official" else 1)
    per_host: dict[str, int] = {}
    urls: list[str] = []
    for h in hits:
        host = get_domain(h["url"])
        if per_host.get(host, 0) < 2 and is_valid_url(h["url"]):
            per_host[host] = per_host.get(host, 0) + 1
            urls.append(h["url"])
        if len(urls) >= st.max_pages:
            break
    pages = fetch_pages(urls)
    crew.diag.append(f"Pages: {len(urls)} requested → {len(pages)} opened with readable text.")
    if not pages:
        warnings.append("None of the search results could be opened (some sites block automated requests).")
        return Discovery()

    summary = prefs_summary(prefs)
    ordered = list(pages.items())
    candidates: list[Scholarship] = []
    extracted = bad_url = batches_failed = 0
    last_error = ""
    for i in range(0, len(ordered), BATCH_PAGES):
        batch = dict(ordered[i:i + BATCH_PAGES])
        blocks = []
        for url, page in batch.items():
            links = "\n".join(apply_links(page)) or "(none)"
            blocks.append(f"[PAGE]\nURL: {url}\nTITLE: {truncate(page['title'], 150)}\n"
                          f"LINKS:\n{links}\nTEXT:\n{build_excerpt(page)}\n[/PAGE]")
        task = build_extraction_task(crew.search_agent, "\n\n".join(blocks), summary, today)
        try:
            result = crew.run_stage(crew.search_agent, task, ExtractionResult)
        except Exception as exc:
            batches_failed += 1
            last_error = _err(exc)
            logger.warning("Extraction batch failed: %s", type(exc).__name__)
            continue
        for sch in result.scholarships:
            extracted += 1
            src = _resolve_source(sch, batch) or _resolve_source(sch, pages)
            if src is None:
                bad_url += 1
                continue
            sch.source_url = src  # always a page we really fetched
            candidates.append(sch)
    nb = (len(ordered) + BATCH_PAGES - 1) // BATCH_PAGES
    crew.diag.append(f"AI extraction: {nb - batches_failed}/{nb} batches succeeded → {extracted} scholarships "
                     f"found in pages ({bad_url} dropped: source page could not be matched).")
    if batches_failed:
        warnings.append(f"{batches_failed} of {nb} page batches could not be analysed by the AI "
                        f"(last error: {last_error or 'unknown'}). This is usually a Groq rate limit — wait a minute and retry.")
    before = len(candidates)
    candidates = [s for s in candidates if _country_ok(s, prefs)]
    if prefs.funding_type == "Fully Funded":
        candidates = [s for s in candidates if s.funding_type != "Partially Funded"]
    crew.diag.append(f"Filters: {before} → {len(candidates)} after country/funding checks.")
    return Discovery(candidates=candidates, pages=pages)


def _sort_key(s: Scholarship) -> tuple:
    days = s.days_remaining if s.days_remaining is not None else (99998 if s.deadline == "Rolling" else 99999)
    return (days, not s.verified)


def verify_scholarships(crew, discovery: Discovery, prefs: SearchPreferences,
                        warnings: list[str]) -> list[Scholarship]:
    """Code gates (date, URL, name-on-page) first, then an LLM consistency check that can only downgrade."""
    today = date.today()
    kept: list[Scholarship] = []
    dropped: Counter = Counter()
    for s in discovery.candidates:
        try:
            out, why = validate_scholarship_ex(s, discovery.pages[s.source_url or ""], today)
        except Exception as exc:  # one bad record must never break the run
            logger.warning("Validation error: %s", type(exc).__name__)
            dropped["validation error"] += 1
            continue
        if out:
            kept.append(out)
        else:
            dropped[why] += 1
    kept = dedupe(kept)
    kept.sort(key=_sort_key)
    kept = kept[: crew.settings.max_results]
    reasons = "; ".join(f"{n}× {w}" for w, n in dropped.items()) or "none"
    crew.diag.append(f"Validation: {len(discovery.candidates)} candidates → {len(kept)} kept (dropped: {reasons}).")
    for i, s in enumerate(kept, 1):
        s.id = f"s{i}"
    if not kept:
        return []

    blocks = []
    for s in kept:
        page = discovery.pages[s.source_url or ""]
        blocks.append(
            f"[RECORD {s.id}]\nCLAIMS: name={s.scholarship_name}; university={s.university}; country={s.country}; "
            f"degree={s.degree_level}; field={s.field}; funding={s.funding_type}; deadline={s.deadline}\n"
            f"EVIDENCE:\n{evidence_lines(page)}\n[/RECORD]")
    try:
        result = crew.run_stage(crew.verify_agent,
                                build_verification_task(crew.verify_agent, "\n\n".join(blocks), prefs_summary(prefs)),
                                VerificationResult)
        flags = {c.id: c for c in result.checks}
    except Exception as exc:
        logger.warning("Verifier LLM check failed: %s", type(exc).__name__)
        warnings.append("The AI consistency check was unavailable; results passed only the automatic date/source checks.")
        flags = {}
    final: list[Scholarship] = []
    llm_dropped = 0
    for s in kept:
        chk = flags.get(s.id)
        if chk and not chk.consistent:
            if s.source_tier != "official":
                llm_dropped += 1
                continue
            s.verified = False
            s.verification_notes = "Evidence inconsistent: " + (chk.notes or "details could not be confirmed.")
        final.append(s)
    for i, s in enumerate(final, 1):
        s.id = f"s{i}"
    crew.diag.append(f"AI consistency check: {len(kept)} → {len(final)} ({llm_dropped} secondary-source records rejected).")
    return final


def _compact(s: Scholarship) -> dict:
    return {"id": s.id, "name": s.scholarship_name, "university": s.university, "country": s.country,
            "degree": s.degree_level, "field": s.field, "funding": s.funding_type,
            "deadline": s.deadline, "eligibility": truncate(s.eligibility, 500),
            "requirements": truncate(s.application_requirements, 350)}


def match_profile(crew, profile: CandidateProfile, scholarships: list[Scholarship],
                  warnings: list[str]) -> dict[str, ScholarshipMatch]:
    """Matcher in small batches; a failed batch only loses its own matches."""
    out: dict[str, ScholarshipMatch] = {}
    pj = profile_json(profile)
    for i in range(0, len(scholarships), BATCH_MATCH):
        chunk = scholarships[i:i + BATCH_MATCH]
        task = build_matching_task(crew.match_agent, pj, json.dumps([_compact(s) for s in chunk], ensure_ascii=False))
        try:
            for m in crew.run_stage(crew.match_agent, task, MatchResult).matches:
                out[m.scholarship_id] = m
        except Exception as exc:
            logger.warning("Matching batch failed: %s", type(exc).__name__)
            warnings.append("Profile matching failed for some scholarships; they are shown without an assessment.")
    return out


def build_strategy(crew, profile: CandidateProfile, scholarships: list[Scholarship], assessment: CVAssessment,
                   warnings: list[str]) -> tuple[dict[str, ApplicationPlan], ApplicationStrategy]:
    """Per-scholarship plans (batched) plus one overall strategy/roadmap."""
    today = date.today()
    plans: dict[str, ApplicationPlan] = {}
    pj = profile_json(profile)
    for i in range(0, len(scholarships), 4):
        chunk = scholarships[i:i + 4]
        task = build_plan_task(crew.strategy_agent, pj, json.dumps([_compact(s) for s in chunk], ensure_ascii=False), today)
        try:
            for p in crew.run_stage(crew.strategy_agent, task, PlanResult).plans:
                plans[p.scholarship_id] = p
        except Exception as exc:
            logger.warning("Plan batch failed: %s", type(exc).__name__)
            warnings.append("Application plans could not be generated for some scholarships.")
    summary = ("SCHOLARSHIPS (verified, with deadlines):\n" + ("\n".join(
        f"- {s.scholarship_name} ({s.country}) deadline: {s.deadline}" for s in scholarships) or "(none)") +
        "\nCV GAPS:\n" + "\n".join(f"- {g}" for g in assessment.gaps[:8]))
    try:
        strategy = crew.run_stage(crew.strategy_agent,
                                  build_overall_strategy_task(crew.strategy_agent, summary, today),
                                  ApplicationStrategy)
    except Exception as exc:
        logger.warning("Overall strategy failed: %s", type(exc).__name__)
        warnings.append("The overall application strategy could not be generated; a default roadmap is shown.")
        strategy = ApplicationStrategy()
    return plans, strategy
