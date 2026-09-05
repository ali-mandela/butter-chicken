"""Tests for the triage gate."""

from __future__ import annotations

import pytest

from aivar.contracts import TriageResult, TriageVerdict
from aivar.llm import LLMConfig, LLMError, LLMInvalidJSON, LLMResponse
from aivar.models import FailureKind, Selector, Source, Step, StepKind, StepResult
from aivar.triage import summarize_triage, triage_failure, triage_run


# Fixtures for reusable test data


@pytest.fixture
def action_step() -> Step:
    """An action step that can fail."""
    return Step(
        id="action_1",
        kind=StepKind.ACTION,
        verb="click",
        target="Submit button",
        selector=Selector(strategy="role", value="button", role="button"),
    )


@pytest.fixture
def assertion_step() -> Step:
    """An assertion step that can fail."""
    return Step(
        id="assert_1",
        kind=StepKind.ASSERTION,
        verb="wait_visible",
        target="Success message",
        selector=Selector(strategy="text", value="Success"),
    )


@pytest.fixture
def llm_config() -> LLMConfig:
    """A minimal LLM config for testing."""
    return LLMConfig(api_key="test_key", models=("test_model",))


# Tests for deterministic rules (no model)


class TestAssertionFailed:
    """ASSERTION_FAILED is always APP_DEFECT."""

    def test_assertion_failed_returns_app_defect_with_confidence_1(
        self, assertion_step: Step
    ) -> None:
        """ASSERTION_FAILED → APP_DEFECT, confidence 1.0."""
        result = StepResult(
            step_id="assert_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.ASSERTION_FAILED,
            error="Expected 'Success' to be visible",
        )

        triage_result, llm_response = triage_failure(assertion_step, result)

        assert triage_result.verdict is TriageVerdict.APP_DEFECT
        assert triage_result.confidence == 1.0
        assert llm_response is None
        assert "assertion" in triage_result.reasoning.lower()

    def test_assertion_failed_model_never_called(
        self, assertion_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """ASSERTION_FAILED never calls the model."""
        result = StepResult(
            step_id="assert_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.ASSERTION_FAILED,
            error="Expected value not found",
        )

        # Monkeypatch chat_json to fail if called
        def fake_chat_json(*args, **kwargs):
            raise AssertionError("Model should not be called for ASSERTION_FAILED")

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        # Should not raise because the model is never consulted
        triage_result, _ = triage_failure(assertion_step, result, config=llm_config)
        assert triage_result.verdict is TriageVerdict.APP_DEFECT


class TestAgentError:
    """AGENT_ERROR is harness/infrastructure, always FLAKY."""

    def test_agent_error_returns_flaky_with_confidence_1(self, action_step: Step) -> None:
        """AGENT_ERROR → FLAKY, confidence 1.0."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.NONE,
            duration_ms=100.0,
            failure=FailureKind.AGENT_ERROR,
            error="Browser disconnected",
        )

        triage_result, llm_response = triage_failure(action_step, result)

        assert triage_result.verdict is TriageVerdict.FLAKY
        assert triage_result.confidence == 1.0
        assert llm_response is None
        assert "harness" in triage_result.reasoning.lower() or "infrastructure" in triage_result.reasoning.lower()

    def test_agent_error_model_never_called(
        self, action_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """AGENT_ERROR never calls the model."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.NONE,
            duration_ms=100.0,
            failure=FailureKind.AGENT_ERROR,
            error="Internal error",
        )

        def fake_chat_json(*args, **kwargs):
            raise AssertionError("Model should not be called for AGENT_ERROR")

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        triage_result, _ = triage_failure(action_step, result, config=llm_config)
        assert triage_result.verdict is TriageVerdict.FLAKY


class TestActionFailed:
    """ACTION_FAILED is element found but action didn't complete, treat as FLAKY."""

    def test_action_failed_returns_flaky_with_confidence_0_7(self, action_step: Step) -> None:
        """ACTION_FAILED → FLAKY, confidence 0.7."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.ACTION_FAILED,
            error="Action timed out",
        )

        triage_result, llm_response = triage_failure(action_step, result)

        assert triage_result.verdict is TriageVerdict.FLAKY
        assert triage_result.confidence == 0.7
        assert llm_response is None
        assert "timing" in triage_result.reasoning.lower() or "overlay" in triage_result.reasoning.lower()

    def test_action_failed_model_never_called(
        self, action_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """ACTION_FAILED never calls the model."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.ACTION_FAILED,
            error="Action failed",
        )

        def fake_chat_json(*args, **kwargs):
            raise AssertionError("Model should not be called for ACTION_FAILED")

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        triage_result, _ = triage_failure(action_step, result, config=llm_config)
        assert triage_result.verdict is TriageVerdict.FLAKY


# Tests for LOCATOR_NOT_FOUND (the model case)


class TestLocatorNotFoundNoConfig:
    """LOCATOR_NOT_FOUND with no config falls back to SCRIPT_ISSUE."""

    def test_locator_not_found_no_config_returns_script_issue(
        self, action_step: Step
    ) -> None:
        """LOCATOR_NOT_FOUND without config → SCRIPT_ISSUE, confidence 0.5."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.LOCATOR_NOT_FOUND,
            error="Element with role 'button' not found",
        )

        triage_result, llm_response = triage_failure(action_step, result, config=None)

        assert triage_result.verdict is TriageVerdict.SCRIPT_ISSUE
        assert triage_result.confidence == 0.5
        assert llm_response is None


class TestLocatorNotFoundWithModel:
    """LOCATOR_NOT_FOUND with config consults the model."""

    def test_locator_not_found_calls_model(
        self, action_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """LOCATOR_NOT_FOUND with config calls the model."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.LOCATOR_NOT_FOUND,
            error="Element not found",
        )

        model_called = False

        def fake_chat_json(*args, **kwargs):
            nonlocal model_called
            model_called = True
            return LLMResponse(
                content='{"verdict": "script_issue", "confidence": 0.8, "reasoning": "Similar button names found"}',
                model="test_model",
                prompt_tokens=10,
                completion_tokens=20,
                cost_usd=0.001,
                latency_ms=100.0,
            )

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        triage_result, llm_response = triage_failure(
            action_step, result, config=llm_config, page_context="The page shows a form"
        )

        assert model_called
        assert llm_response is not None
        assert triage_result.verdict is TriageVerdict.SCRIPT_ISSUE
        assert triage_result.confidence == 0.8

    def test_model_returns_app_defect(
        self, action_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """Model can return app_defect."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.LOCATOR_NOT_FOUND,
            error="Element not found",
        )

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content='{"verdict": "app_defect", "confidence": 0.9, "reasoning": "Feature entirely missing"}',
                model="test_model",
                prompt_tokens=10,
                completion_tokens=20,
                cost_usd=0.001,
                latency_ms=100.0,
            )

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        triage_result, _ = triage_failure(action_step, result, config=llm_config)

        assert triage_result.verdict is TriageVerdict.APP_DEFECT
        assert triage_result.confidence == 0.9

    def test_model_returns_flaky(
        self, action_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """Model can return flaky."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.LOCATOR_NOT_FOUND,
            error="Element not found",
        )

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content='{"verdict": "flaky", "confidence": 0.6, "reasoning": "Timing issue"}',
                model="test_model",
                prompt_tokens=10,
                completion_tokens=20,
                cost_usd=0.001,
                latency_ms=100.0,
            )

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        triage_result, _ = triage_failure(action_step, result, config=llm_config)

        assert triage_result.verdict is TriageVerdict.FLAKY
        assert triage_result.confidence == 0.6


# Hard invariant: ASSERTION steps can never be SCRIPT_ISSUE


class TestAssertionInvariant:
    """ASSERTION steps can never be marked as SCRIPT_ISSUE."""

    def test_assertion_model_script_issue_override_to_app_defect(
        self, assertion_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """If model returns script_issue for an ASSERTION, override to APP_DEFECT."""
        result = StepResult(
            step_id="assert_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.LOCATOR_NOT_FOUND,
            error="Element not found",
        )

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content='{"verdict": "script_issue", "confidence": 0.8, "reasoning": "Selector drift"}',
                model="test_model",
                prompt_tokens=10,
                completion_tokens=20,
                cost_usd=0.001,
                latency_ms=100.0,
            )

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        triage_result, _ = triage_failure(assertion_step, result, config=llm_config)

        # Must be overridden to APP_DEFECT, not SCRIPT_ISSUE
        assert triage_result.verdict is TriageVerdict.APP_DEFECT
        # Reasoning should note the override
        assert "overrid" in triage_result.reasoning.lower()


# Error handling


class TestModelErrorHandling:
    """Handle model errors gracefully."""

    def test_llm_error_degrades_to_script_issue(
        self, action_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """LLMError during model call degrades to SCRIPT_ISSUE 0.5."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.LOCATOR_NOT_FOUND,
            error="Element not found",
        )

        def fake_chat_json(*args, **kwargs):
            raise LLMError("API key invalid")

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        triage_result, _ = triage_failure(action_step, result, config=llm_config)

        assert triage_result.verdict is TriageVerdict.SCRIPT_ISSUE
        assert triage_result.confidence == 0.5

    def test_malformed_json_degrades_to_script_issue(
        self, action_step: Step, llm_config: LLMConfig, monkeypatch
    ) -> None:
        """Malformed JSON response degrades to SCRIPT_ISSUE 0.5."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.LOCATOR_NOT_FOUND,
            error="Element not found",
        )

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content="This is not JSON at all",
                model="test_model",
                prompt_tokens=10,
                completion_tokens=20,
                cost_usd=0.001,
                latency_ms=100.0,
            )

        monkeypatch.setattr("aivar.triage.chat_json", fake_chat_json)

        triage_result, _ = triage_failure(action_step, result, config=llm_config)

        assert triage_result.verdict is TriageVerdict.SCRIPT_ISSUE
        assert triage_result.confidence == 0.5


# Heal eligibility


class TestHealEligibility:
    """Only SCRIPT_ISSUE is heal-eligible."""

    def test_script_issue_is_heal_eligible(self, action_step: Step) -> None:
        """SCRIPT_ISSUE verdict has heal_eligible=True."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.LOCATOR_NOT_FOUND,
            error="Element not found",
        )

        triage_result, _ = triage_failure(action_step, result, config=None)

        assert triage_result.verdict is TriageVerdict.SCRIPT_ISSUE
        assert triage_result.heal_eligible is True

    def test_app_defect_not_heal_eligible(self, action_step: Step) -> None:
        """APP_DEFECT verdict has heal_eligible=False."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.ASSERTION_FAILED,
            error="Assertion failed",
        )

        triage_result, _ = triage_failure(action_step, result)

        assert triage_result.verdict is TriageVerdict.APP_DEFECT
        assert triage_result.heal_eligible is False

    def test_flaky_not_heal_eligible(self, action_step: Step) -> None:
        """FLAKY verdict has heal_eligible=False."""
        result = StepResult(
            step_id="action_1",
            status="failed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=FailureKind.ACTION_FAILED,
            error="Action failed",
        )

        triage_result, _ = triage_failure(action_step, result)

        assert triage_result.verdict is TriageVerdict.FLAKY
        assert triage_result.heal_eligible is False


# Edge cases


class TestEdgeCases:
    """Edge cases and error conditions."""

    def test_triage_passed_result_raises_value_error(self, action_step: Step) -> None:
        """Triaging a passed result raises ValueError."""
        result = StepResult(
            step_id="action_1",
            status="passed",
            source=Source.HEURISTIC,
            duration_ms=100.0,
            failure=None,
            error=None,
        )

        with pytest.raises(ValueError, match="Cannot triage a passed or skipped result"):
            triage_failure(action_step, result)

    def test_triage_skipped_result_raises_value_error(self, action_step: Step) -> None:
        """Triaging a skipped result raises ValueError."""
        result = StepResult(
            step_id="action_1",
            status="skipped",
            source=Source.HEURISTIC,
            duration_ms=0.0,
            failure=None,
            error=None,
        )

        with pytest.raises(ValueError, match="Cannot triage a passed or skipped result"):
            triage_failure(action_step, result)


# triage_run tests


class TestTriageRun:
    """Test the triage_run batch function."""

    def test_triage_run_skips_passed_and_skipped(self, action_step: Step) -> None:
        """triage_run skips passed and skipped results."""
        steps_by_id = {action_step.id: action_step}
        results = [
            StepResult(
                step_id="action_1",
                status="passed",
                source=Source.HEURISTIC,
                duration_ms=100.0,
                failure=None,
            ),
            StepResult(
                step_id="action_1",
                status="failed",
                source=Source.HEURISTIC,
                duration_ms=100.0,
                failure=FailureKind.ACTION_FAILED,
                error="Action failed",
            ),
            StepResult(
                step_id="action_1",
                status="skipped",
                source=Source.HEURISTIC,
                duration_ms=0.0,
                failure=None,
            ),
        ]

        triage_results = triage_run(steps_by_id, results)

        # Only the failed one should be triaged
        assert len(triage_results) == 1
        assert triage_results[0].step_id == "action_1"

    def test_triage_run_returns_in_result_order(self) -> None:
        """triage_run returns results in the same order as input."""
        step1 = Step(
            id="action_1",
            kind=StepKind.ACTION,
            verb="click",
            target="Button 1",
        )
        step2 = Step(
            id="action_2",
            kind=StepKind.ACTION,
            verb="click",
            target="Button 2",
        )
        step3 = Step(
            id="action_3",
            kind=StepKind.ACTION,
            verb="click",
            target="Button 3",
        )

        steps_by_id = {step1.id: step1, step2.id: step2, step3.id: step3}
        results = [
            StepResult(
                step_id="action_1",
                status="failed",
                source=Source.HEURISTIC,
                duration_ms=100.0,
                failure=FailureKind.ACTION_FAILED,
            ),
            StepResult(
                step_id="action_3",
                status="failed",
                source=Source.HEURISTIC,
                duration_ms=100.0,
                failure=FailureKind.AGENT_ERROR,
            ),
            StepResult(
                step_id="action_2",
                status="failed",
                source=Source.HEURISTIC,
                duration_ms=100.0,
                failure=FailureKind.ACTION_FAILED,
            ),
        ]

        triage_results = triage_run(steps_by_id, results)

        # Should be in result order: 1, 3, 2
        assert [t.step_id for t in triage_results] == ["action_1", "action_3", "action_2"]


# summarize_triage tests


class TestSummarizeTriage:
    """Test the summarize_triage summary function."""

    def test_summarize_triage_counts_verdicts(self) -> None:
        """summarize_triage counts correctly by verdict."""
        results = [
            TriageResult(
                step_id="1",
                verdict=TriageVerdict.SCRIPT_ISSUE,
                confidence=0.5,
                reasoning="Script issue 1",
            ),
            TriageResult(
                step_id="2",
                verdict=TriageVerdict.SCRIPT_ISSUE,
                confidence=0.6,
                reasoning="Script issue 2",
            ),
            TriageResult(
                step_id="3",
                verdict=TriageVerdict.APP_DEFECT,
                confidence=1.0,
                reasoning="App defect",
            ),
            TriageResult(
                step_id="4",
                verdict=TriageVerdict.FLAKY,
                confidence=0.7,
                reasoning="Flaky 1",
            ),
            TriageResult(
                step_id="5",
                verdict=TriageVerdict.FLAKY,
                confidence=0.8,
                reasoning="Flaky 2",
            ),
        ]

        summary = summarize_triage(results)

        assert summary["script_issue"] == 2
        assert summary["app_defect"] == 1
        assert summary["flaky"] == 2

    def test_summarize_triage_empty_list(self) -> None:
        """summarize_triage handles empty list."""
        summary = summarize_triage([])

        assert summary["script_issue"] == 0
        assert summary["app_defect"] == 0
        assert summary["flaky"] == 0
