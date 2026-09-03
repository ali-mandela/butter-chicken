from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from aivar.browser import Node
from aivar.llm import LLMConfig, LLMInvalidJSON, LLMResponse, chat_json, extract_json
from aivar.models import StepKind, Verb

logger = logging.getLogger("aivar")


PLAN_SYSTEM = """You are a test automation expert. Your task is to generate a test plan as a JSON object with the following structure:

```json
{"steps": [{"kind": "action", "verb": "fill", "target": "username field", "value": "..."}]}
```

Rules you MUST follow:

1. `kind` must be either "action" (modifies the page) or "assertion" (verifies something is visible).
2. `verb` must be one of: "click", "fill", "wait_visible".
3. An assertion ALWAYS uses verb "wait_visible" and value null.
4. `target` is a 1–3 word description of the element, matching visible wording where possible.
5. NEVER invent credentials. For username, email, or password fields, set value to null — credentials are injected separately.
6. Every plan MUST end with at least one assertion.
7. Return ONLY valid JSON, no markdown, prose, or explanation.
"""


@dataclass(frozen=True)
class PlannedStep:
    """A planned step from the LLM."""

    kind: StepKind
    verb: Verb
    target: str
    value: str | None


class PlanValidationError(Exception):
    """Raised when a plan is invalid."""

    pass


def validate_plan(raw: dict) -> list[PlannedStep]:
    """
    Validate and normalize a plan from the LLM.

    Rules:
    - raw["steps"] must be a non-empty list
    - Each step must have: kind ("action" or "assertion"), verb ("click", "fill", "wait_visible"), target (non-empty string)
    - Normalise: if kind == "assertion", force verb = "wait_visible" and value = None
    - Reject plans with zero assertions (raise PlanValidationError with comment about self-healing)

    Returns list[PlannedStep] if valid.
    """
    if "steps" not in raw or not isinstance(raw["steps"], list) or len(raw["steps"]) == 0:
        raise PlanValidationError("steps must be a non-empty list")

    steps = []
    assertion_count = 0

    for i, step_dict in enumerate(raw["steps"]):
        # Validate kind
        kind_str = step_dict.get("kind")
        if kind_str not in ("action", "assertion"):
            raise PlanValidationError(
                f"Step {i}: kind must be 'action' or 'assertion', got '{kind_str}'"
            )

        # Validate verb
        verb = step_dict.get("verb")
        if verb not in ("click", "fill", "wait_visible"):
            raise PlanValidationError(
                f"Step {i}: verb must be one of 'click', 'fill', 'wait_visible', got '{verb}'"
            )

        # Validate target
        target = step_dict.get("target", "").strip()
        if not target:
            raise PlanValidationError(f"Step {i}: target must be a non-empty string")

        # Get value
        value = step_dict.get("value")

        # Normalise assertions
        if kind_str == "assertion":
            verb = "wait_visible"
            value = None
            assertion_count += 1

        kind = StepKind(kind_str)
        steps.append(
            PlannedStep(kind=kind, verb=verb, target=target, value=value)
        )

    # Reject plans with no assertions
    if assertion_count == 0:
        raise PlanValidationError(
            "a plan with no assertions is not a test "
            "(a suite that asserts nothing always passes and is the classic way self-healing automation hides real regressions)"
        )

    return steps


def plan_steps(
    intent: str,
    nodes: list[Node],
    config: LLMConfig,
    planner: Callable[[str, str, LLMConfig], LLMResponse] | None = None,
) -> tuple[list[PlannedStep], LLMResponse]:
    """
    Generate a plan for the given intent and page nodes.

    Builds a user message with intent and compact node snapshot.
    Calls the LLM (or injected planner callable) to get a plan.
    Validates and normalises the plan.

    On PlanValidationError or LLMInvalidJSON, retries ONCE with a corrective instruction.
    If still invalid, raises the error.

    Returns (list[PlannedStep], LLMResponse).
    """
    # Build compact node snapshot
    node_lines = []
    for node in nodes[:60]:  # Limit to 60 nodes
        parts = []
        if node.role:
            parts.append(f"role={node.role}")
        if node.name:
            # Truncate name to 60 chars
            name = node.name[:60]
            parts.append(f"name={name}")
        if node.placeholder:
            parts.append(f"placeholder={node.placeholder}")
        if node.testid:
            parts.append(f"testid={node.testid}")

        if parts:
            node_lines.append("- " + " ".join(parts))

    snapshot = "\n".join(node_lines)

    user_message = f"""Intent: {intent}

Page snapshot (up to 60 visible nodes):
{snapshot}

Generate a test plan to automate this intent."""

    # Use injected planner if provided; otherwise use chat_json
    if planner:
        response = planner(PLAN_SYSTEM, user_message, config)
    else:
        response = chat_json(PLAN_SYSTEM, user_message, config)

    # Extract and validate JSON
    raw_json = extract_json(response.content)
    steps = validate_plan(raw_json)

    return steps, response


def retry_plan_steps(
    intent: str,
    nodes: list[Node],
    config: LLMConfig,
    error: str,
    planner: Callable[[str, str, LLMConfig], LLMResponse] | None = None,
) -> tuple[list[PlannedStep], LLMResponse]:
    """
    Retry the plan with a corrective instruction.

    Used after a PlanValidationError or LLMInvalidJSON to inform the model of the problem.
    """
    corrected_system = PLAN_SYSTEM + f"\n\nPrevious attempt failed: {error}\nPlease correct this."

    # Build compact node snapshot (reuse logic)
    node_lines = []
    for node in nodes[:60]:
        parts = []
        if node.role:
            parts.append(f"role={node.role}")
        if node.name:
            name = node.name[:60]
            parts.append(f"name={name}")
        if node.placeholder:
            parts.append(f"placeholder={node.placeholder}")
        if node.testid:
            parts.append(f"testid={node.testid}")

        if parts:
            node_lines.append("- " + " ".join(parts))

    snapshot = "\n".join(node_lines)

    user_message = f"""Intent: {intent}

Page snapshot (up to 60 visible nodes):
{snapshot}

Generate a test plan to automate this intent."""

    if planner:
        response = planner(corrected_system, user_message, config)
    else:
        response = chat_json(corrected_system, user_message, config)

    raw_json = extract_json(response.content)
    steps = validate_plan(raw_json)

    return steps, response
