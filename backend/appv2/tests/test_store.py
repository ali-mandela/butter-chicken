"""Tests for aivar.store module."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from aivar.contracts import Decision, Gap, Stage, TriageResult, TriageVerdict
from aivar.models import RunResult, Severity, Source, StepResult
from aivar.report import PipelineReport
from aivar.store import (
    StoreError,
    RunSummary,
    delete_run,
    get_dsn,
    get_run,
    health,
    init_schema,
    list_runs,
    save_run,
    save_run_safe,
)


class TestGetDsn:
    """Tests for get_dsn()."""

    def test_get_dsn_raises_when_unset(self, monkeypatch):
        """get_dsn raises StoreError when AIVAR_DB_URL is unset."""
        # Remove AIVAR_DB_URL from environment
        monkeypatch.delenv("AIVAR_DB_URL", raising=False)

        # Mock load_dotenv to do nothing (so it doesn't load from .env)
        from aivar import store

        def mock_load_dotenv(start=None):
            pass

        monkeypatch.setattr(store, "load_dotenv", mock_load_dotenv)

        # Now try to get the DSN
        with pytest.raises(StoreError) as exc_info:
            get_dsn()

        assert "AIVAR_DB_URL" in str(exc_info.value)


class TestHealth:
    """Tests for health()."""

    def test_health_with_bad_dsn_no_password_leak(self):
        """health() returns False with bad DSN and never leaks password."""
        bad_dsn = "postgresql://u:supersecret@nowhere.invalid:5432/x"

        # Monkeypatch get_dsn to return the bad DSN
        import aivar.store

        original_get_dsn = aivar.store.get_dsn

        def mock_get_dsn():
            return bad_dsn

        aivar.store.get_dsn = mock_get_dsn

        try:
            ok, reason = health()
            assert not ok
            assert "supersecret" not in reason
        finally:
            aivar.store.get_dsn = original_get_dsn

    def test_health_never_raises(self):
        """health() never raises, even with missing env var."""
        import aivar.store

        original_get_dsn = aivar.store.get_dsn

        def mock_get_dsn():
            raise StoreError("AIVAR_DB_URL not set")

        aivar.store.get_dsn = mock_get_dsn

        try:
            ok, reason = health()
            assert not ok
            assert isinstance(reason, str)
        finally:
            aivar.store.get_dsn = original_get_dsn


class TestSaveRunSafe:
    """Tests for save_run_safe()."""

    def test_save_run_safe_returns_none_on_failure(self):
        """save_run_safe returns None and does not raise when DB is unreachable."""
        bad_dsn = "postgresql://u:pass@nowhere.invalid:5432/x"

        report = PipelineReport(
            run_id=uuid4().hex[:8],
            url="http://example.com",
            mode="sweep",
        )

        result = save_run_safe(report, dsn=bad_dsn)
        assert result is None


class TestRunSummary:
    """Tests for RunSummary dataclass."""

    def test_run_summary_round_trip(self):
        """RunSummary preserves all fields."""
        now = datetime.now(timezone.utc)
        summary = RunSummary(
            run_id="test-run-1",
            url="http://example.com",
            mode="sweep",
            escalated=False,
            flows_total=5,
            flows_passed=4,
            gaps_total=2,
            cost_usd=0.123,
            duration_s=45.6,
            summary_line="4/5 flows passed, $0.123, 45.6s",
            created_at=now,
        )

        assert summary.run_id == "test-run-1"
        assert summary.url == "http://example.com"
        assert summary.mode == "sweep"
        assert summary.escalated is False
        assert summary.flows_total == 5
        assert summary.flows_passed == 4
        assert summary.gaps_total == 2
        assert summary.cost_usd == 0.123
        assert summary.duration_s == 45.6
        assert summary.summary_line == "4/5 flows passed, $0.123, 45.6s"
        assert summary.created_at == now


# Live tests (require real database, marked with @pytest.mark.live)
@pytest.mark.live
class TestLiveStore:
    """Live tests using the real AIVAR_DB_URL."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Initialize schema before each test."""
        init_schema()
        yield

    def test_init_schema_idempotent(self):
        """init_schema runs twice without error."""
        # First call (may already be done in setup)
        init_schema()
        # Second call should also succeed
        init_schema()

    def test_save_and_get_run(self):
        """save_run then get_run returns the same data."""
        run_id = uuid4().hex[:8]
        report = self._make_report(run_id)

        # Save the run
        returned_id = save_run(report)
        assert returned_id == run_id

        # Fetch it back
        result = get_run(run_id)
        assert result is not None
        assert result["run"]["run_id"] == run_id
        assert result["run"]["url"] == report.url
        assert result["run"]["mode"] == report.mode
        assert len(result["decisions"]) == len(report.decisions)
        assert len(result["gaps"]) == len(report.gaps)

        # Clean up
        delete_run(run_id)

    def test_save_same_report_twice_is_idempotent(self):
        """Saving the same report twice leaves exactly one run row."""
        run_id = uuid4().hex[:8]
        report = self._make_report(run_id)

        # Save twice
        save_run(report)
        save_run(report)

        # Get and verify
        result = get_run(run_id)
        assert result is not None
        # Should have exactly 2 decisions and 1 gap (from the report)
        assert len(result["decisions"]) == 2
        assert len(result["gaps"]) == 1

        # Clean up
        delete_run(run_id)

    def test_list_runs_includes_saved(self):
        """list_runs includes a saved run."""
        run_id = uuid4().hex[:8]
        report = self._make_report(run_id)

        save_run(report)

        runs = list_runs(limit=100)
        run_ids = [r.run_id for r in runs]
        assert run_id in run_ids

        # Clean up
        delete_run(run_id)

    def test_delete_run_removes_it(self):
        """delete_run removes a run and get_run returns None."""
        run_id = uuid4().hex[:8]
        report = self._make_report(run_id)

        save_run(report)
        assert get_run(run_id) is not None

        deleted = delete_run(run_id)
        assert deleted is True

        assert get_run(run_id) is None

    def test_delete_nonexistent_returns_false(self):
        """delete_run returns False for nonexistent run."""
        run_id = f"nonexistent-{uuid4().hex[:8]}"
        deleted = delete_run(run_id)
        assert deleted is False

    # Helper
    def _make_report(self, run_id: str) -> PipelineReport:
        """Build a test PipelineReport."""
        report = PipelineReport(
            run_id=run_id,
            url="http://test.example.com",
            mode="sweep",
            intent="test sweep",
            escalated=False,
            cost_usd=0.123,
            duration_s=45.6,
        )

        # Add decisions
        report.decisions = [
            Decision.now(
                stage=Stage.EXPLORE,
                verdict="ok",
                reason="explored the site",
                next_stage=Stage.PLAN,
            ),
            Decision.now(
                stage=Stage.PLAN,
                verdict="ok",
                reason="planned the flows",
                next_stage=Stage.CRITIQUE,
            ),
        ]

        # Add gaps
        report.gaps = [
            Gap(
                kind="untested_form",
                description="Contact form not tested",
                evidence="Found on /contact page",
                severity=Severity.SERIOUS,
            ),
        ]

        # Add flow results
        report.flow_results["flow1"] = RunResult(
            test_id="flow1",
            status="passed",
            results=[
                StepResult(
                    step_id="step1",
                    status="passed",
                    source=Source.CACHE,
                    duration_ms=100.0,
                ),
            ],
            cost_usd=0.05,
            heals_used=0,
        )

        return report
