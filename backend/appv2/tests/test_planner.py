from __future__ import annotations

import pytest

from aivar.browser import Node
from aivar.models import StepKind
from aivar.planner import PlannedStep, PlanValidationError, validate_plan


class TestValidatePlan:
    """Test the validate_plan function."""

    def test_accepts_valid_plan(self):
        """Test that a valid plan is accepted."""
        raw = {
            "steps": [
                {"kind": "action", "verb": "click", "target": "button"},
                {"kind": "assertion", "verb": "wait_visible", "target": "result", "value": None},
            ]
        }
        result = validate_plan(raw)
        assert len(result) == 2
        assert result[0].kind == StepKind.ACTION
        assert result[0].verb == "click"
        assert result[1].kind == StepKind.ASSERTION
        assert result[1].verb == "wait_visible"
        assert result[1].value is None

    def test_rejects_empty_steps(self):
        """Test that empty steps list is rejected."""
        raw = {"steps": []}
        with pytest.raises(PlanValidationError):
            validate_plan(raw)

    def test_rejects_missing_steps(self):
        """Test that missing steps key is rejected."""
        raw = {}
        with pytest.raises(PlanValidationError):
            validate_plan(raw)

    def test_rejects_unknown_verb(self):
        """Test that an unknown verb is rejected."""
        raw = {
            "steps": [
                {"kind": "action", "verb": "unknown", "target": "button"}
            ]
        }
        with pytest.raises(PlanValidationError):
            validate_plan(raw)

    def test_rejects_unknown_kind(self):
        """Test that an unknown kind is rejected."""
        raw = {
            "steps": [
                {"kind": "unknown", "verb": "click", "target": "button"}
            ]
        }
        with pytest.raises(PlanValidationError):
            validate_plan(raw)

    def test_rejects_empty_target(self):
        """Test that an empty target is rejected."""
        raw = {
            "steps": [
                {"kind": "action", "verb": "click", "target": ""}
            ]
        }
        with pytest.raises(PlanValidationError):
            validate_plan(raw)

    def test_forces_assertion_verb_and_value(self):
        """Test that assertions are normalized to wait_visible with None value."""
        raw = {
            "steps": [
                {"kind": "assertion", "verb": "click", "target": "button", "value": "something"},
                {"kind": "action", "verb": "click", "target": "button"},
            ]
        }
        result = validate_plan(raw)
        assert result[0].verb == "wait_visible"
        assert result[0].value is None

    def test_rejects_plan_with_no_assertions(self):
        """Test that a plan with no assertions is rejected."""
        raw = {
            "steps": [
                {"kind": "action", "verb": "click", "target": "button"},
                {"kind": "action", "verb": "fill", "target": "input", "value": "text"},
            ]
        }
        with pytest.raises(PlanValidationError) as exc_info:
            validate_plan(raw)
        assert "no assertions" in str(exc_info.value)
        assert "self-healing" in str(exc_info.value)

    def test_accepts_plan_with_at_least_one_assertion(self):
        """Test that a plan with at least one assertion is accepted."""
        raw = {
            "steps": [
                {"kind": "action", "verb": "click", "target": "button"},
                {"kind": "action", "verb": "fill", "target": "input", "value": "text"},
                {"kind": "assertion", "verb": "wait_visible", "target": "result"},
            ]
        }
        result = validate_plan(raw)
        assert len(result) == 3
        # Count assertions
        assertions = [s for s in result if s.kind == StepKind.ASSERTION]
        assert len(assertions) == 1
