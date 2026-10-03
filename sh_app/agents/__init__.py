"""CrewAI agent factories."""
from __future__ import annotations

from typing import Any

from crewai import Agent


def make_agent(llm: Any, role: str, goal: str, backstory: str) -> Agent:
    """Create a tool-free reasoning agent. Web access happens outside the LLM layer."""
    return Agent(role=role, goal=goal, backstory=backstory, llm=llm,
                 allow_delegation=False, verbose=False, max_iter=3)
