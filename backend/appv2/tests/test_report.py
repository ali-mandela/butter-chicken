import json
import pytest
from pathlib import Path
from datetime import datetime

from aivar.models import (
    CompiledTest,
    Finding,
    FindingKind,
    HealProposal,
    RunResult,
    Selector,
    Severity,
    Step,
    StepKind,
    StepResult,
    Source,
)
from aivar.report import render_text, render_json, write_report


@pytest.fixture
def sample_test():
    """Create a sample compiled test."""
    return CompiledTest(
        id="test_login",
        intent="Login to the application",
        url="https://example.com/login",
        steps=[
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="fill",
                target="username field",
                value="${AIVAR_USERNAME}",
            ),
            Step(
                id="s2",
                kind=StepKind.ACTION,
                verb="fill",
                target="password field",
                value="${AIVAR_PASSWORD}",
            ),
            Step(
                id="s3",
                kind=StepKind.ACTION,
                verb="click",
                target="login button",
            ),
        ],
    )


@pytest.fixture
def sample_result():
    """Create a sample run result."""
    return RunResult(
        test_id="test_login",
        status="passed",
        results=[
            StepResult(
                step_id="s1",
                status="passed",
                source=Source.CACHE,
                duration_ms=100.0,
            ),
            StepResult(
                step_id="s2",
                status="passed",
                source=Source.CACHE,
                duration_ms=150.0,
            ),
            StepResult(
                step_id="s3",
                status="passed",
                source=Source.CACHE,
                duration_ms=200.0,
            ),
        ],
        cost_usd=0.0040,
    )


class TestSummaryLine:
    """Test RunResult.summary_line property."""

    def test_passed_no_heals_no_findings(self):
        """Test summary line for passed with no heals and no findings."""
        result = RunResult(
            test_id="test1",
            status="passed",
            results=[],
            cost_usd=0.0040,
        )
        assert result.summary_line == "passed, $0.0040"

    def test_passed_with_1_heal_and_3_findings(self):
        """Test summary line with 1 heal and 3 findings."""
        result = RunResult(
            test_id="test1",
            status="passed",
            results=[],
            cost_usd=0.0040,
            heal_proposals=[
                HealProposal(
                    test_id="test1",
                    step_id="s1",
                    new=Selector(strategy="css", value=".btn"),
                    confidence=0.95,
                    reasoning="Found button",
                    semantic_match=True,
                )
            ],
            findings=[
                Finding(
                    kind=FindingKind.DESIGN_TOKEN,
                    severity=Severity.MODERATE,
                    rule="token-1",
                    message="Token mismatch",
                ),
                Finding(
                    kind=FindingKind.ACCESSIBILITY,
                    severity=Severity.SERIOUS,
                    rule="contrast",
                    message="Low contrast",
                ),
                Finding(
                    kind=FindingKind.VISUAL,
                    severity=Severity.MINOR,
                    rule="spacing",
                    message="Inconsistent spacing",
                ),
            ],
        )
        assert (
            result.summary_line
            == "passed, 1 heal pending approval, 3 design findings, $0.0040"
        )

    def test_failed_with_2_heals_and_1_finding(self):
        """Test summary line for failed with 2 heals and 1 finding."""
        result = RunResult(
            test_id="test1",
            status="failed",
            results=[],
            cost_usd=0.0020,
            heal_proposals=[
                HealProposal(
                    test_id="test1",
                    step_id="s1",
                    new=Selector(strategy="css", value=".btn"),
                    confidence=0.95,
                    reasoning="Found button",
                    semantic_match=True,
                ),
                HealProposal(
                    test_id="test1",
                    step_id="s2",
                    new=Selector(strategy="css", value=".input"),
                    confidence=0.90,
                    reasoning="Found input",
                    semantic_match=True,
                ),
            ],
            findings=[
                Finding(
                    kind=FindingKind.GEOMETRY,
                    severity=Severity.CRITICAL,
                    rule="layout",
                    message="Layout issue",
                ),
            ],
        )
        assert (
            result.summary_line
            == "failed, 2 heals pending approval, 1 design finding, $0.0020"
        )


class TestFindingsBySeverity:
    """Test RunResult.findings_by_severity property."""

    def test_findings_by_severity_counts_correctly(self):
        """Test that findings_by_severity counts correctly."""
        result = RunResult(
            test_id="test1",
            status="passed",
            results=[],
            findings=[
                Finding(
                    kind=FindingKind.ACCESSIBILITY,
                    severity=Severity.CRITICAL,
                    rule="r1",
                    message="m1",
                ),
                Finding(
                    kind=FindingKind.ACCESSIBILITY,
                    severity=Severity.CRITICAL,
                    rule="r2",
                    message="m2",
                ),
                Finding(
                    kind=FindingKind.DESIGN_TOKEN,
                    severity=Severity.SERIOUS,
                    rule="r3",
                    message="m3",
                ),
                Finding(
                    kind=FindingKind.VISUAL,
                    severity=Severity.MODERATE,
                    rule="r4",
                    message="m4",
                ),
            ],
        )
        counts = result.findings_by_severity
        assert counts[Severity.CRITICAL] == 2
        assert counts[Severity.SERIOUS] == 1
        assert counts[Severity.MODERATE] == 1
        assert counts[Severity.MINOR] == 0


class TestRenderText:
    """Test render_text function."""

    def test_render_text_includes_test_header(self, sample_test, sample_result):
        """Test that render_text includes test id and intent."""
        text = render_text(sample_test, sample_result)
        assert "Test: test_login" in text
        assert "Intent: Login to the application" in text

    def test_render_text_includes_every_step_target(self, sample_test, sample_result):
        """Test that render_text includes every step's target."""
        text = render_text(sample_test, sample_result)
        assert "username field" in text
        assert "password field" in text
        assert "login button" in text

    def test_render_text_includes_findings_section_when_present(self, sample_test):
        """Test that render_text includes findings section when findings exist."""
        result = RunResult(
            test_id="test_login",
            status="passed",
            results=[
                StepResult(
                    step_id="s1",
                    status="passed",
                    source=Source.CACHE,
                    duration_ms=100.0,
                ),
            ],
            findings=[
                Finding(
                    kind=FindingKind.ACCESSIBILITY,
                    severity=Severity.CRITICAL,
                    rule="contrast",
                    message="Low contrast on button",
                    target=".btn-primary",
                ),
            ],
        )
        text = render_text(sample_test, result)
        assert "FINDINGS:" in text
        assert "[critical] contrast — Low contrast on button (.btn-primary)" in text

    def test_render_text_omits_findings_section_when_empty(self, sample_test):
        """Test that render_text omits findings section when empty."""
        result = RunResult(
            test_id="test_login",
            status="passed",
            results=[
                StepResult(
                    step_id="s1",
                    status="passed",
                    source=Source.CACHE,
                    duration_ms=100.0,
                ),
            ],
        )
        text = render_text(sample_test, result)
        assert "FINDINGS:" not in text

    def test_render_text_orders_findings_critical_first(self, sample_test):
        """Test that render_text orders findings by severity (critical first)."""
        result = RunResult(
            test_id="test_login",
            status="passed",
            results=[
                StepResult(
                    step_id="s1",
                    status="passed",
                    source=Source.CACHE,
                    duration_ms=100.0,
                ),
            ],
            findings=[
                Finding(
                    kind=FindingKind.VISUAL,
                    severity=Severity.MINOR,
                    rule="r1",
                    message="Minor issue",
                ),
                Finding(
                    kind=FindingKind.ACCESSIBILITY,
                    severity=Severity.CRITICAL,
                    rule="r2",
                    message="Critical issue",
                ),
                Finding(
                    kind=FindingKind.DESIGN_TOKEN,
                    severity=Severity.SERIOUS,
                    rule="r3",
                    message="Serious issue",
                ),
            ],
        )
        text = render_text(sample_test, result)
        # Check ordering: critical first, then serious, then minor
        critical_pos = text.find("[critical]")
        serious_pos = text.find("[serious]")
        minor_pos = text.find("[minor]")
        assert critical_pos < serious_pos < minor_pos

    def test_render_text_omits_heals_section_when_empty(self, sample_test):
        """Test that render_text omits heals section when empty."""
        result = RunResult(
            test_id="test_login",
            status="passed",
            results=[
                StepResult(
                    step_id="s1",
                    status="passed",
                    source=Source.CACHE,
                    duration_ms=100.0,
                ),
            ],
        )
        text = render_text(sample_test, result)
        assert "HEALS PENDING APPROVAL:" not in text


class TestRenderJson:
    """Test render_json function."""

    def test_render_json_structure(self, sample_test, sample_result):
        """Test that render_json returns correct structure."""
        json_data = render_json(sample_test, sample_result)
        assert "test" in json_data
        assert "result" in json_data
        assert "generated_at" in json_data
        assert json_data["test"]["id"] == "test_login"
        assert json_data["result"]["test_id"] == "test_login"

    def test_render_json_generated_at_is_iso8601(self, sample_test, sample_result):
        """Test that generated_at is ISO-8601 formatted."""
        json_data = render_json(sample_test, sample_result)
        # Should end with Z indicating UTC
        assert json_data["generated_at"].endswith("Z")
        # Should be parseable as ISO format
        dt_str = json_data["generated_at"].replace("Z", "+00:00")
        datetime.fromisoformat(dt_str)  # Will raise if not valid


class TestWriteReport:
    """Test write_report function."""

    def test_write_report_creates_file(self, sample_test, sample_result, tmp_path):
        """Test that write_report creates a file."""
        report_path = write_report(sample_test, sample_result, out_dir=tmp_path)
        assert report_path.exists()
        assert report_path.is_file()

    def test_write_report_filename_contains_test_id(
        self, sample_test, sample_result, tmp_path
    ):
        """Test that filename contains test id."""
        report_path = write_report(sample_test, sample_result, out_dir=tmp_path)
        assert "test_login" in report_path.name

    def test_write_report_filename_contains_timestamp(
        self, sample_test, sample_result, tmp_path
    ):
        """Test that filename contains timestamp in YYYYmmdd-HHMMSS format."""
        report_path = write_report(sample_test, sample_result, out_dir=tmp_path)
        # Should have pattern like: test_login-20231225-143022.json
        parts = report_path.stem.split("-")
        assert len(parts) >= 3  # id, date, time
        date_part = "-".join(parts[1:3])
        # Check date format (8 digits, hyphen, 6 digits)
        assert len(date_part) == 15  # YYYYmmdd-HHMMSS

    def test_write_report_json_round_trips(
        self, sample_test, sample_result, tmp_path
    ):
        """Test that JSON round-trips correctly."""
        report_path = write_report(sample_test, sample_result, out_dir=tmp_path)
        with open(report_path) as f:
            loaded = json.load(f)

        assert loaded["test"]["id"] == sample_test.id
        assert loaded["result"]["test_id"] == sample_result.test_id
        assert loaded["result"]["status"] == sample_result.status

    def test_write_report_creates_directory(self, sample_test, sample_result, tmp_path):
        """Test that write_report creates the output directory if it doesn't exist."""
        out_dir = tmp_path / "nested" / "report" / "dir"
        report_path = write_report(sample_test, sample_result, out_dir=out_dir)
        assert report_path.exists()


class TestFindingRoundTrip:
    """Test Finding.to_dict() and Finding.from_dict()."""

    def test_finding_round_trips(self):
        """Test that Finding round-trips through to_dict/from_dict."""
        original = Finding(
            kind=FindingKind.ACCESSIBILITY,
            severity=Severity.CRITICAL,
            rule="contrast-minimum",
            message="Text contrast is too low",
            target=".button",
            step_id="s1",
            details={"contrast_ratio": 2.5, "required": 4.5},
        )
        d = original.to_dict()
        restored = Finding.from_dict(d)
        assert restored == original

    def test_finding_to_dict_omits_none_fields(self):
        """Test that to_dict omits None fields."""
        finding = Finding(
            kind=FindingKind.VISUAL,
            severity=Severity.MINOR,
            rule="spacing",
            message="Inconsistent spacing",
        )
        d = finding.to_dict()
        assert "target" not in d
        assert "step_id" not in d
        assert "details" not in d


class TestRunResultToDict:
    """Test RunResult.to_dict() includes findings and heal_proposals."""

    def test_run_result_to_dict_includes_findings(self):
        """Test that to_dict includes findings."""
        result = RunResult(
            test_id="test1",
            status="passed",
            results=[],
            findings=[
                Finding(
                    kind=FindingKind.ACCESSIBILITY,
                    severity=Severity.CRITICAL,
                    rule="r1",
                    message="m1",
                ),
            ],
        )
        d = result.to_dict()
        assert "findings" in d
        assert len(d["findings"]) == 1
        assert d["findings"][0]["rule"] == "r1"

    def test_run_result_to_dict_includes_heal_proposals(self):
        """Test that to_dict includes heal_proposals."""
        result = RunResult(
            test_id="test1",
            status="passed",
            results=[],
            heal_proposals=[
                HealProposal(
                    test_id="test1",
                    step_id="s1",
                    new=Selector(strategy="css", value=".btn"),
                    confidence=0.95,
                    reasoning="Found button",
                    semantic_match=True,
                ),
            ],
        )
        d = result.to_dict()
        assert "heal_proposals" in d
        assert len(d["heal_proposals"]) == 1


class TestRunResultBackwardsCompatibility:
    """Test that old-style RunResult construction still works."""

    def test_run_result_old_way_still_works(self):
        """Test that RunResult built the old way (no findings/heal_proposals) works."""
        result = RunResult(
            test_id="test1",
            status="passed",
            results=[
                StepResult(
                    step_id="s1",
                    status="passed",
                    source=Source.CACHE,
                    duration_ms=100.0,
                ),
            ],
            cost_usd=0.001,
            heals_used=0,
        )
        # Should have empty lists
        assert result.findings == []
        assert result.heal_proposals == []
        # Should report empty in summary
        assert "design findings" not in result.summary_line
        assert "heals pending" not in result.summary_line

    def test_from_results_without_findings_and_heal_proposals(self):
        """Test that from_results works without findings and heal_proposals."""
        results = [
            StepResult(
                step_id="s1",
                status="passed",
                source=Source.CACHE,
                duration_ms=100.0,
            ),
        ]
        run_result = RunResult.from_results("test1", results, cost_usd=0.001)
        assert run_result.findings == []
        assert run_result.heal_proposals == []

    def test_from_results_with_findings_and_heal_proposals(self):
        """Test that from_results accepts optional findings and heal_proposals."""
        results = [
            StepResult(
                step_id="s1",
                status="passed",
                source=Source.CACHE,
                duration_ms=100.0,
            ),
        ]
        findings = [
            Finding(
                kind=FindingKind.ACCESSIBILITY,
                severity=Severity.CRITICAL,
                rule="r1",
                message="m1",
            ),
        ]
        heal_proposals = [
            HealProposal(
                test_id="test1",
                step_id="s1",
                new=Selector(strategy="css", value=".btn"),
                confidence=0.95,
                reasoning="Found button",
                semantic_match=True,
            ),
        ]
        run_result = RunResult.from_results(
            "test1",
            results,
            cost_usd=0.001,
            findings=findings,
            heal_proposals=heal_proposals,
        )
        assert len(run_result.findings) == 1
        assert len(run_result.heal_proposals) == 1
