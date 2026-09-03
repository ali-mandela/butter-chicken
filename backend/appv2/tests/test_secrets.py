from __future__ import annotations

import os

import pytest

from aivar.secrets import (
    MissingSecretError,
    PLACEHOLDER_RE,
    contains_placeholder,
    redact,
    resolve_value,
)


class TestPlaceholderRegex:
    """Test the PLACEHOLDER_RE regex."""

    def test_matches_simple_placeholder(self):
        """${NAME} should be matched."""
        match = PLACEHOLDER_RE.search("${FOO}")
        assert match is not None
        assert match.group(1) == "FOO"
        assert match.group(2) is None

    def test_matches_placeholder_with_default(self):
        """${NAME:-default} should be matched."""
        match = PLACEHOLDER_RE.search("${FOO:-bar}")
        assert match is not None
        assert match.group(1) == "FOO"
        assert match.group(2) == "bar"

    def test_does_not_match_lowercase(self):
        """${foo} should not be matched (lowercase not allowed)."""
        match = PLACEHOLDER_RE.search("${foo}")
        assert match is None

    def test_does_not_match_invalid_chars_in_name(self):
        """${FOO-BAR} should not be matched (hyphen not allowed in name)."""
        match = PLACEHOLDER_RE.search("${FOO-BAR}")
        assert match is None


class TestResolveValue:
    """Test resolve_value function."""

    def test_none_returns_none(self):
        """None input should return None."""
        assert resolve_value(None) is None

    def test_no_placeholder_returns_unchanged(self):
        """A string with no placeholders should be returned unchanged."""
        assert resolve_value("hello world") == "hello world"

    def test_simple_placeholder_resolves_from_env(self, monkeypatch):
        """${NAME} should resolve from environment variable."""
        monkeypatch.setenv("MY_VAR", "my_value")
        assert resolve_value("${MY_VAR}") == "my_value"

    def test_missing_placeholder_raises_error(self):
        """${NAME} should raise MissingSecretError if not in environment."""
        with pytest.raises(
            MissingSecretError,
            match="environment variable MISSING_VAR is not set",
        ):
            resolve_value("${MISSING_VAR}")

    def test_placeholder_with_default_uses_default(self):
        """${NAME:-default} should use default when env var not set."""
        assert resolve_value("${UNSET_VAR:-fallback}") == "fallback"

    def test_placeholder_with_default_uses_env_when_set(self, monkeypatch):
        """${NAME:-default} should use env value when set."""
        monkeypatch.setenv("MYVAR", "env_value")
        assert resolve_value("${MYVAR:-fallback}") == "env_value"

    def test_multiple_placeholders_in_string(self, monkeypatch):
        """Multiple placeholders in one string should all be replaced."""
        monkeypatch.setenv("USER", "alice")
        monkeypatch.setenv("PASS", "secret")
        result = resolve_value("user=${USER}&password=${PASS}")
        assert result == "user=alice&password=secret"

    def test_mixed_placeholders_and_defaults(self, monkeypatch):
        """Mix of placeholders with and without defaults."""
        monkeypatch.setenv("SET_VAR", "from_env")
        result = resolve_value("a=${SET_VAR:-default1}&b=${UNSET_VAR:-default2}")
        assert result == "a=from_env&b=default2"


class TestContainsPlaceholder:
    """Test contains_placeholder function."""

    def test_none_returns_false(self):
        """None should return False."""
        assert contains_placeholder(None) is False

    def test_no_placeholder_returns_false(self):
        """A string with no placeholders should return False."""
        assert contains_placeholder("hello world") is False

    def test_simple_placeholder_returns_true(self):
        """A string with a placeholder should return True."""
        assert contains_placeholder("${MY_VAR}") is True

    def test_placeholder_with_default_returns_true(self):
        """A string with a defaulted placeholder should return True."""
        assert contains_placeholder("${MY_VAR:-default}") is True


class TestRedact:
    """Test redact function."""

    def test_none_returns_empty_string(self):
        """None should return empty string."""
        assert redact(None) == ""

    def test_no_placeholder_returns_value(self):
        """A value with no placeholders should return the value itself."""
        assert redact("my_password") == "my_password"

    def test_placeholder_returns_asterisks(self):
        """A value with a placeholder should return '***'."""
        assert redact("${MY_VAR}") == "***"

    def test_placeholder_with_default_returns_asterisks(self):
        """A value with a defaulted placeholder should return '***'."""
        assert redact("${MY_VAR:-default}") == "***"

    def test_text_with_embedded_placeholder_returns_asterisks(self):
        """Text with an embedded placeholder should return '***'."""
        assert redact("user=${MY_VAR}&pass=foo") == "***"
