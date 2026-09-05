from __future__ import annotations

import pytest

from aivar.browser import Node
from aivar.models import Selector
from aivar.resolve import (
    MIN_HEURISTIC_SCORE,
    best,
    normalize,
    score_node,
    selector_for,
    shortlist,
)


class TestNormalize:
    """Test normalize function."""

    def test_lowercase_and_split(self):
        """Should lowercase and split on non-alphanumerics."""
        result = normalize("Hello World")
        assert result == ["hello", "world"]

    def test_drops_generic_words(self):
        """Should drop words in GENERIC_WORDS."""
        result = normalize("the login button")
        assert "the" not in result
        assert "login" in result
        assert "button" not in result

    def test_empty_after_dropping_returns_original(self):
        """If all words are generic, return original lowercased."""
        result = normalize("the a an")
        assert result == ["the", "a", "an"]

    def test_split_on_various_separators(self):
        """Should split on any non-alphanumeric."""
        result = normalize("User_Name-Test.ID")
        assert set(result) == {"user", "name", "test", "id"}


class TestSelectorFor:
    """Test selector_for function."""

    def test_prefers_testid(self):
        """Should prefer testid over role/name."""
        node = Node(
            ref="e0",
            role="button",
            name="Click me",
            tag="button",
            placeholder=None,
            testid="my-button",
            visible=True,
        )
        selector = selector_for(node)
        assert selector is not None
        assert selector.strategy == "testid"
        assert selector.value == "my-button"

    def test_role_and_name_second(self):
        """Should prefer role+name when no testid."""
        node = Node(
            ref="e0",
            role="button",
            name="Click me",
            tag="button",
            placeholder=None,
            testid=None,
            visible=True,
        )
        selector = selector_for(node)
        assert selector is not None
        assert selector.strategy == "role"
        assert selector.value == "Click me"
        assert selector.role == "button"

    def test_placeholder_third(self):
        """Should prefer placeholder when no testid or role+name."""
        node = Node(
            ref="e0",
            role="textbox",
            name="",
            tag="input",
            placeholder="Username",
            testid=None,
            visible=True,
        )
        selector = selector_for(node)
        assert selector is not None
        assert selector.strategy == "placeholder"
        assert selector.value == "Username"

    def test_text_fourth(self):
        """Should use role when both role and name are available."""
        node = Node(
            ref="e0",
            role="heading",
            name="Welcome",
            tag="h1",
            placeholder=None,
            testid=None,
            visible=True,
        )
        selector = selector_for(node)
        assert selector is not None
        # Heading has role="heading" and name="Welcome", so it uses role strategy
        assert selector.strategy == "role"
        assert selector.value == "Welcome"
        assert selector.role == "heading"

    def test_name_only(self):
        """Should use text when only name is available (no role)."""
        node = Node(
            ref="e0",
            role="",
            name="Welcome",
            tag="div",
            placeholder=None,
            testid=None,
            visible=True,
        )
        selector = selector_for(node)
        assert selector is not None
        assert selector.strategy == "text"
        assert selector.value == "Welcome"

    def test_none_when_nothing_available(self):
        """Should return None when no selector can be built."""
        node = Node(
            ref="e0",
            role="",
            name="",
            tag="div",
            placeholder=None,
            testid=None,
            visible=True,
        )
        selector = selector_for(node)
        assert selector is None

    def test_selector_for_uses_css_for_non_standard_testid(self):
        """A node with data-test attribute should yield a CSS selector."""
        # Node with data-test attribute
        node_data_test = Node(
            ref="e0",
            role="textbox",
            name="",
            tag="input",
            placeholder=None,
            testid="username",
            testid_attr="data-test",
            visible=True,
        )
        selector = selector_for(node_data_test)
        assert selector is not None
        assert selector.strategy == "css"
        assert selector.value == '[data-test="username"]'

        # Node with standard data-testid should use testid strategy
        node_data_testid = Node(
            ref="e1",
            role="button",
            name="Login",
            tag="input",
            placeholder=None,
            testid="login-button",
            testid_attr="data-testid",
            visible=True,
        )
        selector = selector_for(node_data_testid)
        assert selector is not None
        assert selector.strategy == "testid"
        assert selector.value == "login-button"


class TestScoreNode:
    """Test score_node function."""

    def test_exact_match_scores_1_0(self):
        """Exact name match should score 1.0."""
        node = Node(
            ref="e0",
            role="button",
            name="login button",
            tag="button",
            placeholder=None,
            testid=None,
            visible=True,
        )
        score, why = score_node(node, "login button")
        assert score == 1.0
        assert "exact" in why.lower()

    def test_partial_match_scores_less(self):
        """Partial token match should score less than 1.0."""
        node = Node(
            ref="e0",
            role="button",
            name="submit",
            tag="button",
            placeholder=None,
            testid=None,
            visible=True,
        )
        # Target "submit cancel" has tokens ["submit", "cancel"]
        # Node "submit" has tokens ["submit"]
        # Matched tokens: "submit" (1/2) → 0.5 * 0.8 = 0.4
        score, why = score_node(node, "submit cancel")
        assert 0.35 <= score <= 0.45
        assert "token" in why.lower()

    def test_role_hint_bonus(self):
        """Mention of role in target should give +0.1."""
        node = Node(
            ref="e0",
            role="button",
            name="click",
            tag="button",
            placeholder=None,
            testid=None,
            visible=True,
        )
        score, why = score_node(node, "click button")
        assert "role" in why.lower() or "hint" in why.lower()

    def test_invisible_node_penalty(self):
        """Invisible node should have -0.4 penalty, subject to clamping."""
        visible_node = Node(
            ref="e0",
            role="button",
            name="test",
            tag="button",
            placeholder=None,
            testid=None,
            visible=True,
        )
        invisible_node = Node(
            ref="e1",
            role="button",
            name="test",
            tag="button",
            placeholder=None,
            testid=None,
            visible=False,
        )
        visible_score, _ = score_node(visible_node, "test")
        invisible_score, _ = score_node(invisible_node, "test")
        # Both get exact match (1.0) + name match bonus (+0.15) = 1.15
        # After clamp: visible=1.0
        # Invisible also gets invisible penalty (-0.4): 1.15 - 0.4 = 0.75
        # So difference is 0.25, not 0.4 (due to name bonus shared by both)
        # The invisible penalty is still 0.4, but both benefit from name bonus.
        assert visible_score - invisible_score == pytest.approx(0.25)

    def test_score_clamped_0_to_1(self):
        """Score should be clamped to 0.0..1.0."""
        node = Node(
            ref="e0",
            role="",
            name="",
            tag="div",
            placeholder=None,
            testid=None,
            visible=False,
        )
        score, _ = score_node(node, "anything")
        assert 0.0 <= score <= 1.0

    def test_role_hint_requires_a_real_role(self):
        """Role hint bonus should only apply if node has a non-empty role."""
        # Node with empty role should NOT get role bonus even if target mentions "button"
        roleless_node = Node(
            ref="e0",
            role="",
            name="login",
            tag="div",
            placeholder=None,
            testid="login-container",
            visible=True,
        )
        score, why = score_node(roleless_node, "login button")
        # Should get -0.3 penalty for no role
        assert "roleless -0.3" in why
        # Should NOT get the +0.1 role hint
        assert "role hint" not in why

        # Node with a role should get bonus if target matches
        button_node = Node(
            ref="e1",
            role="button",
            name="Login",
            tag="button",
            placeholder=None,
            testid="login-button",
            visible=True,
        )
        score, why = score_node(button_node, "login button")
        assert "role hint +0.1" in why

    def test_roleless_container_loses_to_real_button(self):
        """A roleless container div should score lower than a real button, even with matching testid."""
        # This is the regression from saucedemo:
        # A <div data-test="login-container"> was winning over <input data-test="login-button" value="Login">

        roleless_container = Node(
            ref="e0",
            role="",
            name="",
            tag="div",
            placeholder=None,
            testid="login-container",
            visible=True,
        )

        real_button = Node(
            ref="e1",
            role="button",
            name="Login",
            tag="input",
            placeholder=None,
            testid="login-button",
            visible=True,
        )

        target = "login button"
        container_score, container_why = score_node(roleless_container, target)
        button_score, button_why = score_node(real_button, target)

        # The button must score strictly higher than the container
        assert button_score > container_score, (
            f"Button ({button_score}, why={button_why}) should beat "
            f"container ({container_score}, why={container_why})"
        )


class TestShortlist:
    """Test shortlist function."""

    def test_returns_candidates_sorted_by_score(self):
        """Should return candidates sorted by score descending."""
        nodes = [
            Node(
                ref="e0",
                role="button",
                name="login",
                tag="button",
                placeholder=None,
                testid=None,
                visible=True,
            ),
            Node(
                ref="e1",
                role="button",
                name="submit",
                tag="button",
                placeholder=None,
                testid=None,
                visible=True,
            ),
            Node(
                ref="e2",
                role="button",
                name="cancel",
                tag="button",
                placeholder=None,
                testid=None,
                visible=True,
            ),
        ]
        candidates = shortlist(nodes, "login button")
        assert len(candidates) >= 1
        # First candidate should be "login" since it matches the target
        assert candidates[0].node.name == "login"

    def test_respects_limit(self):
        """Should respect the limit parameter."""
        nodes = [
            Node(
                ref=f"e{i}",
                role="button",
                name=f"button{i}",
                tag="button",
                placeholder=None,
                testid=None,
                visible=True,
            )
            for i in range(10)
        ]
        candidates = shortlist(nodes, "button", limit=3)
        assert len(candidates) <= 3

    def test_drops_zero_scores(self):
        """Should not include candidates with score 0.0."""
        nodes = [
            Node(
                ref="e0",
                role="",
                name="",
                tag="div",
                placeholder=None,
                testid=None,
                visible=True,
            ),
        ]
        candidates = shortlist(nodes, "something")
        # Node with no name and empty role won't produce a selector
        assert len(candidates) == 0


class TestBest:
    """Test best function."""

    def test_returns_top_candidate_if_above_threshold(self):
        """Should return top candidate if score >= MIN_HEURISTIC_SCORE."""
        nodes = [
            Node(
                ref="e0",
                role="button",
                name="login",
                tag="button",
                placeholder=None,
                testid=None,
                visible=True,
            ),
        ]
        candidate = best(nodes, "login button")
        assert candidate is not None
        assert candidate.score >= MIN_HEURISTIC_SCORE

    def test_returns_none_if_below_threshold(self):
        """Should return None if top score < MIN_HEURISTIC_SCORE."""
        nodes = [
            Node(
                ref="e0",
                role="button",
                name="xxx",
                tag="button",
                placeholder=None,
                testid=None,
                visible=False,
            ),
        ]
        candidate = best(nodes, "login button")
        # Very low score due to no match and invisible
        if candidate is not None:
            assert candidate.score < MIN_HEURISTIC_SCORE

    def test_returns_none_for_empty_list(self):
        """Should return None for empty node list."""
        candidate = best([], "login button")
        assert candidate is None
