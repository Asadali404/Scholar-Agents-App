"""CV improvement and application strategy tasks."""
from __future__ import annotations

from datetime import date

from crewai import Agent, Task

ASSESS_SCHEMA = '{"strengths":[],"gaps":[],"missing_information":[],"recommendations":[]}'
PLAN_SCHEMA = (
    '{"plans":[{"scholarship_id":"s1","why_match":"","potential_concerns":[],"documents_required":[],'
    '"preparation_checklist":[],"suggested_timeline":[],"research_positioning":[],"professor_contact":[],'
    '"sop_suggestions":[],"recommendation_letters":[]}]}'
)
OVERALL_SCHEMA = (
    '{"priority_actions":[],"roadmap":[{"step":"1","title":"","details":"","timeframe":""}],'
    '"documents_to_prepare":[],"research_preparation":[],"sop_preparation":[],'
    '"recommendation_letter_preparation":[],"professor_contact_strategy":[]}'
)


def build_improvement_task(agent: Agent, profile_json: str, requirements_block: str) -> Task:
    """CV gap analysis against requirements seen in the verified scholarships."""
    return Task(
        description=(
            "Assess the candidate's CV against the requirements typically stated in the opportunities below "
            "(if the list is empty, use general expectations for the requested degree level and say so). "
            "Identify gaps (missing skills, research experience, weak project descriptions, missing measurable "
            "results, publications, certifications, GitHub/portfolio evidence, unclear goals) and give actionable "
            "recommendations. NEVER suggest inventing achievements. Max 8 short items per list.\n"
            "Respond with ONLY valid JSON using this schema:\n" + ASSESS_SCHEMA +
            "\n\n<CANDIDATE>\n" + profile_json + "\n</CANDIDATE>\n<REQUIREMENTS>\n" + requirements_block + "\n</REQUIREMENTS>"
        ),
        expected_output="A single JSON object following the schema.",
        agent=agent,
    )


def build_plan_task(agent: Agent, profile_json: str, scholarships_json: str, today: date) -> Task:
    """Per-scholarship application plans."""
    return Task(
        description=(
            f"Today's date is {today.isoformat()}. For EACH scholarship, create a practical application plan "
            "for this candidate. Base 'documents_required' only on the listed requirements, otherwise write "
            "'Check the official page' plus typical documents. Timelines must work back from the stated deadline "
            "(if the deadline is unknown, say so). Do not invent professors, portals or URLs; for professor "
            "contact, give a strategy only. Max 5 short items per list.\n"
            "Respond with ONLY valid JSON using this schema:\n" + PLAN_SCHEMA +
            "\n\n<CANDIDATE>\n" + profile_json + "\n</CANDIDATE>\n<SCHOLARSHIPS>\n" + scholarships_json + "\n</SCHOLARSHIPS>"
        ),
        expected_output="A single JSON object with a 'plans' array.",
        agent=agent,
    )


def build_overall_strategy_task(agent: Agent, summary_block: str, today: date) -> Task:
    """Overall roadmap and preparation strategy."""
    return Task(
        description=(
            f"Today's date is {today.isoformat()}. Create an overall application strategy and a 6-step roadmap "
            "(improve CV, identify supervisors, prepare SOP, request recommendation letters, prepare documents, "
            "submit). Prioritise by the nearest verified deadlines. Max 6 short items per list; no invented facts.\n"
            "Respond with ONLY valid JSON using this schema:\n" + OVERALL_SCHEMA + "\n\n" + summary_block
        ),
        expected_output="A single JSON object following the schema.",
        agent=agent,
    )
