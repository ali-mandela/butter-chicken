from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aivar.config import Guardrails
from aivar.executor import run_test
from aivar.llm import LLMConfig, LLMResponse
from aivar.models import (
    CompiledTest,
    FailureKind,
    Selector,
    Source,
    Step,
    StepKind,
)
from aivar.testfile import load_test, save_test


@pytest.fixture
def saucedemo_url() -> str:
    """Return a file:// URL to saucedemo_like.html."""
    fixture_path = Path(__file__).parent / "fixtures" / "saucedemo_like.html"
    return fixture_path.resolve().as_uri()


@pytest.fixture
def llm_config() -> LLMConfig:
    """Dummy LLM config."""
    return LLMConfig(api_key="test-key")


def fake_chat_json_high_confidence(*args, **kwargs):
    """Fake model returning high confidence."""
    return LLMResponse(
        content=json.dumps(
            {"index": 0, "confidence": 0.95, "reasoning": "Clear match"}
        ),
        model="fake",
        prompt_tokens=10,
        completion_tokens=10,
        cost_usd=0.001,
        latency_ms=50,
    )


def fake_chat_json_low_confidence(*args, **kwargs):
    """Fake model returning low confidence."""
    return LLMResponse(
        content=json.dumps(
            {"index": 0, "confidence": 0.2, "reasoning": "Uncertain"}
        ),
        model="fake",
        prompt_tokens=10,
        completion_tokens=10,
        cost_usd=0.001,
        latency_ms=50,
    )


class TestHealRepairsStaleSelectorWithMocking:
    """Test that healing can repair a stale selector."""

    def test_heal_repairs_stale_selector(self, tmp_path, saucedemo_url, llm_config):
        """
        A STALE compiled selector is repaired by the heal loop.

        This is the case self-healing actually exists for: the selector was
        compiled and committed, then a developer renamed the attribute it was
        pinned to. Setup:
        - s1's compiled selector points at [data-test="login-username-OLD"],
          which no longer matches anything on the page (genuine drift)
        - Tier 0 probes it, finds it stale, and falls through
        - Tier 1 is forced to abstain (resolve.best patched to None) while the
          real shortlist is still produced, so Tier 2 gets genuine candidates
        - A faked high-confidence model picks from that shortlist
        """
        test = CompiledTest(
            id="test-heal-stale",
            intent="Login flow",
            url=saucedemo_url,
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ACTION,
                    verb="fill",
                    target="username field",
                    value="standard_user",
                    # Genuine drift: this attribute value no longer exists.
                    selector=Selector(
                        strategy="css", value='[data-test="login-username-OLD"]'
                    ),
                ),
                Step(
                    id="s2",
                    kind=StepKind.ACTION,
                    verb="fill",
                    target="password field",
                    value="secret_sauce",
                    # This one is fine
                    selector=Selector(strategy="placeholder", value="Password"),
                ),
                Step(
                    id="s3",
                    kind=StepKind.ACTION,
                    verb="click",
                    target="login button",
                    selector=Selector(strategy="css", value='[data-test="login-button"]'),
                ),
                Step(
                    id="s4",
                    kind=StepKind.ASSERTION,
                    verb="wait_visible",
                    target="products title",
                    selector=Selector(strategy="text", value="Products"),
                ),
            ],
            version=1,
        )

        # Save to tmp
        test_path = tmp_path / "test.json"
        save_test(test, test_path)

        # Mock resolve.best to return None (simulating Tier 1 failure)
        # while leaving shortlist real
        def mock_best(nodes, target):
            return None

        with patch("aivar.executor.best", side_effect=mock_best):
            with patch("aivar.healer.chat_json", side_effect=fake_chat_json_high_confidence):
                result = run_test(
                    test,
                    heal=True,
                    llm_config=llm_config,
                    quarantine_dir=str(tmp_path / "quarantine"),
                )

        # Assert the step passed
        s1_result = next(r for r in result.results if r.step_id == "s1")
        assert s1_result.status == "passed"
        assert s1_result.source is Source.HEALED

        # Assert a proposal was saved
        assert result.heals_used == 1
        assert len(result.heal_proposals) == 1

        proposal = result.heal_proposals[0]
        assert proposal.test_id == "test-heal-stale"
        assert proposal.step_id == "s1"
        assert proposal.confidence == 0.95

        # Assert the compiled test file on disk is UNCHANGED
        # (healing uses the proposal for the run, not the test file)
        reloaded = load_test(test_path)
        assert reloaded.steps[0].selector.value == '[data-test="login-username-OLD"]'
        assert reloaded.version == 1

        # Assert proposal file exists
        quarantine_path = tmp_path / "quarantine"
        proposal_files = list(quarantine_path.glob("*.json"))
        assert len(proposal_files) == 1

    def test_assertion_never_healed(self, tmp_path, saucedemo_url, llm_config):
        """Assertion steps are never healed, even with heal=True."""
        test = CompiledTest(
            id="test-no-heal-assertion",
            intent="Test",
            url=saucedemo_url,
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ASSERTION,
                    verb="wait_visible",
                    target="products",
                    # Stale selector
                    selector=Selector(strategy="text", value="NonexistentText"),
                ),
            ],
            version=1,
        )

        test_path = tmp_path / "test.json"
        save_test(test, test_path)

        with patch("aivar.executor.best", return_value=None):
            with patch("aivar.healer.chat_json", side_effect=fake_chat_json_high_confidence):
                result = run_test(
                    test,
                    heal=True,
                    llm_config=llm_config,
                    quarantine_dir=str(tmp_path / "quarantine"),
                )

        # Assert the step failed with ASSERTION_FAILED
        assert result.results[0].status == "failed"
        assert result.results[0].failure == FailureKind.ASSERTION_FAILED

        # Assert no heals were used
        assert result.heals_used == 0
        assert len(result.heal_proposals) == 0

        # Assert no proposal files
        quarantine_path = tmp_path / "quarantine"
        if quarantine_path.exists():
            proposal_files = list(quarantine_path.glob("*.json"))
            assert len(proposal_files) == 0

    def test_heal_cap_enforced(self, tmp_path, saucedemo_url, llm_config):
        """max_heals_per_run cap is enforced."""
        # Three failing steps
        test = CompiledTest(
            id="test-heal-cap",
            intent="Test",
            url=saucedemo_url,
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ACTION,
                    verb="fill",
                    target="username field",
                    value="test",
                    selector=Selector(strategy="css", value='[data-test="username-OLD"]'),
                ),
                Step(
                    id="s2",
                    kind=StepKind.ACTION,
                    verb="fill",
                    target="password field",
                    value="test",
                    selector=Selector(strategy="css", value='[data-test="password-OLD"]'),
                ),
                Step(
                    id="s3",
                    kind=StepKind.ACTION,
                    verb="click",
                    target="login button",
                    selector=Selector(strategy="css", value='[data-test="login-button-OLD"]'),
                ),
            ],
            version=1,
        )

        test_path = tmp_path / "test.json"
        save_test(test, test_path)

        guardrails = Guardrails(max_heals_per_run=1)

        with patch("aivar.executor.best", return_value=None):
            with patch("aivar.healer.chat_json", side_effect=fake_chat_json_high_confidence):
                result = run_test(
                    test,
                    heal=True,
                    llm_config=llm_config,
                    quarantine_dir=str(tmp_path / "quarantine"),
                    guardrails=guardrails,
                )

        # Only the first step should be healed
        assert result.heals_used == 1

        # The second step should fail with error mentioning the cap
        s2_result = next(r for r in result.results if r.step_id == "s2")
        assert s2_result.status == "failed"
        assert "cap" in s2_result.error.lower() or s2_result.failure == FailureKind.LOCATOR_NOT_FOUND

        # The third step should be skipped
        s3_result = next(r for r in result.results if r.step_id == "s3")
        assert s3_result.status == "skipped"

    def test_low_confidence_rejected(self, tmp_path, saucedemo_url, llm_config):
        """Low confidence response is rejected."""
        test = CompiledTest(
            id="test-low-confidence",
            intent="Test",
            url=saucedemo_url,
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ACTION,
                    verb="fill",
                    target="username field",
                    value="test",
                    selector=Selector(strategy="css", value='[data-test="username-OLD"]'),
                ),
            ],
            version=1,
        )

        test_path = tmp_path / "test.json"
        save_test(test, test_path)

        guardrails = Guardrails(min_heal_confidence=0.5)

        with patch("aivar.executor.best", return_value=None):
            with patch("aivar.healer.chat_json", side_effect=fake_chat_json_low_confidence):
                result = run_test(
                    test,
                    heal=True,
                    llm_config=llm_config,
                    quarantine_dir=str(tmp_path / "quarantine"),
                    guardrails=guardrails,
                )

        # Step should fail (not healed)
        s1_result = result.results[0]
        assert s1_result.status == "failed"
        assert s1_result.failure == FailureKind.LOCATOR_NOT_FOUND

        # No proposal should be saved
        assert result.heals_used == 0
        assert len(result.heal_proposals) == 0


@pytest.mark.live
class TestHealLoopLive:
    """
    Live test against real saucedemo with real model.
    Deselected by default (use -m live to run).
    """

    def test_heal_with_real_model_live(self, saucedemo_url):
        """Live test: heal against saucedemo with real model call."""
        import os

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            pytest.skip("OPENROUTER_API_KEY not set")

        test = CompiledTest(
            id="test-live-heal",
            intent="Login flow",
            url=saucedemo_url,
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ACTION,
                    verb="fill",
                    target="username field",
                    value="standard_user",
                    # Stale selector
                    selector=Selector(strategy="css", value='[data-test="username-OLD"]'),
                ),
            ],
            version=1,
        )

        llm_config = LLMConfig.from_env()

        # Mock resolve.best to force healing attempt
        with patch("aivar.executor.best", return_value=None):
            result = run_test(
                test,
                heal=True,
                llm_config=llm_config,
                quarantine_dir="quarantine",
            )

        # Should have been healed
        assert result.results[0].status == "passed"
        assert result.results[0].source is Source.HEALED
        assert result.heals_used == 1
