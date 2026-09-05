"""Script Validator Agent: static analysis first (cheap, deterministic,
catches dangerous operations for certain), then an LLM review pass for
selector quality / assertion coverage / intent. A script is only marked
valid if both passes agree."""
from __future__ import annotations

import ast
import re

from pydantic import BaseModel, Field

from agents.script_validator.prompt import SYSTEM_PROMPT
from schemas.state import TestRunState
from services.llm_provider import get_llm_provider

FORBIDDEN_PATTERNS = (
    r"\bos\.system\(",
    r"\bsubprocess\.",
    r"\beval\(",
    r"\bexec\(",
    r"\btime\.sleep\(",
    r"__import__",
)

REQUIRED_SIGNATURE = re.compile(r"async\s+def\s+test_case\s*\(\s*page\s*,\s*base_url\s*,\s*credentials\s*\)")


class _LLMReview(BaseModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)


def _static_check(source: str) -> list[str]:
    issues: list[str] = []
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return [f"Syntax error: {exc}"]

    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, source):
            issues.append(f"Forbidden/unsafe operation matched pattern: {pattern}")

    if not REQUIRED_SIGNATURE.search(source):
        issues.append("Missing required signature: async def test_case(page, base_url, credentials)")

    if "expect(" not in source and ".assert" not in source:
        issues.append("No assertion (expect(...)) found in script")

    if re.search(r":nth-child\(\d+\)", source):
        issues.append("Brittle positional CSS selector (:nth-child) used")

    for secret_word in ("password", "token"):
        if re.search(rf'print\([^)]*{secret_word}', source, re.IGNORECASE):
            issues.append(f"Script appears to print a secret field: {secret_word}")

    return issues


async def run_script_validation(state: TestRunState) -> TestRunState:
    provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
    all_issues: dict[str, list[str]] = {}

    for script in state.generated_scripts:
        with open(script.file_path, "r", encoding="utf-8") as f:
            source = f.read()

        static_issues = _static_check(source)
        if static_issues:
            script.valid = False
            script.validation_issues = static_issues
            all_issues[script.test_case_id] = static_issues
            continue

        review = await provider.generate_structured(
            SYSTEM_PROMPT, f"SCRIPT SOURCE:\n{source}", _LLMReview
        )
        script.valid = review.valid
        script.validation_issues = review.issues
        if not review.valid:
            all_issues[script.test_case_id] = review.issues

    state.script_validation = {
        "total": len(state.generated_scripts),
        "valid": sum(1 for s in state.generated_scripts if s.valid),
        "invalid": sum(1 for s in state.generated_scripts if not s.valid),
        "issues_by_test_case": all_issues,
    }

    if all(not s.valid for s in state.generated_scripts) and state.generated_scripts:
        raise RuntimeError("All generated scripts failed validation - see script_validation for details")

    return state
