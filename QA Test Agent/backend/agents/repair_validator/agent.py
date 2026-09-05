"""Repair Validator: independently checks a Healing Agent's proposed script
edit before it is ever written to disk or re-executed. Never trusts the
Healer's own claim that a repair is safe.

Per spec Section 19 / 20: a repair is rejected if it changes what the test
asserts (Section 19's hard rule - never modify assertions to hide a
failure), drops the required entry-point signature, or reintroduces any of
the dangerous/brittle patterns script_validator already screens for."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from agents.script_validator.agent import REQUIRED_SIGNATURE, _static_check

ASSERTION_LINE = re.compile(r"(expect\([^\n]*|assert\s[^\n]*)")


@dataclass
class RepairValidation:
    valid: bool
    issues: list[str] = field(default_factory=list)


def _assertions(source: str) -> list[str]:
    return sorted(m.strip() for m in ASSERTION_LINE.findall(source))


def validate_repair(original_source: str, updated_source: str) -> RepairValidation:
    issues = list(_static_check(updated_source))

    if _assertions(original_source) != _assertions(updated_source):
        issues.append(
            "Repair changed the test's assertions - the Healing Agent must only change how "
            "elements are located or waited for, never what the test verifies"
        )

    if not REQUIRED_SIGNATURE.search(updated_source):
        issues.append("Repair removed the required test_case(page, base_url, credentials) signature")

    return RepairValidation(valid=len(issues) == 0, issues=issues)
