"""Reporter Agent: assembles the final Markdown report entirely from the
run's actual persisted state - execution_results, healing_attempts,
failures, etc. Every row in the tables below is backed by a real
ExecutionRecord; this agent never invents a result. The narrative
Executive Summary is the only LLM-generated text, and it is derived from
the same numbers shown in the tables (with a deterministic fallback if the
LLM call fails, so a summary-text hiccup never blocks report generation)."""
from __future__ import annotations

import os

from schemas.state import TestRunState, TestStatus
from services.llm_provider import get_llm_provider
from storage.run_repository import run_dir

STATUS_LABELS = {
    TestStatus.PASSED: "PASS",
    TestStatus.HEALED_PASSED: "PASS (healed)",
    TestStatus.FAILED: "FAIL",
    TestStatus.HEALING_EXHAUSTED: "FAIL (healing exhausted)",
    TestStatus.SKIPPED: "SKIPPED",
    TestStatus.PENDING: "NOT RUN",
    TestStatus.RUNNING: "NOT RUN",
    TestStatus.HEALING: "NOT RUN",
}

UNRESOLVED_CATEGORIES = {"APPLICATION_BUG", "ASSERTION_FAILURE", "DATA_FAILURE"}


def _pct(numerator: int, denominator: int) -> str:
    return f"{(numerator / denominator * 100):.0f}%" if denominator else "n/a"


def _enum_value(v):
    return v.value if hasattr(v, "value") else v


async def _executive_summary(state: TestRunState, total: int, passed: int, failed: int) -> str:
    try:
        provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
        prompt = (
            f"Application: {state.config.application_url}\n"
            f"Total tests: {total}, Passed: {passed}, Failed: {failed}\n"
            f"Requirements analyzed: {len(state.requirements)}\n"
            f"Healing attempts made: {len(state.healing_attempts)}\n"
            "Write a 3-4 sentence executive summary of this autonomous test run for a "
            "QA/engineering audience. Be factual and specific to these numbers - no filler."
        )
        return await provider.generate_text(
            "You write concise, factual QA executive summaries. Plain text, no markdown.", prompt
        )
    except Exception:
        return (
            f"Autonomous testing of {state.config.application_url} executed {total} test case(s): "
            f"{passed} passed and {failed} failed. See Detailed Results below."
        )


async def run_reporting(state: TestRunState) -> TestRunState:
    results_by_tc = {r.test_case_id: r for r in state.execution_results}
    total = len(state.test_cases)
    passed = sum(1 for r in state.execution_results if r.status in (TestStatus.PASSED, TestStatus.HEALED_PASSED))
    failed = sum(1 for r in state.execution_results if r.status in (TestStatus.FAILED, TestStatus.HEALING_EXHAUSTED))
    healed = sum(1 for r in state.execution_results if r.status == TestStatus.HEALED_PASSED)
    skipped = sum(1 for r in state.execution_results if r.status == TestStatus.SKIPPED)

    req_ids = {r.id for r in state.requirements}
    covered_reqs = {tc.requirement_id for tc in state.test_cases if tc.requirement_id} & req_ids
    coverage_pct = _pct(len(covered_reqs), len(req_ids))

    summary_text = await _executive_summary(state, total, passed, failed)

    lines: list[str] = []
    lines.append("# AUTONOMOUS TEST REPORT\n")

    lines.append("## Executive Summary\n")
    lines.append(summary_text.strip() + "\n")

    lines.append("## Application Information\n")
    lines.append(f"- URL: {state.config.application_url}")
    lines.append(f"- Authentication: {_enum_value(state.config.authentication_type)}")
    lines.append(f"- Run ID: {state.run_id}\n")

    lines.append("## Test Environment\n")
    lines.append("- Browser: Chromium (Playwright)")
    lines.append(f"- Parallel execution: {'ON' if state.config.parallel_execution else 'OFF'}")
    lines.append(f"- Max healing attempts: {state.config.max_healing_attempts}\n")

    lines.append("## Requirements Coverage\n")
    lines.append(f"- Requirements extracted from PRD: {len(req_ids)}")
    lines.append(f"- Requirements covered by at least one test case: {len(covered_reqs)} ({coverage_pct})\n")

    lines.append("## Application Discovery Summary\n")
    lines.append(f"- Pages discovered: {len(state.application_map.pages)}")
    for p in state.application_map.pages[:20]:
        lines.append(f"  - {p.url} ({len(p.elements)} interactive elements)")
    lines.append("")

    lines.append("## Test Strategy\n")
    lines.append(f"- Objective: {state.test_plan.get('objective', 'n/a')}")
    lines.append(f"- Test suites: {len(state.test_plan.get('test_suites', []))}")
    lines.append(f"- Plan validation coverage: {state.plan_validation.get('coverage_percentage', 'n/a')}%\n")

    lines.append("## Test Plan\n")
    for suite in state.test_plan.get("test_suites", []):
        lines.append(f"- **{suite.get('name')}**: {suite.get('objective')}")
    lines.append("")

    lines.append("## Test Cases\n")
    lines.append(f"Total test cases generated: {len(state.test_cases)}\n")

    lines.append("## Execution Summary\n")
    lines.append(f"Total {total} | Passed {passed} | Failed {failed} | Healed {healed} | Skipped {skipped}\n")
    lines.append("| Test Case | Requirement | Result | Healing | Duration |")
    lines.append("|---|---|---|---|---|")
    for tc in state.test_cases:
        record = results_by_tc.get(tc.test_case_id)
        result_label = STATUS_LABELS.get(record.status, "NOT RUN") if record else "NOT RUN"
        healing_label = "No"
        if record and record.status == TestStatus.HEALED_PASSED:
            healing_label = "Yes"
        elif record and record.status == TestStatus.HEALING_EXHAUSTED:
            healing_label = "Exhausted"
        duration = f"{record.duration_seconds}s" if record and record.duration_seconds is not None else "-"
        lines.append(f"| {tc.test_case_id} | {tc.requirement_id or '-'} | {result_label} | {healing_label} | {duration} |")
    lines.append("")

    lines.append("## Detailed Results\n")
    for tc in state.test_cases:
        record = results_by_tc.get(tc.test_case_id)
        lines.append(f"### {tc.test_case_id} - {tc.title}")
        lines.append(f"Status: {STATUS_LABELS.get(record.status, 'NOT RUN') if record else 'NOT RUN'}")
        if record and record.errors:
            lines.append("Errors:")
            for err in record.errors[:3]:
                lines.append(f"```\n{err}\n```")
        lines.append("")

    lines.append("## Failure Analysis\n")
    if not state.failures:
        lines.append("No failures were classified in this run.\n")
    for f in state.failures:
        lines.append(
            f"- **{f.test_case_id}**: {_enum_value(f.category)} (confidence {f.confidence:.2f}) - {f.root_cause}"
        )
    lines.append("")

    lines.append("## Healing History\n")
    if not state.healing_attempts:
        lines.append("No healing attempts were made in this run.\n")
    for h in state.healing_attempts:
        lines.append(
            f"- {h.test_case_id} attempt #{h.attempt_number}: {h.diagnosis} -> {h.proposed_change_summary} "
            f"(validated: {h.repair_validated}, re-execution: {_enum_value(h.re_execution_status) if h.re_execution_status else 'n/a'})"
        )
    lines.append("")

    unresolved = [f for f in state.failures if _enum_value(f.category) in UNRESOLVED_CATEGORIES]
    lines.append("## Unresolved Defects\n")
    if not unresolved:
        lines.append("None identified.\n")
    else:
        for f in unresolved:
            lines.append(f"- **{f.test_case_id}**: {f.root_cause} (category: {_enum_value(f.category)})")
    lines.append("")

    lines.append("## Coverage Analysis\n")
    lines.append(f"Requirement coverage: {coverage_pct} ({len(covered_reqs)}/{len(req_ids)}).\n")

    lines.append("## Recommendations\n")
    recommendations = []
    if unresolved:
        recommendations.append("Investigate the unresolved application defects listed above before the next release.")
    if skipped:
        recommendations.append("Fix script validation issues for the skipped test case(s) so they can run.")
    if len(covered_reqs) < len(req_ids):
        recommendations.append("Add test coverage for the requirements not yet mapped to any test case.")
    if not recommendations:
        recommendations.append("No blocking issues found in this run.")
    lines.extend(f"- {r}" for r in recommendations)
    lines.append("")

    lines.append("## Artifacts\n")
    lines.append(f"- Screenshots: `runs/{state.run_id}/screenshots/`")
    lines.append(f"- Videos: `runs/{state.run_id}/videos/`")
    lines.append(f"- Traces: `runs/{state.run_id}/traces/`")
    lines.append(f"- DOM snapshots: `runs/{state.run_id}/dom/`")
    lines.append(f"- Generated scripts: `runs/{state.run_id}/scripts/`")
    lines.append(f"- Logs: `runs/{state.run_id}/logs/`\n")

    report_path = os.path.join(run_dir(state.run_id), "report", "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    state.final_report_path = report_path
    return state
