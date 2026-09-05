"""Planner Agent: turns (Requirements + Application Map) into a structured
test strategy/plan. Supports revision when the Plan Validator rejects it."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agents.planner.prompt import SYSTEM_PROMPT
from schemas.state import TestRunState
from services.llm_provider import get_llm_provider


class TestSuite(BaseModel):
    name: str
    objective: str
    requirement_ids: list[str] = Field(default_factory=list)
    scenario_titles: list[str] = Field(default_factory=list)


class TestPlan(BaseModel):
    test_plan_id: str
    objective: str
    test_suites: list[TestSuite] = Field(default_factory=list)
    coverage: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


def _build_user_prompt(state: TestRunState, feedback: Optional[dict]) -> str:
    reqs = [r.model_dump() for r in state.requirements]
    pages_summary = [
        {
            "url": p.url,
            "title": p.title,
            "forms": p.forms,
            "elements": [e.model_dump() for e in p.elements[:30]],
        }
        for p in state.application_map.pages
    ]
    parts = [
        f"REQUIREMENTS:\n{reqs}",
        f"APPLICATION MAP PAGES:\n{pages_summary}",
        f"AUTHENTICATION TYPE: {state.config.authentication_type}",
        f"DISCOVERY OBSERVATIONS: {state.application_map.observations}",
    ]
    if feedback:
        parts.append(f"PREVIOUS PLAN WAS REJECTED. VALIDATOR FEEDBACK TO ADDRESS:\n{feedback}")
    return "\n\n".join(parts)


async def run_planning(state: TestRunState) -> TestRunState:
    provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
    feedback = state.plan_validation if state.plan_validation.get("valid") is False else None
    plan = await provider.generate_structured(
        SYSTEM_PROMPT, _build_user_prompt(state, feedback), TestPlan
    )
    state.test_plan = plan.model_dump()
    return state
