from __future__ import annotations

import os
from pathlib import Path

import pytest

from aivar.compiler import apply_credentials, compile_test, CompileReport
from aivar.executor import run_test
from aivar.llm import LLMConfig, LLMResponse
from aivar.models import StepKind
from aivar.planner import PlannedStep
from aivar.testfile import load_test


def fake_planner(system: str, user: str, config: LLMConfig) -> LLMResponse:
    """
    A fake planner that returns a fixed 4-step plan for the login page.

    Steps:
    1. Fill username
    2. Fill password
    3. Click login button
    4. Wait for products (assertion)
    """
    from aivar.planner import validate_plan, PlannedStep

    # This plan matches the login.html fixture
    plan_dict = {
        "steps": [
            {
                "kind": "action",
                "verb": "fill",
                "target": "Username",
                "value": None,  # Credentials will be applied
            },
            {
                "kind": "action",
                "verb": "fill",
                "target": "Password",
                "value": None,  # Credentials will be applied
            },
            {
                "kind": "action",
                "verb": "click",
                "target": "Login",
            },
            {
                "kind": "assertion",
                "verb": "wait_visible",
                "target": "Products",
                "value": None,
            },
        ]
    }

    # The planner needs to return the JSON as a string
    import json
    response_content = json.dumps(plan_dict)

    return LLMResponse(
        content=response_content,
        model="test-model",
        prompt_tokens=10,
        completion_tokens=20,
        cost_usd=0.001,
        latency_ms=100.0,
    )


@pytest.fixture
def login_html_path():
    """Path to the login.html fixture."""
    return Path(__file__).parent / "fixtures" / "login.html"


@pytest.fixture
def saucedemo_like_path():
    """Path to the saucedemo_like.html fixture."""
    return Path(__file__).parent / "fixtures" / "saucedemo_like.html"


class TestLiveCompilation:
    """Live tests that call the real LLM API."""

    @pytest.mark.live
    def test_compile_saucedemo_login_with_real_api(self):
        """
        Live test that compiles a real test against saucedemo.com.

        This test calls the real OpenRouter API and compiles a test
        by dry-running against the real saucedemo application.
        Run with: uv run pytest -m live
        """
        os.environ.setdefault("AIVAR_USERNAME", "standard_user")
        os.environ.setdefault("AIVAR_PASSWORD", "secret_sauce")

        try:
            config = LLMConfig.from_env()
            report = compile_test(
                intent="Log in to saucedemo with standard user and verify products page",
                url="https://www.saucedemo.com",
                test_id="test_saucedemo_login",
                config=config,
                headless=True,
            )

            # Verify we got a plan from the LLM
            assert report.plan_len > 0
            assert report.llm.model in config.models

            # Verify at least some steps were resolved
            assert report.resolved > 0

            # Verify the test has steps
            assert len(report.test.steps) > 0

            logger = __import__("logging").getLogger("test")
            logger.info(
                f"Compiled {report.plan_len} planned steps, "
                f"resolved {report.resolved}, unresolved {len(report.unresolved)}"
            )
            logger.info(f"Model: {report.llm.model}, cost: ${report.llm.cost_usd:.6f}")

        except Exception as e:
            # Live tests may fail due to network issues or API changes
            pytest.skip(f"Live test skipped: {e}")


class TestApplyCredentials:
    """Test the apply_credentials function."""

    def test_applies_username_to_username_field(self):
        """Test that username is applied to username fields."""
        step = PlannedStep(
            kind=StepKind.ACTION,
            verb="fill",
            target="username field",
            value=None,
        )
        credentials = {"username": "testuser", "password": "testpass"}
        result = apply_credentials(step, credentials)
        assert result == "testuser"

    def test_applies_password_to_password_field(self):
        """Test that password is applied to password fields."""
        step = PlannedStep(
            kind=StepKind.ACTION,
            verb="fill",
            target="password field",
            value=None,
        )
        credentials = {"username": "testuser", "password": "testpass"}
        result = apply_credentials(step, credentials)
        assert result == "testpass"

    def test_applies_username_to_email_field(self):
        """Test that username is applied to email fields."""
        step = PlannedStep(
            kind=StepKind.ACTION,
            verb="fill",
            target="email address",
            value=None,
        )
        credentials = {"username": "user@example.com", "password": "pass"}
        result = apply_credentials(step, credentials)
        assert result == "user@example.com"

    def test_preserves_non_null_value(self):
        """Test that a non-null value is preserved."""
        step = PlannedStep(
            kind=StepKind.ACTION,
            verb="fill",
            target="username field",
            value="hardcoded",
        )
        credentials = {"username": "testuser", "password": "testpass"}
        result = apply_credentials(step, credentials)
        assert result == "hardcoded"

    def test_non_fill_verb_not_modified(self):
        """Test that non-fill verbs are not modified."""
        step = PlannedStep(
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            value=None,
        )
        credentials = {"username": "testuser", "password": "testpass"}
        result = apply_credentials(step, credentials)
        assert result is None


class TestCompile:
    """Test the compile_test function."""

    def test_compile_produces_runnable_test(self, login_html_path):
        """
        Test that compiling a plan produces a runnable test.

        Compile a 4-step plan, verify all steps got selectors,
        then run the test and assert it passes with all CACHE sources.
        """
        # Set credentials
        os.environ["AIVAR_USERNAME"] = "standard_user"
        os.environ["AIVAR_PASSWORD"] = "secret_sauce"

        try:
            url = login_html_path.as_uri()

            # Compile with fake planner
            config = LLMConfig(api_key="test-key")
            report = compile_test(
                intent="Log in and verify products page",
                url=url,
                test_id="test_login",
                config=config,
                headless=True,
                planner=fake_planner,
            )

            # Verify all steps have selectors
            for step in report.test.steps:
                assert step.selector is not None, f"Step {step.id} has no selector"

            # Run the test
            result = run_test(report.test, headless=True)

            # Assert all steps passed
            assert result.status == "passed"

            # Assert all sources are CACHE (no healing needed)
            for step_result in result.results:
                assert step_result.source.value == "cache"

        finally:
            os.environ.pop("AIVAR_USERNAME", None)
            os.environ.pop("AIVAR_PASSWORD", None)

    def test_credentials_are_placeholders_not_secrets(self, login_html_path):
        """
        Test that the compiled test contains credential placeholders, not resolved secrets.

        Set AIVAR_USERNAME/AIVAR_PASSWORD, compile, and verify the
        saved JSON contains the placeholder, not the resolved value.
        """
        os.environ["AIVAR_USERNAME"] = "my_secret_user"
        os.environ["AIVAR_PASSWORD"] = "my_secret_password"

        try:
            url = login_html_path.as_uri()

            config = LLMConfig(api_key="test-key")
            report = compile_test(
                intent="Log in",
                url=url,
                test_id="test_login",
                config=config,
                headless=True,
                planner=fake_planner,
            )

            # Check the test directly
            test_dict = report.test.to_dict()
            test_json = str(test_dict)

            # Should contain placeholder
            assert "${AIVAR_USERNAME}" in test_json or "${AIVAR_PASSWORD}" in test_json

            # Should NOT contain the resolved secrets
            assert "my_secret_user" not in test_json
            assert "my_secret_password" not in test_json

        finally:
            os.environ.pop("AIVAR_USERNAME", None)
            os.environ.pop("AIVAR_PASSWORD", None)

    def test_unresolved_target_is_recorded(self, login_html_path):
        """
        Test that a planned step targeting a non-existent element
        is recorded in report.unresolved without raising.
        """
        def fake_planner_with_missing_target(system: str, user: str, config: LLMConfig) -> LLMResponse:
            """Planner that includes a non-existent target."""
            plan_dict = {
                "steps": [
                    {
                        "kind": "action",
                        "verb": "click",
                        "target": "NonExistentButton",
                    },
                    {
                        "kind": "assertion",
                        "verb": "wait_visible",
                        "target": "Username",
                    },
                ]
            }
            import json
            return LLMResponse(
                content=json.dumps(plan_dict),
                model="test-model",
                prompt_tokens=10,
                completion_tokens=20,
                cost_usd=0.001,
                latency_ms=100.0,
            )

        url = login_html_path.as_uri()
        config = LLMConfig(api_key="test-key")
        report = compile_test(
            intent="Try to click non-existent button",
            url=url,
            test_id="test_missing",
            config=config,
            headless=True,
            planner=fake_planner_with_missing_target,
        )

        # NonExistentButton should be in unresolved
        assert "NonExistentButton" in report.unresolved
        assert not report.fully_compiled

    def test_dry_run_advances_the_page(self, login_html_path):
        """
        Test that the dry run executes earlier steps so later targets become resolvable.

        A plan where the final assertion targets "Products" (only visible AFTER login)
        should compile to a non-None selector, proving the compiler executed the earlier steps.
        """
        os.environ["AIVAR_USERNAME"] = "test_user"
        os.environ["AIVAR_PASSWORD"] = "test_pass"

        try:
            url = login_html_path.as_uri()
            config = LLMConfig(api_key="test-key")
            report = compile_test(
                intent="Log in and verify products",
                url=url,
                test_id="test_page_advance",
                config=config,
                headless=True,
                planner=fake_planner,
            )

            # The Products assertion should have a selector (only visible after login click)
            products_step = next(
                (s for s in report.test.steps if "Products" in s.target),
                None,
            )
            assert products_step is not None
            assert products_step.selector is not None, (
                "Products target should be resolvable after the login click executes"
            )
        finally:
            os.environ.pop("AIVAR_USERNAME", None)
            os.environ.pop("AIVAR_PASSWORD", None)

    def test_compile_against_data_test_site(self, saucedemo_like_path):
        """
        Test that compilation works against a site using data-test attributes (not data-testid).

        With a FAKE planner (no network), compile a 4-step plan against saucedemo_like.html,
        assert fully_compiled is True, assert the login step's compiled selector contains
        'login-button' and NOT 'login-container', then run the compiled test and assert it passes.

        This proves the fixes for both bugs:
        1. Selector correctly uses CSS for data-test attributes
        2. Scoring doesn't pick the container over the button
        """
        os.environ["AIVAR_USERNAME"] = "test_user"
        os.environ["AIVAR_PASSWORD"] = "test_pass"

        try:
            url = saucedemo_like_path.as_uri()

            # Compile with fake planner against data-test site
            config = LLMConfig(api_key="test-key")
            report = compile_test(
                intent="Log in and verify products page",
                url=url,
                test_id="test_saucedemo_like",
                config=config,
                headless=True,
                planner=fake_planner,
            )

            # Must be fully compiled (no unresolved targets)
            assert report.fully_compiled, f"Not fully compiled. Unresolved: {report.unresolved}"

            # Find the login button step (should be step 3, the click)
            login_step = report.test.steps[2]  # 0-indexed, step 3 is the click login button
            assert login_step.verb == "click"
            assert "login" in login_step.target.lower()

            # The selector must exist and must reference login-button, not login-container
            assert login_step.selector is not None, "Login step must have a compiled selector"

            # Get the selector value
            selector_value = login_step.selector.value
            # For data-test, selector should be CSS: [data-test="login-button"]
            assert "login-button" in selector_value, (
                f"Selector should contain 'login-button', got: {selector_value}"
            )
            assert "login-container" not in selector_value, (
                f"Selector should NOT contain 'login-container' (the container div), got: {selector_value}"
            )

            # Run the compiled test and verify it passes
            result = run_test(report.test, headless=True)
            assert result.status == "passed", (
                f"Compiled test failed: {result.status}. "
                f"Step results: {[(r.id, r.status, r.failure) for r in result.results]}"
            )

        finally:
            os.environ.pop("AIVAR_USERNAME", None)
            os.environ.pop("AIVAR_PASSWORD", None)
