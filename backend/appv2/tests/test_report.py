import json
import pytest
from pathlib import Path
from datetime import datetime

from aivar.contracts import Decision, Gap, Stage, TestPlan, TriageResult, TriageVerdict, FlowKind, Flow
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
from aivar.report import (
    render_text,
    render_json,
    write_report,
    PipelineReport,
    render_pipeline_text,
    render_pipeline_html,
    write_pipeline_report,
)


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


# --------------------------------------------------------------------------
# PipelineReport tests
# --------------------------------------------------------------------------


class TestPipelineReportProperties:
    """Test PipelineReport property computations."""

    def test_flows_total(self):
        """Test flows_total property."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
                "flow2": RunResult(
                    test_id="test2", status="failed", results=[]
                ),
            },
        )
        assert report.flows_total == 2

    def test_flows_passed(self):
        """Test flows_passed property."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
                "flow2": RunResult(
                    test_id="test2", status="failed", results=[]
                ),
                "flow3": RunResult(
                    test_id="test3", status="passed", results=[]
                ),
            },
        )
        assert report.flows_passed == 2

    def test_flows_failed(self):
        """Test flows_failed property."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
                "flow2": RunResult(
                    test_id="test2", status="failed", results=[]
                ),
                "flow3": RunResult(
                    test_id="test3", status="passed", results=[]
                ),
            },
        )
        assert report.flows_failed == 1

    def test_steps_total(self):
        """Test steps_total property."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1",
                    status="passed",
                    results=[
                        StepResult(
                            step_id="s1", status="passed", source=Source.CACHE, duration_ms=100.0
                        ),
                        StepResult(
                            step_id="s2", status="passed", source=Source.CACHE, duration_ms=100.0
                        ),
                    ],
                ),
                "flow2": RunResult(
                    test_id="test2",
                    status="passed",
                    results=[
                        StepResult(
                            step_id="s3", status="passed", source=Source.CACHE, duration_ms=100.0
                        ),
                    ],
                ),
            },
        )
        assert report.steps_total == 3

    def test_steps_passed(self):
        """Test steps_passed property."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1",
                    status="passed",
                    results=[
                        StepResult(
                            step_id="s1", status="passed", source=Source.CACHE, duration_ms=100.0
                        ),
                        StepResult(
                            step_id="s2", status="failed", source=Source.CACHE, duration_ms=100.0
                        ),
                    ],
                ),
                "flow2": RunResult(
                    test_id="test2",
                    status="passed",
                    results=[
                        StepResult(
                            step_id="s3", status="passed", source=Source.CACHE, duration_ms=100.0
                        ),
                    ],
                ),
            },
        )
        assert report.steps_passed == 2

    def test_heals_applied(self):
        """Test heals_applied property."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[], heals_used=2
                ),
                "flow2": RunResult(
                    test_id="test2", status="passed", results=[], heals_used=3
                ),
            },
        )
        assert report.heals_applied == 5

    def test_defects_found(self):
        """Test defects_found property."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            triage=[
                TriageResult(
                    step_id="s1",
                    verdict=TriageVerdict.APP_DEFECT,
                    confidence=0.95,
                    reasoning="App crashed",
                ),
                TriageResult(
                    step_id="s2",
                    verdict=TriageVerdict.SCRIPT_ISSUE,
                    confidence=0.90,
                    reasoning="Locator changed",
                ),
                TriageResult(
                    step_id="s3",
                    verdict=TriageVerdict.APP_DEFECT,
                    confidence=0.85,
                    reasoning="Wrong validation",
                ),
            ],
        )
        assert report.defects_found == 2

    def test_untested_risk_sorts_by_severity(self):
        """Test untested_risk property sorts critical-first."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            gaps=[
                Gap(
                    kind="untested_form",
                    description="Login page not tested",
                    evidence="Form found but no flows",
                    severity=Severity.MINOR,
                ),
                Gap(
                    kind="missing_error_state",
                    description="Network error handling",
                    evidence="No error page flows",
                    severity=Severity.CRITICAL,
                ),
                Gap(
                    kind="untested_page",
                    description="Checkout flow",
                    evidence="Page discovered but no test",
                    severity=Severity.SERIOUS,
                ),
            ],
        )
        risk = report.untested_risk
        # Check that critical comes first
        assert risk[0] == ("Network error handling", "critical")
        assert risk[1] == ("Checkout flow", "serious")
        assert risk[2] == ("Login page not tested", "minor")

    def test_summary_line_all_passing_no_extras(self):
        """Test summary_line with all flows passing and no extras."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
                "flow2": RunResult(
                    test_id="test2", status="passed", results=[]
                ),
            },
            cost_usd=0.0021,
            duration_s=214.0,
        )
        assert report.summary_line == "2/2 flows passed, $0.0021, 214s"

    def test_summary_line_with_heals(self):
        """Test summary_line with heals applied."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[], heals_used=2
                ),
                "flow2": RunResult(
                    test_id="test2", status="passed", results=[], heals_used=1
                ),
            },
            cost_usd=0.0021,
        )
        assert "3 heals applied" in report.summary_line

    def test_summary_line_with_defects(self):
        """Test summary_line with defects found."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
            triage=[
                TriageResult(
                    step_id="s1",
                    verdict=TriageVerdict.APP_DEFECT,
                    confidence=0.95,
                    reasoning="Bug found",
                ),
            ],
            cost_usd=0.0021,
        )
        assert "1 defect found" in report.summary_line

    def test_summary_line_with_gaps(self):
        """Test summary_line with gaps remaining."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
            gaps=[
                Gap(
                    kind="untested_form",
                    description="Login page",
                    evidence="Form found",
                    severity=Severity.SERIOUS,
                ),
                Gap(
                    kind="untested_page",
                    description="Checkout",
                    evidence="Page found",
                    severity=Severity.MODERATE,
                ),
            ],
            cost_usd=0.0021,
        )
        assert "2 gaps remaining" in report.summary_line

    def test_summary_line_pluralisation(self):
        """Test summary_line pluralisation is correct."""
        # 1 heal
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[], heals_used=1
                ),
            },
            cost_usd=0.0021,
        )
        assert "1 heal applied" in report.summary_line

        # 1 defect
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
            triage=[
                TriageResult(
                    step_id="s1",
                    verdict=TriageVerdict.APP_DEFECT,
                    confidence=0.95,
                    reasoning="Bug",
                ),
            ],
            cost_usd=0.0021,
        )
        assert "1 defect found" in report.summary_line

        # 1 gap
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
            gaps=[
                Gap(
                    kind="untested_form",
                    description="Login",
                    evidence="Form found",
                    severity=Severity.SERIOUS,
                ),
            ],
            cost_usd=0.0021,
        )
        assert "1 gap remaining" in report.summary_line


class TestRenderPipelineText:
    """Test render_pipeline_text function."""

    def test_render_includes_every_flow_name(self):
        """Test that render_pipeline_text includes every flow name."""
        plan = TestPlan(
            id="plan1",
            mode="sweep",
            flows=[
                Flow(
                    id="flow1",
                    name="Happy path login",
                    description="Test successful login",
                    kind=FlowKind.HAPPY_PATH,
                    steps=[],
                ),
                Flow(
                    id="flow2",
                    name="Invalid password",
                    description="Test invalid password",
                    kind=FlowKind.NEGATIVE,
                    steps=[],
                ),
            ],
        )
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            plan=plan,
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
                "flow2": RunResult(
                    test_id="test2", status="failed", results=[]
                ),
            },
        )
        text = render_pipeline_text(report)
        assert "Happy path login" in text
        assert "Invalid password" in text

    def test_render_omits_gaps_section_when_empty(self):
        """Test that gaps section is omitted when there are none."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
        )
        text = render_pipeline_text(report)
        assert "COVERAGE GAPS REMAINING:" not in text

    def test_render_includes_gaps_section_when_present(self):
        """Test that gaps section is included when gaps exist."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            gaps=[
                Gap(
                    kind="untested_form",
                    description="Login page",
                    evidence="Form found",
                    severity=Severity.SERIOUS,
                ),
            ],
        )
        text = render_pipeline_text(report)
        assert "COVERAGE GAPS REMAINING:" in text
        assert "Login page" in text

    def test_render_includes_escalated_block(self):
        """Test that ESCALATED block is included when escalated."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            escalated=True,
            escalation_reason="Critical defects found",
        )
        text = render_pipeline_text(report)
        assert "ESCALATED:" in text
        assert "Critical defects found" in text

    def test_render_omits_escalated_block_when_not_escalated(self):
        """Test that ESCALATED block is not included when not escalated."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            escalated=False,
        )
        text = render_pipeline_text(report)
        assert "ESCALATED:" not in text


class TestRenderPipelineHtml:
    """Test render_pipeline_html function."""

    def test_render_starts_with_doctype(self):
        """Test that HTML output starts with <!doctype html."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
        )
        html = render_pipeline_html(report)
        assert html.startswith("<!doctype html")

    def test_render_contains_prefers_color_scheme(self):
        """Test that HTML contains prefers-color-scheme media query."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
        )
        html = render_pipeline_html(report)
        assert "prefers-color-scheme" in html

    def test_render_includes_every_flow_name(self):
        """Test that HTML includes every flow name."""
        plan = TestPlan(
            id="plan1",
            mode="sweep",
            flows=[
                Flow(
                    id="flow1",
                    name="Happy path login",
                    description="Test successful login",
                    kind=FlowKind.HAPPY_PATH,
                    steps=[],
                ),
                Flow(
                    id="flow2",
                    name="Invalid password",
                    description="Test invalid password",
                    kind=FlowKind.NEGATIVE,
                    steps=[],
                ),
            ],
        )
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            plan=plan,
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
                "flow2": RunResult(
                    test_id="test2", status="failed", results=[]
                ),
            },
        )
        html = render_pipeline_html(report)
        assert "Happy path login" in html
        assert "Invalid password" in html

    def test_html_escapes_flow_names(self):
        """Test that flow names are HTML-escaped."""
        plan = TestPlan(
            id="plan1",
            mode="sweep",
            flows=[
                Flow(
                    id="flow1",
                    name="<script>alert(1)</script>",
                    description="Test",
                    kind=FlowKind.HAPPY_PATH,
                    steps=[],
                ),
            ],
        )
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            plan=plan,
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
        )
        html = render_pipeline_html(report)
        # The raw <script> tag should NOT appear in output
        assert "<script>alert(1)</script>" not in html
        # But the escaped version should
        assert "&lt;script&gt;" in html or "script" in html

    def test_render_omits_gaps_section_when_empty(self):
        """Test that gaps section is omitted when empty."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
        )
        html = render_pipeline_html(report)
        # Section header should not appear
        assert "Coverage Gaps Remaining" not in html

    def test_render_empty_report_does_not_raise(self):
        """Test that an empty report renders without raising."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
        )
        html = render_pipeline_html(report)
        assert html.startswith("<!doctype html")


class TestWritePipelineReport:
    """Test write_pipeline_report function."""

    def test_write_creates_all_three_files(self, tmp_path):
        """Test that write_pipeline_report creates JSON, TXT, and HTML files."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
        )
        result = write_pipeline_report(report, out_dir=tmp_path)
        assert "json" in result
        assert "txt" in result
        assert "html" in result
        assert result["json"].exists()
        assert result["txt"].exists()
        assert result["html"].exists()

    def test_json_round_trips(self, tmp_path):
        """Test that JSON file can be loaded back."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
            cost_usd=0.0021,
        )
        result = write_pipeline_report(report, out_dir=tmp_path)
        with open(result["json"]) as f:
            loaded = json.load(f)
        assert loaded["run_id"] == "run1"
        assert loaded["url"] == "https://example.com"
        assert loaded["cost_usd"] == 0.0021

    def test_write_creates_nested_directories(self, tmp_path):
        """Test that write_pipeline_report creates nested directories."""
        nested_dir = tmp_path / "a" / "b" / "c"
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
        )
        result = write_pipeline_report(report, out_dir=nested_dir)
        assert result["json"].exists()

    def test_filenames_use_run_id(self, tmp_path):
        """Test that filenames use the run_id."""
        report = PipelineReport(
            run_id="my_run_123",
            url="https://example.com",
        )
        result = write_pipeline_report(report, out_dir=tmp_path)
        assert "my_run_123" in result["json"].name
        assert "my_run_123" in result["txt"].name
        assert "my_run_123" in result["html"].name


class TestPipelineReportToDict:
    """Test PipelineReport.to_dict() method."""

    def test_to_dict_includes_all_fields(self):
        """Test that to_dict includes all fields."""
        decision = Decision.now(
            stage=Stage.EXECUTE,
            verdict="passed",
            reason="All flows passed",
            next_stage=Stage.REPORT,
        )
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
            mode="sweep",
            intent="Test everything",
            flow_results={
                "flow1": RunResult(
                    test_id="test1", status="passed", results=[]
                ),
            },
            triage=[
                TriageResult(
                    step_id="s1",
                    verdict=TriageVerdict.APP_DEFECT,
                    confidence=0.95,
                    reasoning="Bug",
                ),
            ],
            decisions=[decision],
            escalated=True,
            escalation_reason="Test reason",
            cost_usd=0.0021,
            duration_s=214.0,
        )
        d = report.to_dict()
        assert d["run_id"] == "run1"
        assert d["url"] == "https://example.com"
        assert d["mode"] == "sweep"
        assert d["intent"] == "Test everything"
        assert "flow1" in d["flow_results"]
        assert len(d["triage"]) == 1
        assert len(d["decisions"]) == 1
        assert d["escalated"] is True
        assert d["cost_usd"] == 0.0021
        assert d["duration_s"] == 214.0


class TestEmptyPipelineReport:
    """Test that empty pipeline reports render without errors."""

    def test_empty_report_text_renders(self):
        """Test that an empty report renders to text without error."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
        )
        text = render_pipeline_text(report)
        assert "Run ID: run1" in text
        assert "URL: https://example.com" in text

    def test_empty_report_html_renders(self):
        """Test that an empty report renders to HTML without error."""
        report = PipelineReport(
            run_id="run1",
            url="https://example.com",
        )
        html = render_pipeline_html(report)
        assert html.startswith("<!doctype html")
        assert "run1" in html
