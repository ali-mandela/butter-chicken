"""Plan Validator Agent: reviews the Planner's output before anything is
allowed to reach Test Case Generation. Drives a bounded Planner<->Validator
revision loop (max_plan_revisions, configured centrally - never infinite)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.plan_validator.prompt import SYSTEM_PROMPT
from agents.planner.agent import run_planning
from config.settings import get_settings
from schemas.state import TestRunState
from services.llm_provider import get_llm_provider


class PlanValidation(BaseModel):
    valid: bool
    coverage_percentage: float
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


async def _validate_once(state: TestRunState) -> PlanValidation:
    provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
    reqs = [r.model_dump() for r in state.requirements]
    prompt = (
        f"REQUIREMENTS:\n{reqs}\n\n"
        f"APPLICATION MAP PAGE URLS: {[p.url for p in state.application_map.pages]}\n\n"
        f"TEST PLAN TO VALIDATE:\n{state.test_plan}"
    )
    return await provider.generate_structured(SYSTEM_PROMPT, prompt, PlanValidation)


async def run_plan_validation(state: TestRunState) -> TestRunState:
    settings = get_settings()
    validation = await _validate_once(state)
    state.plan_validation = validation.model_dump()

    while not validation.valid and state.plan_revision_count < settings.max_plan_revisions:
        state.plan_revision_count += 1
        state = await run_planning(state)
        validation = await _validate_once(state)
        state.plan_validation = validation.model_dump()

    if not validation.valid:
        raise RuntimeError(
            f"Test plan failed validation after {state.plan_revision_count} revision(s): "
            f"{validation.issues}"
        )
    return state
