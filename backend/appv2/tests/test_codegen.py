"""Tests for the codegen module that renders flows into pytest files."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from aivar.codegen import (
    is_importable,
    locator_expr,
    render_pytest,
    sanitize_identifier,
    write_flow_file,
    write_suite,
)
from aivar.contracts import Flow, FlowKind
from aivar.models import Selector, Step, StepKind


class TestLocatorExpr:
    """Test locator_expr for all selector strategies."""

    def test_role_strategy(self):
        """Test role strategy produces get_by_role."""
        selector = Selector(strategy="role", value="Login", role="button")
        result = locator_expr(selector)
        assert result == "page.get_by_role('button', name='Login')"

    def test_label_strategy(self):
        """Test label strategy produces get_by_label."""
        selector = Selector(strategy="label", value="Username")
        result = locator_expr(selector)
        assert result == "page.get_by_label('Username')"

    def test_placeholder_strategy(self):
        """Test placeholder strategy produces get_by_placeholder."""
        selector = Selector(strategy="placeholder", value="Enter email")
        result = locator_expr(selector)
        assert result == "page.get_by_placeholder('Enter email')"

    def test_text_strategy(self):
        """Test text strategy produces get_by_text."""
        selector = Selector(strategy="text", value="Submit")
        result = locator_expr(selector)
        assert result == "page.get_by_text('Submit')"

    def test_testid_strategy(self):
        """Test testid strategy produces get_by_test_id."""
        selector = Selector(strategy="testid", value="login-button")
        result = locator_expr(selector)
        assert result == "page.get_by_test_id('login-button')"

    def test_css_strategy(self):
        """Test css strategy produces locator."""
        selector = Selector(strategy="css", value=".btn-primary")
        result = locator_expr(selector)
        assert result == "page.locator('.btn-primary')"

    def test_value_with_double_quote(self):
        """Test that a value with double quotes is properly escaped."""
        selector = Selector(strategy="text", value='Login "now"')
        result = locator_expr(selector)
        # repr() should escape the quotes
        assert "\\\"" in result or result == 'page.get_by_text(\'Login "now"\')'
        # Verify the expression is syntactically valid Python
        assert ast.parse(f"x = {result}") is not None


class TestSanitizeIdentifier:
    """Test sanitize_identifier with various inputs."""

    def test_simple_name(self):
        """Test a simple valid identifier."""
        assert sanitize_identifier("login_flow") == "login_flow"

    def test_uppercase_converts_to_lowercase(self):
        """Test that uppercase is converted to lowercase."""
        assert sanitize_identifier("LoginFlow") == "loginflow"

    def test_spaces_become_underscores(self):
        """Test that spaces are converted to underscores."""
        assert sanitize_identifier("login user flow") == "login_user_flow"

    def test_punctuation_becomes_underscores(self):
        """Test that punctuation is converted to underscores."""
        assert sanitize_identifier("login-flow!") == "login_flow"
        assert sanitize_identifier("login.flow") == "login_flow"

    def test_consecutive_underscores_collapse(self):
        """Test that consecutive underscores are collapsed."""
        assert sanitize_identifier("login___flow") == "login_flow"

    def test_leading_underscores_stripped(self):
        """Test that leading underscores are stripped."""
        assert sanitize_identifier("___login") == "login"

    def test_trailing_underscores_stripped(self):
        """Test that trailing underscores are stripped."""
        assert sanitize_identifier("login___") == "login"

    def test_leading_digit_prefix_with_t_(self):
        """Test that identifiers starting with digits get prefixed."""
        assert sanitize_identifier("3-step-flow") == "t_3_step_flow"

    def test_all_digits(self):
        """Test that all-digit string gets prefixed."""
        assert sanitize_identifier("123") == "t_123"

    def test_empty_string_fallback(self):
        """Test that empty string falls back to 'flow'."""
        assert sanitize_identifier("") == "flow"

    def test_special_chars_only_fallback(self):
        """Test that string with only special chars falls back to 'flow'."""
        assert sanitize_identifier("!@#$%") == "flow"


class TestRenderPytest:
    """Test render_pytest output."""

    def test_render_basic_flow(self):
        """Test rendering a simple flow."""
        step1 = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="login-button",
            selector=Selector(strategy="testid", value="login-button"),
        )
        flow = Flow(
            id="f1",
            name="Test Login",
            description="Login test",
            kind=FlowKind.HAPPY_PATH,
            steps=[step1],
        )
        result = render_pytest(flow, "https://example.com")

        # Check structure
        assert "Generated by the aivar orchestration agent" in result
        assert "Flow ID: f1" in result
        assert "Flow name: Test Login" in result
        assert "Regenerate rather than edit by hand" in result
        assert "import os" in result
        assert "from playwright.sync_api import Page, expect" in result
        assert "def test_test_login(page: Page):" in result
        assert 'page.goto(\'https://example.com\')' in result
        assert "page.get_by_test_id('login-button').first.click()" in result

    def test_render_uses_entry_url_if_present(self):
        """Test that entry_url is used instead of url parameter."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="css", value="button"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
            entry_url="https://custom.example.com",
        )
        result = render_pytest(flow, "https://default.example.com")
        assert "https://custom.example.com" in result

    def test_render_output_passes_ast_parse(self):
        """Test that the generated code is valid Python."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="css", value="button"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        result = render_pytest(flow, "https://example.com")
        # Should not raise SyntaxError
        ast.parse(result)

    def test_render_uncompiled_flow_raises(self):
        """Test that rendering an uncompiled flow raises ValueError."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=None,  # Not compiled
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        with pytest.raises(ValueError, match="not compiled"):
            render_pytest(flow, "https://example.com")


class TestSecretHandling:
    """Test that secret placeholders are properly handled."""

    def test_password_env_var_not_inlined(self):
        """Test that ${AIVAR_PASSWORD} doesn't inline the secret."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="fill",
            target="password-field",
            value="${AIVAR_PASSWORD}",
            selector=Selector(strategy="testid", value="password"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        result = render_pytest(flow, "https://example.com")

        # Should use os.environ (flexible on quote style)
        assert "os.environ" in result and "AIVAR_PASSWORD" in result
        # Should NOT contain any likely password value
        assert "secret" not in result.lower()

    def test_placeholder_with_default_value(self):
        """Test that ${X:-fallback} renders os.environ.get."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="fill",
            target="username",
            value="${AIVAR_USERNAME:-admin}",
            selector=Selector(strategy="testid", value="username"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        result = render_pytest(flow, "https://example.com")

        # Should use os.environ.get with default (flexible on quote style)
        assert "os.environ.get" in result and "AIVAR_USERNAME" in result and "admin" in result

    def test_plain_literal_value(self):
        """Test that plain values are quoted strings."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="fill",
            target="username",
            value="admin",
            selector=Selector(strategy="testid", value="username"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        result = render_pytest(flow, "https://example.com")

        # Should be a quoted string
        assert "'admin'" in result or '"admin"' in result


class TestStepKindHandling:
    """Test that ACTION and ASSERTION wait_visible are handled differently."""

    def test_assertion_wait_visible_uses_expect(self):
        """Test that ASSERTION step with wait_visible uses expect."""
        step = Step(
            id="s1",
            kind=StepKind.ASSERTION,
            verb="wait_visible",
            target="success-message",
            selector=Selector(strategy="text", value="Success!"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        result = render_pytest(flow, "https://example.com")

        # Should use expect
        assert "expect(" in result
        assert "to_be_visible()" in result
        # Should NOT use wait_for
        assert "wait_for" not in result

    def test_action_wait_visible_uses_wait_for(self):
        """Test that ACTION step with wait_visible uses wait_for."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="wait_visible",
            target="loading-indicator",
            selector=Selector(strategy="testid", value="loading"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        result = render_pytest(flow, "https://example.com")

        # Should use wait_for
        assert 'wait_for(state="visible")' in result
        # Should NOT use expect
        assert "expect(" not in result or "expect(" in result and "to_be_visible()" not in result


class TestWriteFlowFile:
    """Test write_flow_file function."""

    def test_write_flow_file_creates_directory(self, tmp_path):
        """Test that write_flow_file creates the output directory."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="css", value="button"),
        )
        flow = Flow(
            id="f1",
            name="my test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        out_dir = tmp_path / "nested" / "output"
        result = write_flow_file(flow, "https://example.com", out_dir)

        # Check directory was created
        assert out_dir.exists()
        # Check file was written
        assert result.exists()
        assert result.name == "test_my_test.py"

    def test_write_flow_file_content_is_valid(self, tmp_path):
        """Test that the written file is valid Python."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="css", value="button"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        result = write_flow_file(flow, "https://example.com", tmp_path)

        # Verify the file is valid Python
        ok, err = is_importable(result)
        assert ok, f"File is not importable: {err}"


class TestWriteSuite:
    """Test write_suite function."""

    def test_write_suite_skips_uncompiled_flows(self, tmp_path):
        """Test that write_suite skips uncompiled flows."""
        compiled_step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="css", value="button"),
        )
        uncompiled_step = Step(
            id="s2",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=None,  # Not compiled
        )
        compiled_flow = Flow(
            id="f1",
            name="compiled",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[compiled_step],
        )
        uncompiled_flow = Flow(
            id="f2",
            name="uncompiled",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[uncompiled_step],
        )

        result = write_suite([compiled_flow, uncompiled_flow], "https://example.com", tmp_path)

        # Should only write the compiled flow
        assert len(result) == 1
        assert "compiled" in result[0].name

    def test_write_suite_creates_conftest(self, tmp_path):
        """Test that write_suite creates conftest.py."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="css", value="button"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )

        write_suite([flow], "https://example.com", tmp_path)

        # Check conftest.py was created
        conftest = tmp_path / "conftest.py"
        assert conftest.exists()
        content = conftest.read_text()
        assert "ignore_https_errors" in content
        assert "browser_context_args" in content

    def test_write_suite_doesnt_overwrite_conftest(self, tmp_path):
        """Test that write_suite doesn't overwrite existing conftest.py."""
        # Create an existing conftest
        conftest = tmp_path / "conftest.py"
        original_content = "# Original conftest\nMARKER = 'original'\n"
        conftest.write_text(original_content)

        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="css", value="button"),
        )
        flow = Flow(
            id="f1",
            name="test",
            description="",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )

        write_suite([flow], "https://example.com", tmp_path)

        # Check conftest wasn't overwritten
        content = conftest.read_text()
        assert content == original_content


class TestIsImportable:
    """Test is_importable function."""

    def test_valid_python_file(self, tmp_path):
        """Test that a valid Python file passes."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")
        ok, err = is_importable(test_file)
        assert ok is True
        assert err == ""

    def test_invalid_python_file(self, tmp_path):
        """Test that an invalid Python file fails."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = \n")  # Syntax error
        ok, err = is_importable(test_file)
        assert ok is False
        assert err  # Error message should be present

    def test_nonexistent_file(self, tmp_path):
        """Test that nonexistent file returns error."""
        test_file = tmp_path / "nonexistent.py"
        ok, err = is_importable(test_file)
        assert ok is False
        assert err


class TestGeneratedFileActuallyRuns:
    """Test that a generated file can actually run with pytest."""

    def test_generated_file_actually_runs(self, tmp_path):
        """Test end-to-end: generate a flow and run it with pytest."""
        # Use the actual saucedemo_like.html fixture
        fixture_path = Path(__file__).parent / "fixtures" / "saucedemo_like.html"
        assert fixture_path.exists(), f"Fixture not found at {fixture_path}"

        # Create a Flow that tests the login form
        # Note: fixture uses data-test, not data-testid, so we use CSS selectors
        step1 = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="fill",
            target="username-input",
            value="standard_user",
            selector=Selector(strategy="css", value="#user-name"),
        )
        step2 = Step(
            id="s2",
            kind=StepKind.ACTION,
            verb="fill",
            target="password-input",
            value="secret_sauce",
            selector=Selector(strategy="css", value="#password"),
        )
        step3 = Step(
            id="s3",
            kind=StepKind.ACTION,
            verb="click",
            target="login-button",
            selector=Selector(strategy="css", value="#login-button"),
        )
        step4 = Step(
            id="s4",
            kind=StepKind.ASSERTION,
            verb="wait_visible",
            target="products-title",
            selector=Selector(strategy="css", value="#products"),
        )

        flow = Flow(
            id="f1",
            name="login test",
            description="Test the login flow",
            kind=FlowKind.HAPPY_PATH,
            steps=[step1, step2, step3, step4],
        )

        # Convert fixture path to file:// URL
        url = fixture_path.resolve().as_uri()

        # Write the flow to the temp directory
        out_dir = tmp_path / "tests"
        write_suite([flow], url, out_dir)

        # Find the generated test file
        test_files = list(out_dir.glob("test_*.py"))
        assert len(test_files) > 0, "No test files generated"
        test_file = test_files[0]

        # Run pytest on the generated file
        # Timeout is set high because launching a real browser takes time
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # The test should pass (returncode 0)
        assert result.returncode == 0, f"pytest failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
