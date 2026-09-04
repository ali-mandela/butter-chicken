from __future__ import annotations

import json
from pathlib import Path

import pytest

from aivar.models import CompiledTest, HealProposal, Selector, Step, StepKind
from aivar.quarantine import (
    apply_proposal,
    delete_proposal,
    load_proposals,
    proposal_id,
    save_proposal,
)


def make_proposal(
    test_id: str = "test1",
    step_id: str = "s1",
    confidence: float = 0.8,
) -> HealProposal:
    """Helper to create a HealProposal."""
    return HealProposal(
        test_id=test_id,
        step_id=step_id,
        old=Selector(strategy="role", value="Login", role="button"),
        new=Selector(strategy="role", value="Sign in", role="button"),
        confidence=confidence,
        reasoning="Healed by model",
        semantic_match=True,
    )


class TestProposalId:
    def test_proposal_id_deterministic(self):
        """proposal_id is deterministic for identical proposals."""
        proposal = make_proposal()
        id1 = proposal_id(proposal)
        id2 = proposal_id(proposal)
        assert id1 == id2

    def test_proposal_id_differs_on_new_selector_change(self):
        """proposal_id differs when new selector changes."""
        p1 = make_proposal()
        p2 = HealProposal(
            test_id=p1.test_id,
            step_id=p1.step_id,
            old=p1.old,
            new=Selector(strategy="role", value="DIFFERENT", role="button"),
            confidence=p1.confidence,
            reasoning=p1.reasoning,
            semantic_match=p1.semantic_match,
        )
        id1 = proposal_id(p1)
        id2 = proposal_id(p2)
        assert id1 != id2

    def test_proposal_id_length(self):
        """proposal_id is first 12 chars of sha256."""
        proposal = make_proposal()
        id_str = proposal_id(proposal)
        assert len(id_str) == 12
        assert all(c in "0123456789abcdef" for c in id_str)


class TestSaveProposal:
    def test_save_proposal_creates_file(self, tmp_path):
        """save_proposal creates a JSON file."""
        proposal = make_proposal()
        path = save_proposal(proposal, tmp_path)

        assert path.exists()
        assert path.suffix == ".json"

        # Check filename format
        assert proposal.test_id in path.name
        assert proposal.step_id in path.name

    def test_save_proposal_content(self, tmp_path):
        """Saved file contains correct JSON."""
        proposal = make_proposal(confidence=0.75)
        save_proposal(proposal, tmp_path)

        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1

        with open(files[0], "r") as f:
            data = json.load(f)

        assert data["test_id"] == "test1"
        assert data["step_id"] == "s1"
        assert data["confidence"] == 0.75
        assert data["reasoning"] == "Healed by model"

    def test_save_proposal_overwrites_same_proposal(self, tmp_path):
        """Saving the same proposal twice leaves one file."""
        proposal = make_proposal()
        save_proposal(proposal, tmp_path)
        save_proposal(proposal, tmp_path)

        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1

    def test_save_proposal_different_proposals_both_files(self, tmp_path):
        """Different proposals create different files."""
        p1 = make_proposal(test_id="test1")
        p2 = make_proposal(test_id="test2")

        save_proposal(p1, tmp_path)
        save_proposal(p2, tmp_path)

        files = list(tmp_path.glob("*.json"))
        assert len(files) == 2


class TestLoadProposals:
    def test_load_proposals_empty_dir(self, tmp_path):
        """load_proposals returns empty list for nonexistent dir."""
        proposals = load_proposals(tmp_path / "nonexistent")
        assert proposals == []

    def test_load_proposals_single_file(self, tmp_path):
        """load_proposals loads a single proposal."""
        proposal = make_proposal()
        save_proposal(proposal, tmp_path)

        loaded = load_proposals(tmp_path)
        assert len(loaded) == 1

        pid, loaded_proposal = loaded[0]
        assert loaded_proposal.test_id == proposal.test_id
        assert loaded_proposal.step_id == proposal.step_id
        assert loaded_proposal.confidence == proposal.confidence

    def test_load_proposals_multiple_files_sorted(self, tmp_path):
        """load_proposals returns all proposals sorted by id."""
        p1 = make_proposal(test_id="test1", step_id="s1")
        p2 = make_proposal(test_id="test2", step_id="s2")
        p3 = make_proposal(test_id="test3", step_id="s3")

        save_proposal(p1, tmp_path)
        save_proposal(p2, tmp_path)
        save_proposal(p3, tmp_path)

        loaded = load_proposals(tmp_path)
        assert len(loaded) == 3

        # Should be sorted by proposal_id
        ids = [pid for pid, _ in loaded]
        assert ids == sorted(ids)

    def test_load_proposals_skips_unparseable(self, tmp_path):
        """load_proposals skips unparseable files without crashing."""
        proposal = make_proposal()
        save_proposal(proposal, tmp_path)

        # Write an invalid JSON file
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ invalid json")

        # Should load the good one and skip the bad one
        loaded = load_proposals(tmp_path)
        assert len(loaded) == 1
        assert loaded[0][1].test_id == "test1"


class TestDeleteProposal:
    def test_delete_proposal_success(self, tmp_path):
        """delete_proposal removes the file."""
        proposal = make_proposal()
        save_proposal(proposal, tmp_path)

        pid = proposal_id(proposal)
        success = delete_proposal(pid, tmp_path)

        assert success
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 0

    def test_delete_proposal_nonexistent(self, tmp_path):
        """delete_proposal returns False for nonexistent id."""
        success = delete_proposal("nonexistent-id", tmp_path)
        assert not success

    def test_delete_proposal_nonexistent_dir(self, tmp_path):
        """delete_proposal returns False for nonexistent dir."""
        success = delete_proposal("any-id", tmp_path / "nonexistent")
        assert not success


class TestApplyProposal:
    def test_apply_proposal_replaces_selector(self, tmp_path):
        """apply_proposal replaces step selector."""
        # Create a test file
        test = CompiledTest(
            id="test1",
            intent="Test",
            url="http://localhost",
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ACTION,
                    verb="click",
                    target="Login",
                    selector=Selector(strategy="role", value="Old", role="button"),
                ),
            ],
            version=1,
        )
        test_path = tmp_path / "test.json"
        from aivar.testfile import save_test

        save_test(test, test_path)

        # Create and apply a proposal
        proposal = HealProposal(
            test_id="test1",
            step_id="s1",
            old=test.steps[0].selector,
            new=Selector(strategy="role", value="New", role="button"),
            confidence=0.9,
            reasoning="Healed",
            semantic_match=True,
        )

        result = apply_proposal(proposal, test_path)

        # Check the result
        assert result.steps[0].selector.value == "New"
        assert result.version == 2

        # Check the file was written
        from aivar.testfile import load_test

        reloaded = load_test(test_path)
        assert reloaded.steps[0].selector.value == "New"
        assert reloaded.version == 2

    def test_apply_proposal_leaves_other_steps_untouched(self, tmp_path):
        """apply_proposal only changes the targeted step."""
        test = CompiledTest(
            id="test1",
            intent="Test",
            url="http://localhost",
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ACTION,
                    verb="click",
                    target="Login",
                    selector=Selector(strategy="role", value="Old1", role="button"),
                ),
                Step(
                    id="s2",
                    kind=StepKind.ACTION,
                    verb="click",
                    target="Logout",
                    selector=Selector(strategy="role", value="Old2", role="button"),
                ),
            ],
            version=1,
        )
        test_path = tmp_path / "test.json"
        from aivar.testfile import save_test

        save_test(test, test_path)

        # Apply proposal to s1 only
        proposal = HealProposal(
            test_id="test1",
            step_id="s1",
            old=test.steps[0].selector,
            new=Selector(strategy="role", value="New1", role="button"),
            confidence=0.9,
            reasoning="Healed",
            semantic_match=True,
        )

        apply_proposal(proposal, test_path)

        from aivar.testfile import load_test

        reloaded = load_test(test_path)
        assert reloaded.steps[0].selector.value == "New1"
        assert reloaded.steps[1].selector.value == "Old2"  # Unchanged

    def test_apply_proposal_unknown_step_raises(self, tmp_path):
        """apply_proposal raises KeyError for unknown step_id."""
        test = CompiledTest(
            id="test1",
            intent="Test",
            url="http://localhost",
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ACTION,
                    verb="click",
                    target="Login",
                    selector=Selector(strategy="role", value="Old", role="button"),
                ),
            ],
            version=1,
        )
        test_path = tmp_path / "test.json"
        from aivar.testfile import save_test

        save_test(test, test_path)

        proposal = HealProposal(
            test_id="test1",
            step_id="unknown-id",
            old=None,
            new=Selector(strategy="role", value="New", role="button"),
            confidence=0.9,
            reasoning="Healed",
            semantic_match=True,
        )

        with pytest.raises(KeyError):
            apply_proposal(proposal, test_path)
