from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aivar.models import CompiledTest, RunResult, Severity


def render_text(test: CompiledTest, result: RunResult) -> str:
    """
    Render a monospace text report with:
    - header with test id and intent
    - per-step table (columns: step, status, kind, verb, target, source, duration)
    - FINDINGS section (grouped by severity, critical first)
    - HEALS PENDING APPROVAL section (if any)
    - final summary line
    """
    lines = []

    # Header
    lines.append(f"Test: {test.id}")
    lines.append(f"Intent: {test.intent}")
    lines.append("")

    # Per-step table
    lines.append("Step Results:")
    lines.append("-" * 80)
    lines.append(
        f"{'Step':<8} {'Status':<10} {'Kind':<10} {'Verb':<12} {'Target':<20} {'Source':<10} {'Duration':<10}"
    )
    lines.append("-" * 80)

    for step_result in result.results:
        step = next((s for s in test.steps if s.id == step_result.step_id), None)
        if step:
            lines.append(
                f"{step.id:<8} {step_result.status:<10} {step.kind.value:<10} "
                f"{step.verb:<12} {step.target[:20]:<20} {step_result.source.value:<10} "
                f"{step_result.duration_ms:.0f}ms"
            )

    lines.append("-" * 80)
    lines.append("")

    # FINDINGS section (omit if empty)
    if result.findings:
        lines.append("FINDINGS:")
        # Sort by severity (critical first)
        sorted_findings = sorted(result.findings, key=lambda f: f.severity.order)
        for finding in sorted_findings:
            target_str = f" ({finding.target})" if finding.target else ""
            lines.append(
                f"[{finding.severity.value}] {finding.rule} — {finding.message}{target_str}"
            )
        lines.append("")

    # HEALS PENDING APPROVAL section (omit if empty)
    if result.heal_proposals:
        lines.append("HEALS PENDING APPROVAL:")
        for heal in result.heal_proposals:
            old_str = ""
            if heal.old:
                old_str = f"{heal.old.strategy}:{heal.old.value} → "
            new_str = f"{heal.new.strategy}:{heal.new.value}"
            lines.append(f"  {heal.step_id}: {old_str}{new_str}")
            lines.append(f"    Confidence: {heal.confidence:.2f}")
            lines.append(f"    Reasoning: {heal.reasoning}")
        lines.append("")

    # Final summary line
    lines.append(result.summary_line)

    return "\n".join(lines)


def render_json(test: CompiledTest, result: RunResult) -> dict[str, Any]:
    """
    Render JSON with test dict, result dict, and generated_at timestamp.
    """
    return {
        "test": test.to_dict(),
        "result": result.to_dict(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def write_report(
    test: CompiledTest, result: RunResult, out_dir: str | Path = "artifacts"
) -> Path:
    """
    Write a JSON report to <out_dir>/<test.id>-<UTC timestamp YYYYmmdd-HHMMSS>.json
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Generate filename with UTC timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"{test.id}-{timestamp}.json"
    file_path = out_path / filename

    # Write JSON report
    report_data = render_json(test, result)
    with open(file_path, "w") as f:
        json.dump(report_data, f, indent=2)

    return file_path
