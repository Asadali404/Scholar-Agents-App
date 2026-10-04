"""Pydantic models. All LLM output is validated through these before use."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

DISCLAIMER = (
    "Scholarship availability and deadlines can change. Always confirm the final deadline and "
    "eligibility requirements on the official scholarship/university website before applying."
)
RANKING_NOTE = (
    "Results are ordered by deadline proximity, then verification status, then profile "
    "compatibility. This is a display mechanism, not an objective ranking of scholarship quality."
)
MATCH_CATEGORIES = ("Strong Match", "Potential Match", "Needs Improvement", "Insufficient Information")


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        return ", ".join(s for s in (_to_str(x) for x in v) if s)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _to_list(v: Any) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, (list, tuple, set)):
        return [s for s in (_to_str(x) for x in v) if s]
    if isinstance(v, dict):
        return [f"{k}: {_to_str(x)}" for k, x in v.items()]
    return [str(v)]


def _to_bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "1", "y"}
    return bool(v)


Str = Annotated[str, BeforeValidator(_to_str)]
StrList = Annotated[list[str], BeforeValidator(_to_list)]
Bool = Annotated[bool, BeforeValidator(_to_bool)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class SearchPreferences(_Base):
    countries: StrList = Field(default_factory=list)
    department: Str = ""
    degree_level: Str = "MS"  # MS | PhD | Postdoctoral
    funding_type: Str = "Either"  # Fully Funded | Partially Funded | Either

    @property
    def any_country(self) -> bool:
        return not self.countries or any(c.lower().startswith("any") for c in self.countries)


class CandidateProfile(_Base):
    degree: Str = ""
    university: Str = ""
    graduation_year: Str = ""
    gpa: Str = ""
    field: Str = ""
    education: StrList = Field(default_factory=list)
    experience: StrList = Field(default_factory=list)
    research_experience: StrList = Field(default_factory=list)
    publications: StrList = Field(default_factory=list)
    projects: StrList = Field(default_factory=list)
    certifications: StrList = Field(default_factory=list)
    skills: StrList = Field(default_factory=list)
    programming_languages: StrList = Field(default_factory=list)
    ai_ml_experience: StrList = Field(default_factory=list)
    awards: StrList = Field(default_factory=list)
    internships: StrList = Field(default_factory=list)
    english_proficiency: Str = ""
    research_interests: StrList = Field(default_factory=list)
    strengths: StrList = Field(default_factory=list)
    weaknesses: StrList = Field(default_factory=list)
    missing_information: StrList = Field(default_factory=list)


class Scholarship(_Base):
    id: Str = ""
    scholarship_name: Str = ""
    university: Str = ""
    country: Str = ""
    degree_level: Str = ""
    field: Str = ""
    funding_type: Str = "Unknown"
    funding_details: Str = ""
    deadline: Str = ""
    deadline_iso: Optional[str] = None
    deadline_status: Str = "UNKNOWN"
    days_remaining: Optional[int] = None
    deadline_note: Str = ""
    official_url: Optional[str] = None
    source_url: Optional[str] = None
    source_tier: Str = "secondary"
    eligibility: Str = ""
    application_requirements: Str = ""
    verified: Bool = False
    verification_notes: Str = ""

    @field_validator("official_url", "source_url", mode="before")
    @classmethod
    def _url(cls, v: Any) -> Optional[str]:
        return v.strip() if isinstance(v, str) and v.strip().lower().startswith(("http://", "https://")) else None

    @field_validator("deadline_iso", mode="before")
    @classmethod
    def _iso(cls, v: Any) -> Optional[str]:
        return v if isinstance(v, str) and v.strip() else None

    @field_validator("days_remaining", mode="before")
    @classmethod
    def _days(cls, v: Any) -> Optional[int]:
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @field_validator("funding_type", mode="before")
    @classmethod
    def _funding(cls, v: Any) -> str:
        s = _to_str(v).lower()
        if "full" in s:
            return "Fully Funded"
        if "partial" in s:
            return "Partially Funded"
        return "Unknown"


class FitScores(_Base):
    academic: int = 0
    research: int = 0
    technical: int = 0
    experience: int = 0
    eligibility: int = 0

    @field_validator("*", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> int:
        try:
            return max(0, min(100, int(float(v))))
        except (TypeError, ValueError):
            return 0


class ScholarshipMatch(_Base):
    scholarship_id: Str = ""
    category: Str = "Insufficient Information"
    fit_scores: FitScores = Field(default_factory=FitScores)
    match_summary: Str = ""
    matching_requirements: StrList = Field(default_factory=list)
    missing_requirements: StrList = Field(default_factory=list)
    potential_concerns: StrList = Field(default_factory=list)
    recommended_actions: StrList = Field(default_factory=list)

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v: Any) -> str:
        s = _to_str(v).lower()
        for c in MATCH_CATEGORIES:
            if c.lower() == s or c.lower().split()[0] in s.split()[:1]:
                return c
        return "Insufficient Information"


class CVAssessment(_Base):
    strengths: StrList = Field(default_factory=list)
    gaps: StrList = Field(default_factory=list)
    missing_information: StrList = Field(default_factory=list)
    recommendations: StrList = Field(default_factory=list)


class ApplicationPlan(_Base):
    scholarship_id: Str = ""
    why_match: Str = ""
    potential_concerns: StrList = Field(default_factory=list)
    documents_required: StrList = Field(default_factory=list)
    preparation_checklist: StrList = Field(default_factory=list)
    suggested_timeline: StrList = Field(default_factory=list)
    research_positioning: StrList = Field(default_factory=list)
    professor_contact: StrList = Field(default_factory=list)
    sop_suggestions: StrList = Field(default_factory=list)
    recommendation_letters: StrList = Field(default_factory=list)


class RoadmapStep(_Base):
    step: Str = ""
    title: Str = ""
    details: Str = ""
    timeframe: Str = ""


class ApplicationStrategy(_Base):
    priority_actions: StrList = Field(default_factory=list)
    roadmap: list[RoadmapStep] = Field(default_factory=list)
    documents_to_prepare: StrList = Field(default_factory=list)
    research_preparation: StrList = Field(default_factory=list)
    sop_preparation: StrList = Field(default_factory=list)
    recommendation_letter_preparation: StrList = Field(default_factory=list)
    professor_contact_strategy: StrList = Field(default_factory=list)


class ScholarshipEntry(_Base):
    scholarship: Scholarship
    match: Optional[ScholarshipMatch] = None
    plan: Optional[ApplicationPlan] = None


class ScholarHunterReport(_Base):
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    candidate: CandidateProfile = Field(default_factory=CandidateProfile)
    search_preferences: SearchPreferences = Field(default_factory=SearchPreferences)
    scholarships: list[ScholarshipEntry] = Field(default_factory=list)
    profile_assessment: CVAssessment = Field(default_factory=CVAssessment)
    application_strategy: ApplicationStrategy = Field(default_factory=ApplicationStrategy)
    sources: list[str] = Field(default_factory=list)
    executive_summary: Str = ""
    warnings: StrList = Field(default_factory=list)
    diagnostics: StrList = Field(default_factory=list)  # step-by-step run log (counts, drop reasons)
    disclaimer: str = DISCLAIMER
    ranking_note: str = RANKING_NOTE


# ---- containers used to validate agent outputs ----------------------------------------
class ExtractionResult(_Base):
    scholarships: list[Scholarship] = Field(default_factory=list)


class VerificationCheck(_Base):
    id: Str = ""
    consistent: Bool = True
    notes: Str = ""


class VerificationResult(_Base):
    checks: list[VerificationCheck] = Field(default_factory=list)


class MatchResult(_Base):
    matches: list[ScholarshipMatch] = Field(default_factory=list)


class PlanResult(_Base):
    plans: list[ApplicationPlan] = Field(default_factory=list)


class ReportSummary(_Base):
    executive_summary: Str = ""
