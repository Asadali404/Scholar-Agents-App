"""Crew orchestration: runs the seven agents sequentially and validates every output."""
from __future__ import annotations

import logging
from typing import Callable, Optional, Type, TypeVar

from crewai import Agent, Crew, Process, Task
from pydantic import BaseModel, ValidationError

from sh_app.agents.application_strategy_agent import build_application_strategy_agent
from sh_app.agents.cv_agent import build_cv_agent
from sh_app.agents.cv_improvement_agent import build_cv_improvement_agent
from sh_app.agents.profile_match_agent import build_profile_match_agent
from sh_app.agents.report_agent import build_report_agent
from sh_app.agents.scholarship_search_agent import build_search_agent
from sh_app.agents.verification_agent import build_verification_agent
from sh_app.core.config import Settings, get_settings
from sh_app.core.llm import LLMCallError, build_llm
from sh_app.core.models import ScholarHunterReport, SearchPreferences
from sh_app.utils.json_utils import extract_json

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
Progress = Callable[[float, str], None]


class StageError(RuntimeError):
    """An agent stage failed after one retry."""


class ScholarHunterCrew:
    """Owns the LLM, the seven agents, and the sequential pipeline."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.diag: list[str] = []  # step-by-step run log shown in the UI
        self.llm = build_llm(self.settings)  # raises MissingAPIKeyError if no key
        self.cv_agent: Agent = build_cv_agent(self.llm)
        self.search_agent: Agent = build_search_agent(self.llm)
        self.verify_agent: Agent = build_verification_agent(self.llm)
        self.match_agent: Agent = build_profile_match_agent(self.llm)
        self.improve_agent: Agent = build_cv_improvement_agent(self.llm)
        self.strategy_agent: Agent = build_application_strategy_agent(self.llm)
        self.report_agent: Agent = build_report_agent(self.llm)

    def _kickoff(self, agent: Agent, task: Task) -> str:
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        try:
            result = crew.kickoff()
        except LLMCallError as exc:
            raise StageError(str(exc)) from exc
        except Exception as exc:
            logger.error("Crew execution failed: %s", type(exc).__name__)
            msg = "rate" if "rate" in str(exc).lower() else "unexpected error"
            raise StageError(f"An AI agent failed ({msg}). Please wait a moment and try again.") from exc
        return getattr(result, "raw", None) or str(result)

    def run_stage(self, agent: Agent, task: Task, model: Type[T]) -> T:
        """Run one task, parse + validate JSON, retry once with a stricter instruction."""
        raw = self._kickoff(agent, task)
        try:
            return model.model_validate(extract_json(raw))
        except (ValueError, ValidationError):
            logger.warning("Invalid agent output; retrying once")
        retry = Task(
            description=task.description + "\n\nIMPORTANT: your previous reply was not valid JSON for this "
                        "schema. Reply again with ONLY the JSON object, no commentary, no code fences.",
            expected_output=task.expected_output, agent=agent)
        raw = self._kickoff(agent, retry)
        try:
            return model.model_validate(extract_json(raw))
        except (ValueError, ValidationError) as exc:
            raise StageError("An agent returned malformed output twice. Please try again.") from exc

    def run(self, cv_text: str, prefs: SearchPreferences, progress: Progress) -> ScholarHunterReport:
        """Full pipeline: CV → search → verify → match → improve → strategy → report."""
        from sh_app.services import cv_service, report_service, scholarship_service as ss

        warnings: list[str] = []
        progress(0.02, "🔍 Reading your CV...")
        profile = cv_service.analyze_cv(self, cv_text)
        progress(0.14, "✓ CV analysis complete")

        progress(0.16, "🌐 Searching scholarship sources...")
        discovery = ss.discover_scholarships(self, profile, prefs, warnings)
        progress(0.38, "✓ Opportunities discovered")

        progress(0.40, "🔎 Verifying deadlines...")
        verified = ss.verify_scholarships(self, discovery, prefs, warnings)
        progress(0.58, "✓ Current opportunities verified")

        progress(0.60, "🧠 Matching your profile...")
        matches = ss.match_profile(self, profile, verified, warnings)
        progress(0.74, "✓ Profile assessment complete")

        progress(0.76, "📝 Identifying CV gaps...")
        assessment = cv_service.assess_cv(self, profile, verified, warnings)
        plans, strategy = ss.build_strategy(self, profile, verified, assessment, warnings)
        progress(0.90, "✓ Recommendations generated")

        progress(0.92, "📊 Preparing final report...")
        report = report_service.build_report(
            self, profile, prefs, verified, matches, plans, assessment, strategy, warnings)
        if not report.scholarships:
            self.diag.append("Result: 0 scholarships survived. See the lines above to see which step lost them.")
        self.diag.append(f"AI model used: {self.llm.active_model}")
        report.diagnostics = list(self.diag)
        progress(1.0, "✓ Report ready")
        return report
