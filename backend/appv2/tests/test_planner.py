from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from aivar.browser import Node
from aivar.contracts import FlowKind, PlanMode, TestPlan
from aivar.llm import LLMConfig, LLMResponse
from aivar.models import StepKind
from aivar.planner import PlannedStep, PlanValidationError, validate_plan, plan_flows


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


class TestPlanFlows:
    """Test the plan_flows function."""

    @pytest.fixture
    def fake_config(self):
        """Create a fake LLM config."""
        return LLMConfig(api_key="fake-key")

    def _make_fake_response(self, json_content: dict) -> LLMResponse:
        """Helper to create a fake LLM response."""
        return LLMResponse(
            content=json.dumps(json_content),
            model="fake-model",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.001,
            latency_ms=100.0,
        )

    def test_good_multi_flow_response(self, fake_config):
        """Test that a valid multi-flow response parses into a TestPlan."""
        response_json = {
            "flows": [
                {
                    "name": "Happy path login",
                    "description": "Login with valid credentials",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "username", "value": "user"},
                        {"kind": "action", "verb": "fill", "target": "password", "value": None},
                        {"kind": "action", "verb": "click", "target": "login button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "dashboard", "value": None},
                    ],
                },
                {
                    "name": "Reject invalid password",
                    "description": "Attempt login with wrong password",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "username", "value": "user"},
                        {"kind": "action", "verb": "fill", "target": "password", "value": None},
                        {"kind": "action", "verb": "click", "target": "login button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error message"},
                    ],
                },
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            plan, response = plan_flows(
                digest="Entry: https://example.com\nPage 1: Login",
                mode=PlanMode.SWEEP,
                config=fake_config,
            )

            assert isinstance(plan, TestPlan)
            assert plan.flow_count == 2
            assert plan.flows[0].id == "f1"
            assert plan.flows[1].id == "f2"
            assert plan.flows[0].kind == FlowKind.HAPPY_PATH
            assert plan.flows[1].kind == FlowKind.NEGATIVE

    def test_flow_with_zero_assertions(self, fake_config):
        """Test that a flow with no assertions raises PlanValidationError."""
        response_json = {
            "flows": [
                {
                    "name": "No assertion flow",
                    "description": "This flow has no assertion",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                    ],
                }
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            with pytest.raises(PlanValidationError) as exc_info:
                plan_flows(
                    digest="Entry: https://example.com",
                    mode=PlanMode.SWEEP,
                    config=fake_config,
                )
            assert "no assertions" in str(exc_info.value)

    def test_unknown_kind(self, fake_config):
        """Test that an unknown flow kind raises PlanValidationError."""
        response_json = {
            "flows": [
                {
                    "name": "Unknown kind flow",
                    "description": "This has an unknown kind",
                    "kind": "unknown_kind",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                }
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            with pytest.raises(PlanValidationError) as exc_info:
                plan_flows(
                    digest="Entry: https://example.com",
                    mode=PlanMode.SWEEP,
                    config=fake_config,
                )
            assert "kind" in str(exc_info.value).lower()

    def test_max_flows_truncates(self, fake_config):
        """Test that max_flows=2 truncates a 5-flow response to 2."""
        response_json = {
            "flows": [
                {
                    "name": "Happy path",
                    "description": "Flow 0",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                },
                {
                    "name": "Negative",
                    "description": "Flow 1",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                },
                # These additional flows will be truncated
                {
                    "name": "Edge case",
                    "description": "Flow 2",
                    "kind": "edge_case",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                },
                {
                    "name": "Error state",
                    "description": "Flow 3",
                    "kind": "error_state",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                },
                {
                    "name": "Navigation",
                    "description": "Flow 4",
                    "kind": "navigation",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "link"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "page"},
                    ],
                },
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            plan, _ = plan_flows(
                digest="Entry: https://example.com",
                mode=PlanMode.SWEEP,
                config=fake_config,
                max_flows=2,
            )

            assert plan.flow_count == 2
            assert plan.flows[0].id == "f1"
            assert plan.flows[1].id == "f2"

    def test_sweep_mode_retry_on_happy_path_only(self, fake_config):
        """Test that SWEEP mode retries once if response is happy-path-only."""
        # First response: only happy paths
        first_response_json = {
            "flows": [
                {
                    "name": "Happy path",
                    "description": "Success case",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                }
            ]
        }

        # Second response: includes a negative flow
        second_response_json = {
            "flows": [
                {
                    "name": "Happy path",
                    "description": "Success case",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                },
                {
                    "name": "Negative case",
                    "description": "Error case",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "input", "value": "invalid"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                },
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.side_effect = [
                self._make_fake_response(first_response_json),
                self._make_fake_response(second_response_json),
            ]

            plan, _ = plan_flows(
                digest="Entry: https://example.com",
                mode=PlanMode.SWEEP,
                config=fake_config,
            )

            # Should have succeeded with the retry
            assert plan.flow_count == 2
            assert FlowKind.NEGATIVE in plan.kinds_covered
            # Should have called chat_json twice (initial + retry)
            assert mock_chat.call_count == 2

    def test_sweep_mode_raises_on_happy_path_only_twice(self, fake_config):
        """Test that SWEEP mode raises if even retry produces only happy paths."""
        # Always return happy-path-only
        response_json = {
            "flows": [
                {
                    "name": "Happy path",
                    "description": "Success case",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                }
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.side_effect = [
                self._make_fake_response(response_json),
                self._make_fake_response(response_json),
            ]

            with pytest.raises(PlanValidationError) as exc_info:
                plan_flows(
                    digest="Entry: https://example.com",
                    mode=PlanMode.SWEEP,
                    config=fake_config,
                )
            assert "SWEEP mode" in str(exc_info.value)

    def test_focused_mode_includes_intent(self, fake_config):
        """Test that FOCUSED mode puts the intent into the prompt."""
        response_json = {
            "flows": [
                {
                    "name": "Login flow",
                    "description": "Test login",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "username", "value": "user"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "dashboard"},
                    ],
                },
                {
                    "name": "Negative login",
                    "description": "Reject bad password",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "username", "value": "user"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                },
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            intent = "authenticate with valid and invalid credentials"
            plan, _ = plan_flows(
                digest="Entry: https://example.com",
                mode=PlanMode.FOCUSED,
                intent=intent,
                config=fake_config,
            )

            # Verify the intent appears in the prompt
            call_args = mock_chat.call_args
            system_prompt = call_args[0][0]
            assert intent in system_prompt

    def test_spec_led_mode_includes_prd_text(self, fake_config):
        """Test that SPEC_LED mode puts PRD text into the prompt."""
        response_json = {
            "flows": [
                {
                    "name": "PRD-based flow",
                    "description": "Test per spec",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                },
                {
                    "name": "Error case",
                    "description": "Test error handling",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "input", "value": "invalid"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                },
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            prd = "The app must validate input and show error messages for invalid data."
            plan, _ = plan_flows(
                digest="Entry: https://example.com",
                mode=PlanMode.SPEC_LED,
                prd_text=prd,
                config=fake_config,
            )

            # Verify the PRD appears in the prompt
            call_args = mock_chat.call_args
            system_prompt = call_args[0][0]
            assert prd in system_prompt

    def test_extra_instruction_in_message(self, fake_config):
        """Test that extra_instruction appears in the user message."""
        response_json = {
            "flows": [
                {
                    "name": "Flow 1",
                    "description": "Test 1",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                },
                {
                    "name": "Flow 2",
                    "description": "Test 2",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "field", "value": "bad"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                },
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            extra = "Please focus on the payment flow and include edge cases."
            plan, _ = plan_flows(
                digest="Entry: https://example.com",
                mode=PlanMode.SWEEP,
                config=fake_config,
                extra_instruction=extra,
            )

            # Verify extra_instruction appears in the user message
            call_args = mock_chat.call_args
            user_message = call_args[0][1]
            assert extra in user_message

    def test_credentials_never_invented(self, fake_config):
        """Test that fill steps for password fields have value=None."""
        response_json = {
            "flows": [
                {
                    "name": "Login",
                    "description": "Login flow",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "username", "value": None},
                        {"kind": "action", "verb": "fill", "target": "password", "value": None},
                        {"kind": "action", "verb": "click", "target": "submit"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "success"},
                    ],
                },
                {
                    "name": "Wrong password",
                    "description": "Invalid password flow",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "username", "value": "user"},
                        {"kind": "action", "verb": "fill", "target": "password", "value": None},
                        {"kind": "action", "verb": "click", "target": "submit"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                }
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            plan, _ = plan_flows(
                digest="Entry: https://example.com",
                mode=PlanMode.SWEEP,
                config=fake_config,
            )

            # Find password fill steps in all flows
            for flow in plan.flows:
                password_steps = [
                    s for s in flow.steps
                    if s.verb == "fill" and "password" in s.target.lower()
                ]
                for step in password_steps:
                    assert step.value is None, "Password field should never have an invented value"

    def test_empty_flows_raises(self, fake_config):
        """Test that an empty flows list raises PlanValidationError."""
        response_json = {"flows": []}

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            with pytest.raises(PlanValidationError) as exc_info:
                plan_flows(
                    digest="Entry: https://example.com",
                    mode=PlanMode.SWEEP,
                    config=fake_config,
                )
            assert "empty" in str(exc_info.value).lower()

    def test_flow_missing_steps(self, fake_config):
        """Test that a flow with no steps raises PlanValidationError."""
        response_json = {
            "flows": [
                {
                    "name": "No steps flow",
                    "description": "This has no steps",
                    "kind": "happy_path",
                    "steps": [],
                }
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            with pytest.raises(PlanValidationError) as exc_info:
                plan_flows(
                    digest="Entry: https://example.com",
                    mode=PlanMode.SWEEP,
                    config=fake_config,
                )
            assert "steps" in str(exc_info.value).lower()

    def test_unknown_verb_raises(self, fake_config):
        """Test that an unknown verb raises PlanValidationError."""
        response_json = {
            "flows": [
                {
                    "name": "Bad verb flow",
                    "description": "Unknown verb",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "hover", "target": "element"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                }
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            with pytest.raises(PlanValidationError) as exc_info:
                plan_flows(
                    digest="Entry: https://example.com",
                    mode=PlanMode.SWEEP,
                    config=fake_config,
                )
            assert "verb" in str(exc_info.value).lower()

    def test_non_string_name_raises(self, fake_config):
        """Test that a non-string flow name raises PlanValidationError."""
        response_json = {
            "flows": [
                {
                    "name": 123,  # Should be string
                    "description": "Bad name",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                }
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            with pytest.raises(PlanValidationError) as exc_info:
                plan_flows(
                    digest="Entry: https://example.com",
                    mode=PlanMode.SWEEP,
                    config=fake_config,
                )
            assert "name" in str(exc_info.value).lower()

    def test_step_ids_assigned_correctly(self, fake_config):
        """Test that step IDs are assigned as f1s1, f1s2, f2s1, etc."""
        response_json = {
            "flows": [
                {
                    "name": "First flow",
                    "description": "First",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "action", "verb": "fill", "target": "input", "value": "text"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "result"},
                    ],
                },
                {
                    "name": "Second flow",
                    "description": "Second",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                },
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            plan, _ = plan_flows(
                digest="Entry: https://example.com",
                mode=PlanMode.SWEEP,
                config=fake_config,
            )

            # Check first flow step IDs
            assert plan.flows[0].steps[0].id == "f1s1"
            assert plan.flows[0].steps[1].id == "f1s2"
            assert plan.flows[0].steps[2].id == "f1s3"

            # Check second flow step IDs
            assert plan.flows[1].steps[0].id == "f2s1"
            assert plan.flows[1].steps[1].id == "f2s2"

    def test_assertion_normalization(self, fake_config):
        """Test that assertion steps are normalized to wait_visible with None value."""
        response_json = {
            "flows": [
                {
                    "name": "Flow",
                    "description": "Test",
                    "kind": "happy_path",
                    "steps": [
                        {"kind": "action", "verb": "click", "target": "button"},
                        # Assertion with wrong verb and value — should be normalized
                        {"kind": "assertion", "verb": "click", "target": "result", "value": "something"},
                    ],
                },
                {
                    "name": "Error flow",
                    "description": "Error case",
                    "kind": "negative",
                    "steps": [
                        {"kind": "action", "verb": "fill", "target": "input", "value": "bad"},
                        {"kind": "assertion", "verb": "wait_visible", "target": "error"},
                    ],
                }
            ]
        }

        with patch("aivar.planner.chat_json") as mock_chat:
            mock_chat.return_value = self._make_fake_response(response_json)

            plan, _ = plan_flows(
                digest="Entry: https://example.com",
                mode=PlanMode.SWEEP,
                config=fake_config,
            )

            assertion_step = plan.flows[0].steps[1]
            assert assertion_step.kind == StepKind.ASSERTION
            assert assertion_step.verb == "wait_visible"
            assert assertion_step.value is None
