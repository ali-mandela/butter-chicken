from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from playwright.sync_api import sync_playwright
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

from aivar.browser import Browser
from aivar.config import DEFAULTS, Guardrails
from aivar.llm import LLMConfig, LLMResponse
from aivar.models import CompiledTest, Step, StepKind
from aivar.planner import PlannedStep, plan_steps, retry_plan_steps, PlanValidationError, LLMInvalidJSON
from aivar.resolve import best
from aivar.secrets import resolve_value
from aivar.testfile import save_test

logger = logging.getLogger("aivar")


DEFAULT_CREDENTIALS = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}


def apply_credentials(step: PlannedStep, credentials: dict[str, str]) -> str | None:
    """
    Apply credentials to a step value.

    If the step verb is 'fill' and value is None/empty:
    - If target contains 'pass' (case-insensitive), use credentials["password"]
    - If target contains 'user', 'email', or 'login', use credentials["username"]
    - Otherwise return the original value

    This is how secrets reach the test WITHOUT passing through the model.
    """
    if step.verb != "fill":
        return step.value

    if not step.value:
        target_lower = step.target.lower()
        if "pass" in target_lower:
            return credentials.get("password", step.value)
        elif any(word in target_lower for word in ["user", "email", "login"]):
            return credentials.get("username", step.value)

    return step.value


@dataclass
class CompileReport:
    """Report of a test compilation."""

    test: CompiledTest
    resolved: int
    unresolved: list[str]
    llm: LLMResponse
    plan_len: int

    @property
    def fully_compiled(self) -> bool:
        """True if all targets were resolved."""
        return len(self.unresolved) == 0


def compile_test(
    intent: str,
    url: str,
    *,
    test_id: str,
    config: LLMConfig | None = None,
    guardrails: Guardrails = DEFAULTS,
    credentials: dict[str, str] | None = None,
    headless: bool = True,
    planner: Callable[[str, str, LLMConfig], LLMResponse] | None = None,
) -> CompileReport:
    """
    Compile a test by dry-running it on the live app.

    Flow:
    1. Launch Chromium, navigate to url, wrap in Browser
    2. Take browser.snapshot()
    3. Call the planner ONCE (use injected planner if provided)
    4. Walk planned steps IN ORDER:
       a. Take a FRESH snapshot (page has advanced)
       b. resolve.best(nodes, target) to find a selector
       c. Apply credentials to the step value
       d. Execute the step with browser.act() so the page advances
       e. Build a Step with placeholder value (NOT resolved secret)
    5. Always close the browser (try/finally)
    6. Return CompileReport

    Errors during step execution do NOT abort compilation; they're recorded in unresolved.
    """
    if config is None:
        config = LLMConfig.from_env()

    if credentials is None:
        credentials = DEFAULT_CREDENTIALS

    playwright = None
    browser = None
    page = None
    browser_wrapper = None

    resolved_count = 0
    unresolved_targets = []
    planned_steps: list[PlannedStep] = []
    llm_response: LLMResponse | None = None

    try:
        # Launch browser
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        browser_wrapper = Browser(page)

        # Navigate to URL
        page.goto(url)
        logger.info(f"Navigated to {url}")

        # Take initial snapshot
        nodes = browser_wrapper.snapshot()
        logger.info(f"Took snapshot: {len(nodes)} visible nodes")

        # Call the planner ONCE
        try:
            planned_steps, llm_response = plan_steps(intent, nodes, config, planner=planner)
        except (PlanValidationError, LLMInvalidJSON) as e:
            logger.warning(f"Plan validation failed: {e}, retrying with corrective instruction")
            planned_steps, llm_response = retry_plan_steps(
                intent, nodes, config, str(e), planner=planner
            )

        logger.info(f"Planned {len(planned_steps)} steps")

        # Walk through planned steps
        compiled_steps: list[Step] = []

        for step_index, planned in enumerate(planned_steps):
            # Take a fresh snapshot (page has advanced)
            nodes = browser_wrapper.snapshot()
            logger.info(f"Step {step_index + 1}: took snapshot with {len(nodes)} nodes")

            # Try to resolve the target
            selector = None
            candidate = best(nodes, planned.target)
            if candidate:
                selector = candidate.selector
                resolved_count += 1
                logger.info(
                    f"Step {step_index + 1}: resolved '{planned.target}' -> {candidate.why}"
                )
            else:
                unresolved_targets.append(planned.target)
                logger.warning(f"Step {step_index + 1}: could not resolve '{planned.target}'")

            # Apply credentials to get the placeholder value for storage
            placeholder_value = apply_credentials(planned, credentials)

            # Build the step with placeholder value (NOT the resolved secret)
            step = Step(
                id=f"s{step_index + 1}",
                kind=planned.kind,
                verb=planned.verb,
                target=planned.target,
                value=placeholder_value,  # Use placeholder (e.g., ${AIVAR_PASSWORD})
                selector=selector,
            )
            compiled_steps.append(step)

            # For execution, resolve the placeholder value
            resolved_value = resolve_value(placeholder_value)

            # Execute the step (so the page advances for later steps)
            # Only execute if we have a selector and it's an ACTION step
            if selector and planned.kind == StepKind.ACTION:
                try:
                    browser_wrapper.act(selector, planned.verb, resolved_value, guardrails.action_timeout_ms)
                    logger.info(f"Step {step_index + 1}: executed {planned.verb} on '{planned.target}'")
                except Exception as e:
                    logger.warning(f"Step {step_index + 1}: execution failed: {e}")
                    # Don't abort; record the failure and continue

        # Build the compiled test
        test = CompiledTest(
            id=test_id,
            intent=intent,
            url=url,
            steps=compiled_steps,
        )

        return CompileReport(
            test=test,
            resolved=resolved_count,
            unresolved=unresolved_targets,
            llm=llm_response or LLMResponse(
                content="", model="unknown", prompt_tokens=0, completion_tokens=0,
                cost_usd=0.0, latency_ms=0.0
            ),
            plan_len=len(planned_steps),
        )

    finally:
        # Always close the browser
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
