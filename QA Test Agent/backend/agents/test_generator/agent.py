from __future__ import annotations

from pydantic import BaseModel, Field

from agents.test_generator.prompt import SYSTEM_PROMPT
from schemas.state import TestCase, TestRunState
from services.llm_provider import get_llm_provider


class _TestCaseList(BaseModel):
    test_cases: list[TestCase] = Field(default_factory=list)


async def run_test_generation(state: TestRunState) -> TestRunState:
    provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
    pages_summary = [
        {"url": p.url, "title": p.title, "elements": [e.model_dump() for e in p.elements[:40]]}
        for p in state.application_map.pages
    ]
    prompt = (
        f"APPROVED TEST PLAN:\n{state.test_plan}\n\n"
        f"APPLICATION MAP:\n{pages_summary}\n\n"
        f"REQUIREMENTS:\n{[r.model_dump() for r in state.requirements]}"
    )
    result = await provider.generate_structured(SYSTEM_PROMPT, prompt, _TestCaseList)
    if not result.test_cases:
        raise RuntimeError("Test Case Generator produced zero test cases")
    state.test_cases = result.test_cases
    return state
