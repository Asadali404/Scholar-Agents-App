from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class CandidateProfile(BaseModel):
    degree: str
    field: str
    cgpa: Optional[str] = None
    technical_skills: List[str] = Field(default_factory=list)
    research_pillars: List[str] = Field(default_factory=list)
    publications_count: Optional[int] = None
    experience_years: Optional[float] = None
    tests_taken: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    target_level: Literal["MS", "PhD", "Postdoc", "Any"]
    target_domain: Optional[str] = None
    countries: List[str] = Field(default_factory=list)

class RawResult(BaseModel):
    query: str
    title: str
    url: str
    snippet: str

class RawResults(BaseModel):
    results: List[RawResult] = Field(default_factory=list)

class ScholarshipRecord(BaseModel):
    country: str
    scholarship_name: str
    provider: Optional[str] = None
    level: Optional[str] = None
    deadline: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    funding: Optional[str] = None
    official_link: str
    confidence: Literal["high", "medium", "low"]
    fit_score: Optional[int] = None

class ScholarshipRecords(BaseModel):
    records: List[ScholarshipRecord] = Field(default_factory=list)

class GapItem(BaseModel):
    scholarship_name: str
    weaknesses: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"]
    est_prep_time: str

class GapReport(BaseModel):
    overall_strengths: List[str] = Field(default_factory=list)
    common_gaps: List[str] = Field(default_factory=list)
    per_scholarship: List[GapItem] = Field(default_factory=list)

class TrackerSummary(BaseModel):
    summary: str
