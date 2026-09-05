"""Healing Agent: repairs automation defects (selector drift, timing,
script-logic bugs) and re-executes, bounded by config.max_healing_attempts
per test case. Never touches genuine application defects or assertions
(Section 19's hard rule) - those categories are skipped here entirely and
surface in the report as unresolved defects instead.

Every proposed repair goes through the Repair Validator before it is ever
written to disk, and every re-execution is a real Playwright run via
browser.executor.execute_script - no fabricated results."""
from __future__ import annotations

import os

from pydantic import BaseModel

from agents.healer.prompt import SYSTEM_PROMPT
from agents.repair_validator.agent import validate_repair
from browser.executor import execute_script
from browser.playwright_manager import PlaywrightManager
from schemas.state import FailureCategory, HealingAttempt, TestRunState, TestStatus
from security.secrets import get_secret_store
from services.llm_provider import get_llm_provider
from storage.run_repository import run_dir

HEALABLE_CATEGORIES = {
    FailureCategory.SELECTOR_FAILURE,
    FailureCategory.TIMING_FAILURE,
    FailureCategory.TEST_SCRIPT_BUG,
}


class _RepairProposal(BaseModel):
    diagnosis: str
    updated_source_code: str
    change_summary: str


def _latest_dom_context(state: TestRunState) -> str:
    for page in state.application_map.pages:
        if page.dom_snapshot_path and os.path.exists(page.dom_snapshot_path):
            try:
                with open(page.dom_snapshot_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()[:20000]
            except OSError:
                continue
    return "(no DOM snapshot available)"


async def run_healing(state: TestRunState) -> TestRunState:
    provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
    max_attempts = state.config.max_healing_attempts
    scripts_by_tc = {s.test_case_id: s for s in state.generated_scripts}
    results_by_tc = {r.test_case_id: r for r in state.execution_results}
    credential = get_secret_store().get(state.config.credential_ref) if state.config.credential_ref else None
    dom_context = _latest_dom_context(state)
    base = run_dir(state.run_id)

    manager = PlaywrightManager(engine="chromium", headless=True)
    await manager.start()
    try:
        for failure in state.failures:
            if failure.category not in HEALABLE_CATEGORIES:
                continue  # application defect / assertion mismatch / etc - never "fixed" here

            script = scripts_by_tc.get(failure.test_case_id)
            if script is None:
                continue

            attempt_number = 0
            current_status = TestStatus.FAILED

            while attempt_number < max_attempts and current_status == TestStatus.FAILED:
                attempt_number += 1
                with open(script.file_path, "r", encoding="utf-8") as f:
                    original_source = f.read()

                record = results_by_tc[failure.test_case_id]
                prompt = (
                    f"FAILURE CATEGORY: {failure.category.value}\n"
                    f"ROOT CAUSE (from Failure Classifier): {failure.root_cause}\n"
                    f"EVIDENCE: {failure.evidence}\n\n"
                    f"ORIGINAL SCRIPT:\n{original_source}\n\n"
                    f"LATEST ERRORS:\n{record.errors}\n\n"
                    f"CURRENT DOM SNAPSHOT (best-effort, may be from a related page):\n{dom_context}\n"
                )
                proposal = await provider.generate_structured(SYSTEM_PROMPT, prompt, _RepairProposal)

                validation = validate_repair(original_source, proposal.updated_source_code)
                attempt = HealingAttempt(
                    test_case_id=failure.test_case_id,
                    attempt_number=attempt_number,
                    failure_category=failure.category,
                    diagnosis=proposal.diagnosis,
                    proposed_change_summary=proposal.change_summary,
                    repair_validated=validation.valid,
                    repair_rejected_reason=None if validation.valid else "; ".join(validation.issues),
                )

                if not validation.valid:
                    state.healing_attempts.append(attempt)
                    continue

                with open(script.file_path, "w", encoding="utf-8") as f:
                    f.write(proposal.updated_source_code)

                new_record = await execute_script(
                    manager, script, state.config.application_url, credential, base
                )
                attempt.re_execution_status = new_record.status
                state.healing_attempts.append(attempt)
                results_by_tc[failure.test_case_id] = new_record
                current_status = new_record.status

            final_record = results_by_tc[failure.test_case_id]
            if final_record.status == TestStatus.FAILED:
                final_record.status = TestStatus.HEALING_EXHAUSTED
            elif final_record.status == TestStatus.PASSED and attempt_number > 0:
                final_record.status = TestStatus.HEALED_PASSED
    finally:
        await manager.stop()

    state.execution_results = [results_by_tc[tc.test_case_id] for tc in state.test_cases]
    return state
