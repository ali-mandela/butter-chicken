from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from aivar.browser import Node
from aivar.config import Guardrails
from aivar.healer import (
    RerankResult,
    format_candidates,
    propose_heal,
    rerank,
    semantic_match,
)
from aivar.llm import LLMConfig, LLMInvalidJSON, LLMResponse
from aivar.models import Selector, Step, StepKind
from aivar.resolve import Candidate


@pytest.fixture
def llm_config() -> LLMConfig:
    """Dummy LLM config for testing."""
    return LLMConfig(api_key="test-key")


def make_node(role: str = "button", name: str = "", testid: str | None = None) -> Node:
    """Helper to create a Node.

    Defaults to a real ARIA role because semantic_match refuses roleless nodes
    outright -- a <div> wrapper is never a healed control. Pass role="" to
    exercise that rejection deliberately.
    """
    return Node(
        ref="node-1",
        role=role,
        name=name,
        tag="button",
        placeholder=None,
        testid=testid,
        visible=True,
        testid_attr="data-testid" if testid else None,
    )


def make_candidate(node: Node, score: float = 0.8) -> Candidate:
    """Helper to create a Candidate."""
    selector = Selector(strategy="role", value=node.name, role=node.role)
    return Candidate(node=node, selector=selector, score=score, why="test")


class TestFormatCandidates:
    def test_format_candidates_with_all_fields(self):
        """Format candidates with all fields populated."""
        node = Node(
            ref="node-1",
            role="button",
            name="Login",
            tag="button",
            placeholder="Press to login",
            testid="login-btn",
            visible=True,
            testid_attr="data-testid",
        )
        candidate = make_candidate(node)
        result = format_candidates([candidate])
        assert "[0]" in result
        assert "role=button" in result
        assert "name=Login" in result
        assert "testid=login-btn" in result
        assert "placeholder=Press to login" in result
        assert "score=0.80" in result

    def test_format_candidates_omit_empty_fields(self):
        """Empty fields are omitted."""
        node = Node(
            ref="node-1",
            role="button",
            name="Click me",
            tag="button",
            placeholder=None,
            testid=None,
            visible=True,
        )
        candidate = make_candidate(node)
        result = format_candidates([candidate])
        assert "placeholder=" not in result
        assert "testid=" not in result

    def test_format_candidates_multiple(self):
        """Multiple candidates are formatted with indices."""
        nodes = [
            make_node("button", "Login"),
            make_node("button", "Logout"),
            make_node("link", "Sign up"),
        ]
        candidates = [make_candidate(n) for n in nodes]
        result = format_candidates(candidates)
        assert "[0]" in result
        assert "[1]" in result
        assert "[2]" in result
        assert "Login" in result
        assert "Logout" in result
        assert "Sign up" in result


class TestRerank:
    def test_rerank_happy_path(self, llm_config):
        """Rerank successfully parses model response."""

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {"index": 1, "confidence": 0.87, "reasoning": "Best match"}
                ),
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.001,
                latency_ms=100,
            )

        candidates = [
            make_candidate(make_node("button", "Login")),
            make_candidate(make_node("button", "Sign in")),
        ]

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            result, response = rerank("sign in button", candidates, llm_config)

        assert result.index == 1
        assert result.confidence == 0.87
        assert result.reasoning == "Best match"
        assert response.model == "test"

    def test_rerank_clamps_confidence(self, llm_config):
        """Confidence above 1.0 is clamped to 1.0, below 0.0 to 0.0."""

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {"index": 0, "confidence": 1.5, "reasoning": "High"}
                ),
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.001,
                latency_ms=100,
            )

        candidates = [make_candidate(make_node("button", "Login"))]

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            result, _ = rerank("login", candidates, llm_config)

        assert result.confidence == 1.0

    def test_rerank_missing_index_raises(self, llm_config):
        """Missing index raises LLMInvalidJSON."""

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content=json.dumps({"confidence": 0.5, "reasoning": "No index"}),
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.001,
                latency_ms=100,
            )

        candidates = [make_candidate(make_node("button", "Login"))]

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            with pytest.raises(LLMInvalidJSON, match="Missing 'index'"):
                rerank("login", candidates, llm_config)

    def test_rerank_out_of_range_index_raises(self, llm_config):
        """Out-of-range index raises LLMInvalidJSON."""

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {"index": 5, "confidence": 0.5, "reasoning": "Bad index"}
                ),
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.001,
                latency_ms=100,
            )

        candidates = [make_candidate(make_node("button", "Login"))]

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            with pytest.raises(LLMInvalidJSON, match="out of range"):
                rerank("login", candidates, llm_config)


class TestSemanticMatch:
    def test_semantic_match_old_is_none(self):
        """old=None always returns True."""
        node = make_node("button", "Click")
        match, reason = semantic_match(None, node)
        assert match
        assert "no prior selector" in reason

    def test_semantic_match_role_agrees(self):
        """Role strategy: agree iff roles match."""
        node = make_node("button", "Login")
        old = Selector(strategy="role", value="Login", role="button")
        match, reason = semantic_match(old, node)
        assert match
        assert "button" in reason

    def test_semantic_match_role_disagrees(self):
        """Role strategy: disagree if roles differ."""
        node = make_node("link", "Login")
        old = Selector(strategy="role", value="Login", role="button")
        match, reason = semantic_match(old, node)
        assert not match
        assert "button" in reason
        assert "link" in reason

    def test_semantic_match_testid_equal(self):
        """Testid strategy: agree iff testids match."""
        node = make_node(testid="login-btn")
        old = Selector(strategy="testid", value="login-btn")
        match, reason = semantic_match(old, node)
        assert match

    def test_semantic_match_testid_different(self):
        """Testid strategy: disagree if testids differ."""
        node = make_node(testid="login-btn-new")
        old = Selector(strategy="testid", value="login-btn-old")
        match, reason = semantic_match(old, node)
        assert not match

    def test_semantic_match_css_extracts_testid(self):
        """CSS strategy: extract testid from [attr="value"]."""
        node = make_node(testid="x")
        old = Selector(strategy="css", value='[data-test="x"]')
        match, reason = semantic_match(old, node)
        assert match

    def test_roleless_container_is_refused(self):
        """A node with no ARIA role is never an acceptable heal.

        Regression: on the real saucedemo page a <div data-test="login-container">
        outranked the actual submit button. Even a confident model choosing it
        must be refused here -- containers are not controls.
        """
        node = make_node(role="", testid="login-container")
        old = Selector(strategy="css", value='[data-test="login-container"]')
        match, reason = semantic_match(old, node, "login button")
        assert not match
        assert "role" in reason.lower()

    def test_semantic_match_survives_testid_rename(self):
        """A renamed test id still heals when the target wording still matches.

        A developer renaming data-test="username" to "user-name" is ordinary
        refactoring, not a different element. Without this fallback, test-id
        drift -- the single most common kind -- could never be healed.
        """
        node = make_node(role="textbox", name="Username", testid="user-name")
        old = Selector(strategy="css", value='[data-test="username"]')
        match, reason = semantic_match(old, node, "username field")
        assert match
        assert "target wording" in reason

    def test_testid_rename_without_other_agreement_is_refused(self):
        """A renamed test id with nothing else in common is still refused."""
        node = make_node(role="button", name="Cancel", testid="cancel-btn")
        old = Selector(strategy="css", value='[data-test="username"]')
        match, reason = semantic_match(old, node, "username field")
        assert not match

    def test_semantic_match_text_shares_token(self):
        """Text strategy: agree if normalized tokens overlap."""
        node = make_node(name="Click Login")
        old = Selector(strategy="text", value="Login Button")
        match, reason = semantic_match(old, node)
        assert match
        assert "login" in reason.lower()

    def test_semantic_match_placeholder_shares_token(self):
        """Placeholder strategy: agree if tokens overlap."""
        node = Node(
            ref="node-1",
            role="textbox",
            name="",
            tag="input",
            placeholder="Enter password",
            testid=None,
            visible=True,
        )
        old = Selector(strategy="placeholder", value="password")
        match, reason = semantic_match(old, node)
        assert match

    def test_semantic_match_unknown_strategy(self):
        """Unknown strategy returns False."""
        node = make_node("button", "Login")
        old = Selector(strategy="unknown", value="x")
        match, reason = semantic_match(old, node)
        assert not match
        assert "unknown" in reason.lower()


class TestProposeHeal:
    def test_propose_heal_assertion_never_healed(self, llm_config):
        """ASSERTION steps are never healed."""
        step = Step(
            id="s1",
            kind=StepKind.ASSERTION,
            verb="wait_visible",
            target="Login",
            selector=Selector(strategy="role", value="Login", role="button"),
        )
        candidates = [make_candidate(make_node("button", "Login"))]

        proposal, reason, llm_response = propose_heal(
            test_id="test1",
            step=step,
            candidates=candidates,
            config=llm_config,
            guardrails=Guardrails(),
        )

        assert proposal is None
        assert "assertions are never healed" in reason
        assert llm_response is None

    def test_propose_heal_no_candidates(self, llm_config):
        """No candidates returns None."""
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="Login",
        )

        proposal, reason, llm_response = propose_heal(
            test_id="test1",
            step=step,
            candidates=[],
            config=llm_config,
            guardrails=Guardrails(),
        )

        assert proposal is None
        assert "no candidates" in reason
        assert llm_response is None

    def test_propose_heal_rerank_fails(self, llm_config):
        """Rerank failure is caught and rejected."""

        def fake_chat_json(*args, **kwargs):
            raise LLMInvalidJSON("Bad response")

        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="Login",
        )
        candidates = [make_candidate(make_node("button", "Login"))]

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            proposal, reason, llm_response = propose_heal(
                test_id="test1",
                step=step,
                candidates=candidates,
                config=llm_config,
                guardrails=Guardrails(),
            )

        assert proposal is None
        assert "rerank failed" in reason

    def test_propose_heal_low_confidence_rejected(self, llm_config):
        """Confidence below cap is rejected."""

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {"index": 0, "confidence": 0.2, "reasoning": "Low"}
                ),
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.001,
                latency_ms=100,
            )

        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="Login",
        )
        candidates = [make_candidate(make_node("button", "Login"))]
        guardrails = Guardrails(min_heal_confidence=0.5)

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            proposal, reason, llm_response = propose_heal(
                test_id="test1",
                step=step,
                candidates=candidates,
                config=llm_config,
                guardrails=guardrails,
            )

        assert proposal is None
        assert "confidence" in reason and "below" in reason

    def test_propose_heal_semantic_mismatch_rejected(self, llm_config):
        """Semantic mismatch with require_semantic_match=True rejects."""

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {"index": 0, "confidence": 0.9, "reasoning": "Good"}
                ),
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.001,
                latency_ms=100,
            )

        old_node = make_node("button", "Login")
        new_node = make_node("link", "Login")  # Different role
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="Login",
            selector=Selector(strategy="role", value="Login", role="button"),
        )
        candidates = [make_candidate(new_node)]
        guardrails = Guardrails(require_semantic_match=True)

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            proposal, reason, llm_response = propose_heal(
                test_id="test1",
                step=step,
                candidates=candidates,
                config=llm_config,
                guardrails=guardrails,
            )

        assert proposal is None
        assert "semantic mismatch" in reason

    def test_propose_heal_semantic_mismatch_ignored(self, llm_config):
        """Semantic mismatch ignored when require_semantic_match=False."""

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {"index": 0, "confidence": 0.9, "reasoning": "Good"}
                ),
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.001,
                latency_ms=100,
            )

        new_node = make_node("link", "Login")  # Different role
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="Login",
            selector=Selector(strategy="role", value="Login", role="button"),
        )
        candidates = [make_candidate(new_node)]
        guardrails = Guardrails(require_semantic_match=False)

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            proposal, reason, llm_response = propose_heal(
                test_id="test1",
                step=step,
                candidates=candidates,
                config=llm_config,
                guardrails=guardrails,
            )

        assert proposal is not None
        assert reason == "accepted"

    def test_propose_heal_happy_path(self, llm_config):
        """Happy path: proposal is accepted."""

        def fake_chat_json(*args, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {"index": 0, "confidence": 0.9, "reasoning": "Looks good"}
                ),
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.001,
                latency_ms=100,
            )

        node = make_node("button", "Login")
        step = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="Login",
        )
        candidates = [make_candidate(node)]

        with patch("aivar.healer.chat_json", side_effect=fake_chat_json):
            proposal, reason, llm_response = propose_heal(
                test_id="test1",
                step=step,
                candidates=candidates,
                config=llm_config,
                guardrails=Guardrails(),
            )

        assert proposal is not None
        assert reason == "accepted"
        assert proposal.test_id == "test1"
        assert proposal.step_id == "s1"
        assert proposal.confidence == 0.9
        assert proposal.reasoning == "Looks good"
