from __future__ import annotations

import json
from pathlib import Path

import pytest

from aivar.config import Guardrails
from aivar.executor import SelectorConfigError, run_test
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
def fixture_url() -> str:
    """Return a file:// URL to the local login.html fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "login.html"
    return fixture_path.resolve().as_uri()


@pytest.fixture
def saucedemo_fixture_url() -> str:
    """Return a file:// URL to the saucedemo_like.html fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "saucedemo_like.html"
    return fixture_path.resolve().as_uri()


def make_test(url: str, steps: list[Step]) -> CompiledTest:
    """Helper to build a CompiledTest."""
    return CompiledTest(
        id="test-1",
        intent="Test intent",
        url=url,
        steps=steps,
        version=1,
    )


class TestHappyPath:
    """Happy path: fill username, fill password, click Login, assert Products visible."""

    def test_happy_path(self, fixture_url: str):
        """All steps pass, all have source=cache, no failures."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="fill",
                target="username",
                value="test",
                selector=Selector(strategy="placeholder", value="Username"),
            ),
            Step(
                id="s2",
                kind=StepKind.ACTION,
                verb="fill",
                target="password",
                value="test",
                selector=Selector(strategy="placeholder", value="Password"),
            ),
            Step(
                id="s3",
                kind=StepKind.ACTION,
                verb="click",
                target="button",
                selector=Selector(strategy="css", value="#login"),
            ),
            Step(
                id="s4",
                kind=StepKind.ASSERTION,
                verb="wait_visible",
                target="products",
                selector=Selector(strategy="text", value="Products"),
            ),
        ]
        test = make_test(fixture_url, steps)
        result = run_test(test, headless=True)

        assert result.status == "passed"
        assert len(result.results) == 4
        for step_result in result.results:
            assert step_result.status == "passed"
            assert step_result.source == Source.CACHE
            assert step_result.failure is None


class TestActionMissingElement:
    """Action step with a missing element should fail with LOCATOR_NOT_FOUND."""

    def test_action_missing_element(self, fixture_url: str):
        """Action targeting nonexistent element → LOCATOR_NOT_FOUND."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="click",
                target="nonexistent",
                selector=Selector(strategy="css", value="#doesnotexist"),
            ),
        ]
        test = make_test(fixture_url, steps)
        guardrails = Guardrails(action_timeout_ms=500)
        result = run_test(test, guardrails=guardrails, headless=True)

        assert result.status == "failed"
        assert len(result.results) == 1
        step_result = result.results[0]
        assert step_result.status == "failed"
        assert step_result.failure == FailureKind.LOCATOR_NOT_FOUND


class TestAssertionNeverReportsLocatorNotFound:
    """
    CRITICAL: An ASSERTION step targeting a missing element must report
    ASSERTION_FAILED, never LOCATOR_NOT_FOUND.

    This is the rule that prevents real bugs from being auto-healed later.
    If an assertion fails because the element is missing, that's a candidate bug,
    not a candidate selector repair.
    """

    def test_assertion_missing_element(self, fixture_url: str):
        """Assertion targeting nonexistent element → ASSERTION_FAILED, not LOCATOR_NOT_FOUND."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ASSERTION,
                verb="wait_visible",
                target="nonexistent",
                selector=Selector(strategy="css", value="#doesnotexist"),
            ),
        ]
        test = make_test(fixture_url, steps)
        guardrails = Guardrails(action_timeout_ms=500)
        result = run_test(test, guardrails=guardrails, headless=True)

        assert result.status == "failed"
        assert len(result.results) == 1
        step_result = result.results[0]
        assert step_result.status == "failed"

        # CRITICAL CHECK: This must be ASSERTION_FAILED, never LOCATOR_NOT_FOUND
        assert step_result.failure == FailureKind.ASSERTION_FAILED
        assert step_result.failure != FailureKind.LOCATOR_NOT_FOUND


class TestStepsSkippedAfterFailure:
    """Steps after a failure should be recorded as skipped and not executed."""

    def test_skip_steps_after_failure(self, fixture_url: str):
        """First step fails, next two are skipped."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="click",
                target="nonexistent",
                selector=Selector(strategy="css", value="#doesnotexist"),
            ),
            Step(
                id="s2",
                kind=StepKind.ACTION,
                verb="fill",
                target="username",
                value="test",
                selector=Selector(strategy="placeholder", value="Username"),
            ),
            Step(
                id="s3",
                kind=StepKind.ACTION,
                verb="click",
                target="button",
                selector=Selector(strategy="css", value="#login"),
            ),
        ]
        test = make_test(fixture_url, steps)
        guardrails = Guardrails(action_timeout_ms=500)
        result = run_test(test, guardrails=guardrails, headless=True)

        assert result.status == "failed"
        assert len(result.results) == 3
        assert result.results[0].status == "failed"
        assert result.results[0].failure == FailureKind.LOCATOR_NOT_FOUND
        assert result.results[1].status == "skipped"
        assert result.results[2].status == "skipped"


class TestUncompiledActionStep:
    """Action step with selector=None (uncompiled) should report LOCATOR_NOT_FOUND."""

    def test_uncompiled_action_step(self, fixture_url: str):
        """Uncompiled action step (selector=None) → LOCATOR_NOT_FOUND."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="click",
                target="button",
                selector=None,
            ),
        ]
        test = make_test(fixture_url, steps)
        result = run_test(test, headless=True)

        assert result.status == "failed"
        assert len(result.results) == 1
        step_result = result.results[0]
        assert step_result.status == "failed"
        assert step_result.failure == FailureKind.LOCATOR_NOT_FOUND


class TestMalformedSelector:
    """Malformed selector (e.g., role strategy with role=None) should report AGENT_ERROR."""

    def test_malformed_selector_role_without_role(self, fixture_url: str):
        """role strategy without role field → AGENT_ERROR."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="click",
                target="button",
                selector=Selector(strategy="role", value="Login", role=None),
            ),
        ]
        test = make_test(fixture_url, steps)
        result = run_test(test, headless=True)

        assert result.status == "error"
        assert len(result.results) == 1
        step_result = result.results[0]
        assert step_result.status == "failed"
        assert step_result.failure == FailureKind.AGENT_ERROR


class TestTestfileRoundTrip:
    """save_test then load_test should produce an equivalent CompiledTest."""

    def test_round_trip(self, tmp_path: Path):
        """Save and load a test, compare to_dict()."""
        original_steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="fill",
                target="username",
                value="test",
                selector=Selector(strategy="placeholder", value="Username"),
            ),
            Step(
                id="s2",
                kind=StepKind.ACTION,
                verb="click",
                target="button",
                selector=Selector(strategy="css", value="#login"),
            ),
        ]
        original_test = CompiledTest(
            id="test-round-trip",
            intent="Round trip test",
            url="http://example.com",
            steps=original_steps,
            version=1,
        )

        test_file = tmp_path / "test.json"
        save_test(original_test, test_file)
        loaded_test = load_test(test_file)

        assert loaded_test.to_dict() == original_test.to_dict()


class TestExamplesLoginJson:
    """examples/login.json should load cleanly and have the expected structure."""

    def test_examples_login_loads(self):
        """Load examples/login.json and verify it has 4 steps, last is assertion."""
        examples_dir = Path(__file__).parent.parent / "examples"
        login_file = examples_dir / "login.json"
        assert login_file.exists(), f"examples/login.json not found at {login_file}"

        test = load_test(login_file)

        assert test.id == "saucedemo-login"
        assert test.intent == "Log in with valid credentials and verify the products page loads"
        assert test.url == "https://www.saucedemo.com"
        assert test.version == 1
        assert len(test.steps) == 4

        # Check last step is assertion
        last_step = test.steps[-1]
        assert last_step.kind == StepKind.ASSERTION


class TestTier1HeuristicResolution:
    """Test Tier 1 cascade for ACTION steps with selector=None."""

    def test_tier1_resolves_uncompiled_action_step(self, fixture_url: str):
        """ACTION step with selector=None and a heuristic match should pass with source=HEURISTIC."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="fill",
                target="username",
                value="test",
                selector=None,  # Uncompiled, will use Tier 1
            ),
            Step(
                id="s2",
                kind=StepKind.ACTION,
                verb="fill",
                target="password",
                value="test",
                selector=Selector(strategy="placeholder", value="Password"),
            ),
            Step(
                id="s3",
                kind=StepKind.ACTION,
                verb="click",
                target="login submit",
                selector=None,  # Uncompiled, will use Tier 1
            ),
            Step(
                id="s4",
                kind=StepKind.ASSERTION,
                verb="wait_visible",
                target="products",
                selector=Selector(strategy="text", value="Products"),
            ),
        ]
        test = make_test(fixture_url, steps)
        result = run_test(test, headless=True)

        # First step should pass with HEURISTIC source (matched the input via placeholder)
        assert result.results[0].status == "passed", (
            f"Step 1 failed: {result.results[0].failure}, {result.results[0].error}"
        )
        assert result.results[0].source == Source.HEURISTIC
        assert result.results[0].failure is None

        # Third step (login button) should also pass with HEURISTIC
        # The data-testid="login-submit" button will be selected via heuristic matching
        assert result.results[2].status == "passed"
        assert result.results[2].source == Source.HEURISTIC


class TestAssertionHasNoTier1Fallback:
    """
    Test that ASSERTION steps have NO Tier 1 fallback.
    This is the anti-masking rule: if an assertion fails because the element is missing,
    that's a candidate bug, not a lookup problem to route around.
    """

    def test_assertion_fails_without_tier1_resolution(self, fixture_url: str):
        """ASSERTION step with selector=None should fail with ASSERTION_FAILED, not use Tier 1."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="click",
                target="login button",
                selector=Selector(strategy="testid", value="login-submit"),
            ),
            Step(
                id="s2",
                kind=StepKind.ASSERTION,
                verb="wait_visible",
                target="products header",
                selector=None,  # Uncompiled assertion
            ),
        ]
        test = make_test(fixture_url, steps)
        result = run_test(test, headless=True)

        # Second step is an ASSERTION and should fail with ASSERTION_FAILED
        assert result.results[1].status == "failed"
        assert result.results[1].failure == FailureKind.ASSERTION_FAILED
        # Critically: it should NOT be HEURISTIC source or find a match via Tier 1
        assert result.results[1].source != Source.HEURISTIC


class TestSecretSubstitutionInFill:
    """Test that secret values are resolved during step execution."""

    def test_secret_substitution_in_fill(self, fixture_url: str, monkeypatch):
        """A step with value '${MY_USER}' should resolve from env and fill the input."""
        monkeypatch.setenv("MY_USER", "resolved_user")
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="fill",
                target="username",
                value="${MY_USER}",
                selector=Selector(strategy="placeholder", value="Username"),
            ),
        ]
        test = make_test(fixture_url, steps)
        result = run_test(test, headless=True)

        assert result.status == "passed"
        assert result.results[0].status == "passed"


class TestMissingSecretIsAgentError:
    """Test that a missing required secret causes AGENT_ERROR."""

    def test_missing_secret_raises_agent_error(self, fixture_url: str):
        """A step with value '${UNDEFINED_SECRET}' should fail with AGENT_ERROR."""
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="fill",
                target="username",
                value="${AIVAR_DEFINITELY_NOT_SET}",
                selector=Selector(strategy="placeholder", value="Username"),
            ),
        ]
        test = make_test(fixture_url, steps)
        result = run_test(test, headless=True)

        assert result.status == "error"
        assert result.results[0].status == "failed"
        assert result.results[0].failure == FailureKind.AGENT_ERROR
        assert "environment variable" in result.results[0].error


class TestTier1DataTestSite:
    """Test Tier 1 resolution on a site using data-test attributes (not data-testid)."""

    def test_tier1_resolves_data_test_site_end_to_end(self, saucedemo_fixture_url: str):
        """
        Using saucedemo_like.html (with data-test attributes), build a CompiledTest
        with three ACTION steps having selector=None and one ASSERTION with explicit selector.
        The three ACTION steps must resolve via Tier 1 and the whole run must PASS.

        This proves the fix works end-to-end on a site shaped like the real one.
        """
        steps = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="fill",
                target="username",
                value="test",
                selector=None,  # Uncompiled, will use Tier 1
            ),
            Step(
                id="s2",
                kind=StepKind.ACTION,
                verb="fill",
                target="password",
                value="test",
                selector=None,  # Uncompiled, will use Tier 1
            ),
            Step(
                id="s3",
                kind=StepKind.ACTION,
                verb="click",
                target="login button",
                selector=None,  # Uncompiled, will use Tier 1
            ),
            Step(
                id="s4",
                kind=StepKind.ASSERTION,
                verb="wait_visible",
                target="products",
                # Assertion gets explicit selector (assertions have no Tier 1 fallback)
                selector=Selector(strategy="css", value='[data-test="title"]'),
            ),
        ]
        test = make_test(saucedemo_fixture_url, steps)
        result = run_test(test, headless=True)

        # All steps must pass
        assert result.status == "passed", (
            f"Test failed: {result.status}. "
            f"Step results: {[(r.id, r.status, r.failure) for r in result.results]}"
        )

        # First three steps must use HEURISTIC source (Tier 1 resolved)
        assert result.results[0].status == "passed"
        assert result.results[0].source == Source.HEURISTIC

        assert result.results[1].status == "passed"
        assert result.results[1].source == Source.HEURISTIC

        assert result.results[2].status == "passed"
        assert result.results[2].source == Source.HEURISTIC

        # Fourth step (assertion) uses its explicit selector
        assert result.results[3].status == "passed"
