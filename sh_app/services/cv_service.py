"""CV analysis and CV gap assessment."""
from __future__ import annotations

import json
import logging

from sh_app.core.models import CandidateProfile, CVAssessment, Scholarship
from sh_app.tasks.cv_tasks import build_cv_task
from sh_app.tasks.improvement_tasks import build_improvement_task
from sh_app.utils.text import truncate

logger = logging.getLogger(__name__)


def profile_json(profile: CandidateProfile) -> str:
    """Compact JSON of the non-empty profile fields (prompt-friendly)."""
    data = {k: v for k, v in profile.model_dump().items() if v not in ("", [], None)}
    for k in ("strengths", "weaknesses", "missing_information"):
        data.pop(k, None)
    return truncate(json.dumps(data, ensure_ascii=False), 5000)


def analyze_cv(crew, cv_text: str) -> CandidateProfile:
    """Run the CV Analyst. Failure here is fatal (nothing to match without a profile)."""
    return crew.run_stage(crew.cv_agent, build_cv_task(crew.cv_agent, cv_text), CandidateProfile)


def assess_cv(crew, profile: CandidateProfile, scholarships: list[Scholarship], warnings: list[str]) -> CVAssessment:
    """Run the CV Improvement Advisor; falls back to the analyst's own findings on failure."""
    block = "\n".join(
        f"- {s.scholarship_name} ({s.university}, {s.country}): {truncate(s.eligibility, 300)} "
        f"{truncate(s.application_requirements, 200)}" for s in scholarships[:10]
    ) or "(no verified opportunities found; use general expectations)"
    try:
        result = crew.run_stage(crew.improve_agent,
                                build_improvement_task(crew.improve_agent, profile_json(profile), block),
                                CVAssessment)
    except Exception as exc:
        logger.warning("CV improvement stage failed: %s", type(exc).__name__)
        warnings.append("The CV improvement advisor could not complete; showing the CV analyst's findings instead.")
        result = CVAssessment()
    if not result.strengths:
        result.strengths = profile.strengths
    if not result.gaps:
        result.gaps = profile.weaknesses
    if not result.missing_information:
        result.missing_information = profile.missing_information
    return result
