"""Report assembly (deterministic), filtering, metrics and JSON export."""
from __future__ import annotations

import json
import logging
from typing import Optional

from sh_app.core.models import (ApplicationPlan, ApplicationStrategy, CandidateProfile, CVAssessment,
                         ReportSummary, ScholarHunterReport, Scholarship, ScholarshipEntry,
                         ScholarshipMatch, SearchPreferences)
from sh_app.tasks.report_tasks import build_report_task
from sh_app.tools.deadline_checker import refresh_status

logger = logging.getLogger(__name__)
MATCH_RANK = {"Strong Match": 0, "Potential Match": 1, "Needs Improvement": 2, "Insufficient Information": 3}


def refreshed(s: Scholarship) -> Scholarship:
    """Copy with deadline status/days recomputed against *today* (never trust stored status)."""
    out = s.model_copy()
    out.deadline_status, out.days_remaining = refresh_status(s.deadline_iso, s.deadline, s.deadline_status)
    return out


def sort_entries(entries: list[ScholarshipEntry]) -> list[ScholarshipEntry]:
    """Deadline proximity → verification → match category (display order only)."""
    def key(e: ScholarshipEntry):
        s = refreshed(e.scholarship)
        days = s.days_remaining if s.days_remaining is not None else (99998 if s.deadline == "Rolling" else 99999)
        return (days, not s.verified, MATCH_RANK.get(e.match.category if e.match else "Insufficient Information", 3))
    return sorted(entries, key=key)


def build_report(crew, profile: CandidateProfile, prefs: SearchPreferences, scholarships: list[Scholarship],
                 matches: dict[str, ScholarshipMatch], plans: dict[str, ApplicationPlan],
                 assessment: CVAssessment, strategy: ApplicationStrategy,
                 warnings: list[str]) -> ScholarHunterReport:
    """Combine all agent outputs. URLs/deadlines come only from validated records."""
    entries = sort_entries([ScholarshipEntry(scholarship=s, match=matches.get(s.id), plan=plans.get(s.id))
                            for s in scholarships])
    sources = sorted({u for s in scholarships for u in (s.source_url, s.official_url) if u})
    facts = (f"Verified open opportunities: {len(entries)}; fully funded: "
             f"{sum(e.scholarship.funding_type == 'Fully Funded' for e in entries)}; strong matches: "
             f"{sum(bool(e.match and e.match.category == 'Strong Match') for e in entries)}.\n"
             f"Deadlines: {', '.join(e.scholarship.deadline for e in entries[:5]) or 'none'}.\n"
             f"Top strengths: {'; '.join(assessment.strengths[:3])}\nTop gaps: {'; '.join(assessment.gaps[:3])}")
    try:
        summary = crew.run_stage(crew.report_agent, build_report_task(crew.report_agent, facts), ReportSummary).executive_summary
    except Exception as exc:
        logger.warning("Report summary failed: %s", type(exc).__name__)
        summary = ""
    return ScholarHunterReport(candidate=profile, search_preferences=prefs, scholarships=entries,
                               profile_assessment=assessment, application_strategy=strategy,
                               sources=sources, executive_summary=summary, warnings=list(dict.fromkeys(warnings)))


def compute_metrics(entries: list[ScholarshipEntry]) -> dict[str, int]:
    """Dashboard counters (expired entries are excluded by the caller)."""
    return {
        "found": len(entries),
        "verified": sum(e.scholarship.verified for e in entries),
        "fully_funded": sum(e.scholarship.funding_type == "Fully Funded" for e in entries),
        "strong": sum(bool(e.match and e.match.category == "Strong Match") for e in entries),
        "closing_soon": sum(refreshed(e.scholarship).deadline_status == "CLOSING_SOON" for e in entries),
    }


def to_json(report: ScholarHunterReport) -> str:
    """Pretty JSON for ``st.download_button`` (schema follows the specification)."""
    return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)
