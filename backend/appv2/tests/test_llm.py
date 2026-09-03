from __future__ import annotations

import os
from pathlib import Path

import pytest

from aivar.envfile import load_env_file, load_dotenv
from aivar.llm import (
    LLMConfig,
    LLMError,
    LLMInvalidJSON,
    extract_json,
)


class TestExtractJson:
    """Test the extract_json function."""

    def test_bare_json(self):
        """Test extracting bare JSON."""
        text = '{"key": "value"}'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_json_with_markdown_json_fence(self):
        """Test extracting JSON with ```json fence."""
        text = '```json\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_json_with_markdown_fence(self):
        """Test extracting JSON with ``` fence."""
        text = '```\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_json_with_prose_prefix(self):
        """Test extracting JSON with prose before it."""
        text = 'Here is the plan:\n{"steps": [{"kind": "action"}]}'
        result = extract_json(text)
        assert result == {"steps": [{"kind": "action"}]}

    def test_invalid_json(self):
        """Test that invalid JSON raises LLMInvalidJSON."""
        text = "not valid json at all"
        with pytest.raises(LLMInvalidJSON):
            extract_json(text)


class TestLoadEnvFile:
    """Test the load_env_file function."""

    def test_loads_basic_key_value(self, tmp_path):
        """Test loading a basic key=value pair."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        result = load_env_file(env_file)
        assert result == {"KEY": "value"}

    def test_strips_whitespace_around_equals(self, tmp_path):
        """Test that whitespace around = is stripped."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENROUTER_API_KEY = 'sk-or-v1-abc'\n")
        result = load_env_file(env_file)
        assert result == {"OPENROUTER_API_KEY": "sk-or-v1-abc"}

    def test_strips_single_quotes(self, tmp_path):
        """Test that single quotes are stripped."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY='value'\n")
        result = load_env_file(env_file)
        assert result == {"KEY": "value"}

    def test_strips_double_quotes(self, tmp_path):
        """Test that double quotes are stripped."""
        env_file = tmp_path / ".env"
        env_file.write_text('KEY="value"\n')
        result = load_env_file(env_file)
        assert result == {"KEY": "value"}

    def test_skips_blank_lines(self, tmp_path):
        """Test that blank lines are skipped."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\n\nKEY2=value2\n")
        result = load_env_file(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_skips_comment_lines(self, tmp_path):
        """Test that comment lines are skipped."""
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nKEY=value\n")
        result = load_env_file(env_file)
        assert result == {"KEY": "value"}

    def test_handles_missing_file(self):
        """Test that a missing file returns an empty dict."""
        result = load_env_file(Path("/nonexistent/path/.env"))
        assert result == {}


class TestLoadDotenv:
    """Test the load_dotenv function."""

    def test_loads_from_parent_directory(self, tmp_path, monkeypatch):
        """Test that load_dotenv finds .env in the parent directory."""
        # Create .env in tmp_path
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY=test_value\n")

        # Create a subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        # Call load_dotenv from the subdirectory
        monkeypatch.delenv("TEST_KEY", raising=False)
        load_dotenv(subdir)

        assert os.environ.get("TEST_KEY") == "test_value"

    def test_does_not_overwrite_existing_env_var(self, tmp_path, monkeypatch):
        """Test that load_dotenv does not overwrite existing env vars."""
        # Create .env in tmp_path
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY=new_value\n")

        # Set an existing env var
        monkeypatch.setenv("TEST_KEY", "existing_value")

        # Call load_dotenv
        load_dotenv(tmp_path)

        # Should NOT be overwritten
        assert os.environ.get("TEST_KEY") == "existing_value"

        # Clean up
        monkeypatch.delenv("TEST_KEY")


class TestLLMConfigFromEnv:
    """Test LLMConfig.from_env."""

    def test_raises_error_when_api_key_missing(self, tmp_path, monkeypatch):
        """Test that LLMConfig.from_env raises LLMError when API key is absent."""
        # Remove the API key if it exists
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        # Create an empty .env file
        env_file = tmp_path / ".env"
        env_file.write_text("")

        # Mock load_dotenv to do nothing (we're testing the error path)
        def mock_load_dotenv(start=None):
            pass

        monkeypatch.setattr("aivar.llm.load_dotenv", mock_load_dotenv)

        with pytest.raises(LLMError) as exc_info:
            LLMConfig.from_env()

        assert "OPENROUTER_API_KEY" in str(exc_info.value)

    def test_loads_from_environment(self, monkeypatch):
        """Test that LLMConfig.from_env loads from the environment."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")

        def mock_load_dotenv(start=None):
            pass

        monkeypatch.setattr("aivar.llm.load_dotenv", mock_load_dotenv)

        config = LLMConfig.from_env()
        assert config.api_key == "test-key-123"

    def test_loads_custom_models_from_env(self, monkeypatch):
        """Test that LLMConfig.from_env loads custom models from AIVAR_LLM_MODELS."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
        monkeypatch.setenv("AIVAR_LLM_MODELS", "model1, model2, model3")

        def mock_load_dotenv(start=None):
            pass

        monkeypatch.setattr("aivar.llm.load_dotenv", mock_load_dotenv)

        config = LLMConfig.from_env()
        assert config.models == ("model1", "model2", "model3")
