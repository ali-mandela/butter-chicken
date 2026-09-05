import os
import pytest
from aivar.config import Guardrails, DEFAULTS


def test_defaults_match_spec():
    """Test that defaults match the spec."""
    assert DEFAULTS.max_heals_per_run == 3
    assert DEFAULTS.min_heal_confidence == 0.5
    assert DEFAULTS.require_semantic_match is True
    assert DEFAULTS.heal_assertions is False
    assert DEFAULTS.max_cost_per_run_usd == 0.50
    assert DEFAULTS.action_retries == 2
    assert DEFAULTS.action_timeout_ms == 8000


def test_heal_assertions_true_raises():
    """Test that Guardrails(heal_assertions=True) raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        Guardrails(heal_assertions=True)
    assert "heal_assertions must never be True" in str(exc_info.value)


def test_min_heal_confidence_out_of_range():
    """Test that out-of-range min_heal_confidence raises."""
    with pytest.raises(ValueError):
        Guardrails(min_heal_confidence=-0.1)
    with pytest.raises(ValueError):
        Guardrails(min_heal_confidence=1.1)


def test_negative_max_heals_per_run():
    """Test that negative max_heals_per_run raises."""
    with pytest.raises(ValueError):
        Guardrails(max_heals_per_run=-1)


def test_from_env_picks_up_max_heals(monkeypatch):
    """Test that from_env picks up AIVAR_MAX_HEALS_PER_RUN."""
    monkeypatch.setenv("AIVAR_MAX_HEALS_PER_RUN", "7")
    g = Guardrails.from_env()
    assert g.max_heals_per_run == 7


def test_from_env_ignores_heal_assertions_env(monkeypatch):
    """Test that from_env ignores AIVAR_HEAL_ASSERTIONS and result stays False."""
    monkeypatch.setenv("AIVAR_HEAL_ASSERTIONS", "true")
    g = Guardrails.from_env()
    assert g.heal_assertions is False
