"""Final report task (narrative only; structured data is assembled in code)."""
from __future__ import annotations

from crewai import Agent, Task


def build_report_task(agent: Agent, facts_block: str) -> Task:
    """Write a short executive summary from verified facts."""
    return Task(
        description=(
            "Write an executive summary (max 120 words, plain prose) of the findings below. Mention counts, "
            "the nearest deadline if any, the candidate's main strength and main gap, and remind the reader to "
            "confirm details on official websites. Use ONLY the facts provided.\n"
            'Respond with ONLY valid JSON: {"executive_summary": ""}\n\n' + facts_block
        ),
        expected_output='A JSON object {"executive_summary": "..."}.',
        agent=agent,
    )
