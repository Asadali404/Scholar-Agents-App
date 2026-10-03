"""CV analysis task."""
from __future__ import annotations

from crewai import Agent, Task

from sh_app.utils.text import truncate

SCHEMA = (
    '{"degree":"","university":"","graduation_year":"","gpa":"","field":"","education":[],"experience":[],'
    '"research_experience":[],"publications":[],"projects":[],"certifications":[],"skills":[],'
    '"programming_languages":[],"ai_ml_experience":[],"awards":[],"internships":[],'
    '"english_proficiency":"","research_interests":[],"strengths":[],"weaknesses":[],"missing_information":[]}'
)


def build_cv_task(agent: Agent, cv_text: str) -> Task:
    """Extract a structured candidate profile (no personal contact details)."""
    return Task(
        description=(
            "Analyse the CV below and build a structured candidate profile.\n"
            "Rules: use ONLY information present in the CV; leave unknown values empty and list them in "
            "missing_information; do NOT include name, email, phone or address; keep each list item short "
            "(under 25 words); 'strengths'/'weaknesses' must be evidence-based for a scholarship applicant.\n"
            "Respond with ONLY valid JSON using exactly this schema:\n" + SCHEMA +
            "\n\n<CV_TEXT>\n" + truncate(cv_text, 12000) + "\n</CV_TEXT>"
        ),
        expected_output="A single JSON object following the schema.",
        agent=agent,
    )
