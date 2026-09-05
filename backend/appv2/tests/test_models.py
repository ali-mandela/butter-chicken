import pytest
from aivar.models import (
    Step,
    StepKind,
    Verb,
    Selector,
    FailureKind,
    CompiledTest,
    StepResult,
    Source,
    RunResult,
)


def test_action_step_is_healable():
    """Test that an ACTION step is healable."""
    step = Step(
        id="step1",
        kind=StepKind.ACTION,
        verb="click",
        target="button",
    )
    assert step.healable is True


def test_assertion_step_is_not_healable():
    """Test that an ASSERTION step is not healable."""
    step = Step(
        id="step1",
        kind=StepKind.ASSERTION,
        verb="wait_visible",
        target="success_message",
    )
    assert step.healable is False


def test_locator_not_found_heal_eligible():
    """Test that LOCATOR_NOT_FOUND is heal_eligible."""
    assert FailureKind.LOCATOR_NOT_FOUND.heal_eligible is True


def test_other_failures_not_heal_eligible():
    """Test that other failures are not heal_eligible."""
    assert FailureKind.ACTION_FAILED.heal_eligible is False
    assert FailureKind.ASSERTION_FAILED.heal_eligible is False
    assert FailureKind.AGENT_ERROR.heal_eligible is False


def test_agent_error_not_test_failure():
    """Test that AGENT_ERROR is not a test failure."""
    assert FailureKind.AGENT_ERROR.is_test_failure is False


def test_other_failures_are_test_failures():
    """Test that other failures are test failures."""
    assert FailureKind.LOCATOR_NOT_FOUND.is_test_failure is True
    assert FailureKind.ACTION_FAILED.is_test_failure is True
    assert FailureKind.ASSERTION_FAILED.is_test_failure is True


def test_compiled_test_roundtrip():
    """Test that CompiledTest round-trips through to_dict/from_dict."""
    selector = Selector(strategy="role", value="button", role="submit")
    step_with_selector = Step(
        id="step1",
        kind=StepKind.ACTION,
        verb="click",
        target="submit_btn",
        selector=selector,
    )
    step_without_selector = Step(
        id="step2",
        kind=StepKind.ASSERTION,
        verb="wait_visible",
        target="success_msg",
    )
    test = CompiledTest(
        id="test1",
        intent="Submit the form",
        url="https://example.com",
        steps=[step_with_selector, step_without_selector],
        version=1,
    )

    data = test.to_dict()
    restored = CompiledTest.from_dict(data)

    assert restored.id == test.id
    assert restored.intent == test.intent
    assert restored.url == test.url
    assert restored.version == test.version
    assert len(restored.steps) == 2

    # Check first step with selector
    restored_step1 = restored.steps[0]
    assert restored_step1.id == "step1"
    assert restored_step1.kind == StepKind.ACTION
    assert restored_step1.verb == "click"
    assert restored_step1.selector is not None
    assert restored_step1.selector.strategy == "role"
    assert restored_step1.selector.value == "button"
    assert restored_step1.selector.role == "submit"

    # Check second step without selector
    restored_step2 = restored.steps[1]
    assert restored_step2.id == "step2"
    assert restored_step2.kind == StepKind.ASSERTION
    assert restored_step2.verb == "wait_visible"
    assert restored_step2.selector is None


def test_run_result_from_results_all_passed():
    """Test that RunResult.from_results returns 'passed' for all-passed."""
    results = [
        StepResult(
            step_id="step1",
            status="passed",
            source=Source.CACHE,
            duration_ms=100.0,
        ),
        StepResult(
            step_id="step2",
            status="passed",
            source=Source.CACHE,
            duration_ms=50.0,
        ),
    ]
    run = RunResult.from_results(test_id="test1", results=results)
    assert run.status == "passed"


def test_run_result_from_results_one_failed():
    """Test that RunResult.from_results returns 'failed' when one failed."""
    results = [
        StepResult(
            step_id="step1",
            status="passed",
            source=Source.CACHE,
            duration_ms=100.0,
        ),
        StepResult(
            step_id="step2",
            status="failed",
            source=Source.CACHE,
            duration_ms=50.0,
            failure=FailureKind.ASSERTION_FAILED,
        ),
    ]
    run = RunResult.from_results(test_id="test1", results=results)
    assert run.status == "failed"


def test_run_result_from_results_agent_error_outranks():
    """Test that RunResult.from_results returns 'error' when AGENT_ERROR present."""
    results = [
        StepResult(
            step_id="step1",
            status="passed",
            source=Source.CACHE,
            duration_ms=100.0,
        ),
        StepResult(
            step_id="step2",
            status="failed",
            source=Source.CACHE,
            duration_ms=50.0,
            failure=FailureKind.AGENT_ERROR,
        ),
    ]
    run = RunResult.from_results(test_id="test1", results=results)
    assert run.status == "error"
