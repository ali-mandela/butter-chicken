"""Executor Agent: runs every validated generated script against a real
browser. Test cases marked parallel_safe with no unmet dependencies run
concurrently (in isolated browser contexts) when config.parallel_execution
is on; everything else runs sequentially, respecting depends_on order.

Scripts that failed script_validator are never executed - they are recorded
as SKIPPED. This agent never fabricates a PASSED/FAILED result: every
ExecutionRecord it produces comes from browser.executor.execute_script,
which ran a real Playwright session."""
from __future__ import annotations

import asyncio

from browser.executor import execute_script
from browser.playwright_manager import PlaywrightManager
from schemas.state import ExecutionRecord, TestCase, TestRunState, TestStatus
from security.secrets import get_secret_store
from storage.run_repository import run_dir


def _topological_batches(test_cases: list[TestCase], valid_ids: set[str]) -> list[list[TestCase]]:
    """Groups test cases into ordered batches: every test case in a batch can
    start together (their dependencies are already satisfied by prior
    batches); tests with no dependents run in the earliest possible batch."""
    remaining = {tc.test_case_id: tc for tc in test_cases if tc.test_case_id in valid_ids}
    done: set[str] = set()
    batches: list[list[TestCase]] = []

    while remaining:
        batch = [
            tc
            for tc in remaining.values()
            if all(dep in done or dep not in remaining for dep in tc.depends_on)
        ]
        if not batch:
            # Unresolved/circular dependency - never deadlock: run what's left, in order.
            batch = list(remaining.values())
        batches.append(batch)
        for tc in batch:
            done.add(tc.test_case_id)
            remaining.pop(tc.test_case_id, None)

    return batches


async def run_execution(state: TestRunState) -> TestRunState:
    base = run_dir(state.run_id)
    credential = None
    if state.config.credential_ref:
        credential = get_secret_store().get(state.config.credential_ref)

    scripts_by_tc = {s.test_case_id: s for s in state.generated_scripts if s.valid}
    valid_ids = set(scripts_by_tc.keys())

    results: dict[str, ExecutionRecord] = {
        tc.test_case_id: ExecutionRecord(
            test_case_id=tc.test_case_id,
            status=TestStatus.SKIPPED,
            errors=["Script failed validation - not executed"],
        )
        for tc in state.test_cases
        if tc.test_case_id not in valid_ids
    }

    manager = PlaywrightManager(engine="chromium", headless=True)
    await manager.start()
    try:
        batches = _topological_batches(state.test_cases, valid_ids)
        for batch in batches:
            run_parallel = state.config.parallel_execution
            parallel_batch = [tc for tc in batch if tc.parallel_safe and run_parallel]
            sequential_batch = [tc for tc in batch if tc not in parallel_batch]

            if parallel_batch:
                coros = [
                    execute_script(
                        manager, scripts_by_tc[tc.test_case_id], state.config.application_url, credential, base
                    )
                    for tc in parallel_batch
                ]
                batch_results = await asyncio.gather(*coros)
                for tc, record in zip(parallel_batch, batch_results):
                    results[tc.test_case_id] = record

            for tc in sequential_batch:
                results[tc.test_case_id] = await execute_script(
                    manager, scripts_by_tc[tc.test_case_id], state.config.application_url, credential, base
                )
    finally:
        await manager.stop()

    state.execution_results = [results[tc.test_case_id] for tc in state.test_cases]
    return state
