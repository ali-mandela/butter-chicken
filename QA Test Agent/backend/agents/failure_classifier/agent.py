from __future__ import annotations

from pydantic import BaseModel, Field

from agents.failure_classifier.prompt import SYSTEM_PROMPT
from schemas.state import FailureAnalysis, FailureCategory, TestRunState, TestStatus
from services.llm_provider import get_llm_provider


class _Classification(BaseModel):
    category: FailureCategory
    confidence: float
    root_cause: str
    evidence: list[str] = Field(default_factory=list)


async def run_failure_classification(state: TestRunState) -> TestRunState:
    provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
    scripts_by_tc = {s.test_case_id: s for s in state.generated_scripts}
    analyses: list[FailureAnalysis] = []

    for record in state.execution_results:
        if record.status != TestStatus.FAILED:
            continue

        script = scripts_by_tc.get(record.test_case_id)
        source = ""
        if script:
            try:
                with open(script.file_path, "r", encoding="utf-8") as f:
                    source = f.read()
            except OSError:
                source = ""

        prompt = (
            f"TEST CASE ID: {record.test_case_id}\n\n"
            f"SCRIPT SOURCE:\n{source}\n\n"
            f"ERRORS:\n{record.errors}\n\n"
            f"CONSOLE LOGS:\n{record.console_logs}\n\n"
            f"NETWORK ERRORS:\n{record.network_errors}\n"
        )
        result = await provider.generate_structured(SYSTEM_PROMPT, prompt, _Classification)
        analyses.append(
            FailureAnalysis(
                test_case_id=record.test_case_id,
                category=result.category,
                confidence=result.confidence,
                root_cause=result.root_cause,
                evidence=result.evidence,
            )
        )

    state.failures = analyses
    return state
