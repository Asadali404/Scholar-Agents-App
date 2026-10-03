"""Profile matching task."""
from __future__ import annotations

from crewai import Agent, Task

SCHEMA = (
    '{"matches":[{"scholarship_id":"s1","category":"Strong Match|Potential Match|Needs Improvement|Insufficient Information",'
    '"fit_scores":{"academic":0,"research":0,"technical":0,"experience":0,"eligibility":0},'
    '"match_summary":"","matching_requirements":[],"missing_requirements":[],"potential_concerns":[],"recommended_actions":[]}]}'
)


def build_matching_task(agent: Agent, profile_json: str, scholarships_json: str) -> Task:
    """Compare the candidate with each verified scholarship."""
    return Task(
        description=(
            "Compare the candidate profile with each scholarship. Use ONLY the profile and the listed "
            "eligibility/requirements. If a scholarship lists no usable eligibility information, use the "
            "category 'Insufficient Information'. fit_scores are rough 0-100 integers (AI-assisted, not "
            "statistically validated). Do not claim anything the profile does not show. Keep every text "
            "item under 30 words. Return one match per scholarship id.\n"
            "Respond with ONLY valid JSON using this schema:\n" + SCHEMA +
            "\n\n<CANDIDATE>\n" + profile_json + "\n</CANDIDATE>\n<SCHOLARSHIPS>\n" + scholarships_json + "\n</SCHOLARSHIPS>"
        ),
        expected_output="A single JSON object with a 'matches' array.",
        agent=agent,
    )
