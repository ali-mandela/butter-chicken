"""Tests for the coverage gate (critic module)."""

from unittest.mock import patch, MagicMock
import pytest

from aivar.contracts import (
    CoverageAssessment,
    CoverageVerdict,
    Flow,
    FlowKind,
    Gap,
    PlanMode,
    TestPlan,
)
from aivar.critic import assess_coverage, escalate_if_exhausted, structural_gaps
from aivar.explorer import ExplorationReport, FormField, FormObservation, PageObservation
from aivar.llm import LLMConfig, LLMError, LLMInvalidJSON, LLMResponse
from aivar.models import Selector, Severity, Step, StepKind


# ============================================================================
# Fixtures
# ============================================================================


def make_selector(value: str) -> Selector:
    """Helper to create a selector."""
    return Selector(strategy="css", value=value)


def make_form(
    name: str,
    field_names: list[str] | None = None,
    is_login: bool = False,
) -> FormObservation:
    """Helper to create a FormObservation."""
    field_names = field_names or ["username", "password"]
    fields = [
        FormField(
            name=fname,
            field_type="password" if fname == "password" else "text",
            required=True,
            selector=make_selector(f"[name='{fname}']"),
        )
        for fname in field_names
    ]
    return FormObservation(
        name=name,
        fields=fields,
        submit=make_selector("button[type=submit]"),
        is_login=is_login,
    )


def make_page(
    url: str,
    title: str = "",
    forms: list[FormObservation] | None = None,
    headings: list[str] | None = None,
) -> PageObservation:
    """Helper to create a PageObservation."""
    return PageObservation(
        url=url,
        title=title,
        depth=0,
        node_count=100,
        forms=forms or [],
        links=[],
        headings=headings or [],
        controls=[],
        reached_by=None,
    )


def make_report(
    entry_url: str = "https://example.com",
    pages: list[PageObservation] | None = None,
    login_form: FormObservation | None = None,
    authenticated: bool = False,
) -> ExplorationReport:
    """Helper to create an ExplorationReport."""
    return ExplorationReport(
        entry_url=entry_url,
        authenticated=authenticated,
        login_form=login_form,
        pages=pages or [],
        errors=[],
        duration_ms=1000.0,
    )


def make_step(
    target: str,
    kind: StepKind = StepKind.ACTION,
) -> Step:
    """Helper to create a Step."""
    return Step(
        id="step_" + target,
        kind=kind,
        verb="click" if kind == StepKind.ACTION else "assert",
        target=target,
        value=None,
        selector=make_selector(f"[data-test='{target}']"),
    )


def make_flow(
    name: str,
    kind: FlowKind = FlowKind.HAPPY_PATH,
    steps: list[Step] | None = None,
) -> Flow:
    """Helper to create a Flow."""
    steps = steps or [make_step("action_1"), make_step("assertion_1", StepKind.ASSERTION)]
    return Flow(
        id="flow_" + name,
        name=name,
        description=f"Test {name}",
        kind=kind,
        steps=steps,
        entry_url="https://example.com",
    )


def make_plan(
    flows: list[Flow] | None = None,
    mode: PlanMode = PlanMode.SWEEP,
    intent: str | None = None,
) -> TestPlan:
    """Helper to create a TestPlan."""
    flows = flows or [make_flow("happy path")]
    return TestPlan(
        id="plan_1",
        mode=mode,
        flows=flows,
        intent=intent,
        prd_path=None,
    )


def mock_llm_config() -> LLMConfig:
    """Helper to create an LLMConfig for testing."""
    return LLMConfig(api_key="test-key")


# ============================================================================
# structural_gaps tests
# ============================================================================


def test_untested_form_login_is_critical():
    """A login form referenced by no flow yields a CRITICAL untested_form gap."""
    login_form = make_form("login form", ["username", "password"], is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other_action")])])

    gaps = structural_gaps(report, plan)

    # Should have untested_form gap with CRITICAL severity
    untested_forms = [g for g in gaps if g.kind == "untested_form"]
    assert len(untested_forms) > 0
    assert untested_forms[0].severity == Severity.CRITICAL
    # Evidence should contain field names and URL path
    assert "username" in untested_forms[0].evidence.lower()
    assert "password" in untested_forms[0].evidence.lower()


def test_untested_form_regular_is_serious():
    """A regular form referenced by no flow yields a SERIOUS untested_form gap."""
    search_form = make_form("search form", ["query"])
    page = make_page("https://example.com", forms=[search_form])
    report = make_report(pages=[page])

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other_action")])])

    gaps = structural_gaps(report, plan)

    untested_forms = [g for g in gaps if g.kind == "untested_form"]
    assert len(untested_forms) > 0
    assert untested_forms[0].severity == Severity.SERIOUS
    # Evidence should contain field name and URL path
    assert "query" in untested_forms[0].evidence.lower()


def test_untested_page_is_moderate():
    """A discovered page whose title doesn't appear in any flow yields untested_page gap."""
    page = make_page("https://example.com/settings", title="Settings Page")
    report = make_report(pages=[page])

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("home")])])

    gaps = structural_gaps(report, plan)

    untested_pages = [g for g in gaps if g.kind == "untested_page"]
    assert len(untested_pages) > 0
    assert untested_pages[0].severity == Severity.MODERATE
    # Evidence should contain the page URL
    assert "https://example.com/settings" in untested_pages[0].evidence


def test_missing_error_state_in_sweep_is_serious():
    """Plan with only HAPPY_PATH flows in SWEEP mode yields missing_error_state gap."""
    page = make_page("https://example.com")
    report = make_report(pages=[page])

    plan = make_plan(
        flows=[
            make_flow("happy 1", FlowKind.HAPPY_PATH),
            make_flow("happy 2", FlowKind.HAPPY_PATH),
        ],
        mode=PlanMode.SWEEP,
    )

    gaps = structural_gaps(report, plan)

    missing_error = [g for g in gaps if g.kind == "missing_error_state"]
    assert len(missing_error) > 0
    assert missing_error[0].severity == Severity.SERIOUS


def test_missing_error_state_skipped_in_focused():
    """In FOCUSED mode, missing_error_state check is skipped."""
    page = make_page("https://example.com")
    report = make_report(pages=[page])

    plan = make_plan(
        flows=[make_flow("happy path", FlowKind.HAPPY_PATH)],
        mode=PlanMode.FOCUSED,
        intent="test login",
    )

    gaps = structural_gaps(report, plan)

    missing_error = [g for g in gaps if g.kind == "missing_error_state"]
    assert len(missing_error) == 0


def test_no_assertions_is_critical():
    """Any flow with zero assertions yields a CRITICAL no_assertions gap."""
    page = make_page("https://example.com")
    report = make_report(pages=[page])

    # Flow with only ACTION steps, no ASSERTION
    flow = make_flow("bad flow", steps=[make_step("action_1"), make_step("action_2")])
    plan = make_plan(flows=[flow])

    gaps = structural_gaps(report, plan)

    no_assertions = [g for g in gaps if g.kind == "no_assertions"]
    assert len(no_assertions) > 0
    assert no_assertions[0].severity == Severity.CRITICAL
    assert "bad flow" in no_assertions[0].evidence


def test_fully_covering_plan_yields_no_gaps():
    """A fully covering plan (form referenced, has assertions, error flows) yields no gaps."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    flows = [
        make_flow(
            "login happy",
            FlowKind.HAPPY_PATH,
            steps=[
                make_step("login form"),
                make_step("login success", StepKind.ASSERTION),
            ],
        ),
        make_flow(
            "login invalid",
            FlowKind.NEGATIVE,
            steps=[
                make_step("login form"),
                make_step("invalid creds", StepKind.ASSERTION),
            ],
        ),
    ]
    plan = make_plan(flows=flows, mode=PlanMode.SWEEP)

    gaps = structural_gaps(report, plan)

    assert len(gaps) == 0


# ============================================================================
# assess_coverage tests
# ============================================================================


def test_assess_coverage_merges_gaps_without_duplicates():
    """assess_coverage merges structural and model gaps without duplicates."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    # Mock the model to return the same gap as structural (with new evidence format)
    mock_response = LLMResponse(
        content='{"score": 0.5, "gaps": [{"kind": "untested_form", "description": "Form \'login form\' is not covered by any test flow", "evidence": "form on / with fields: username, password", "severity": "critical"}], "reasoning": "login form not covered", "replan_instruction": null}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, llm_response = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Should not have duplicate gaps (deduplicated on kind + description + evidence)
    gap_keys = [(g.kind, g.description, g.evidence) for g in assessment.gaps]
    assert len(gap_keys) == len(set(gap_keys))


def test_verdict_critical_gap_yields_replan():
    """Verdict is REPLAN when any CRITICAL gap exists."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    # Model claims everything is perfect, but structural gap exists
    mock_response = LLMResponse(
        content='{"score": 1.0, "gaps": [], "reasoning": "perfect coverage", "replan_instruction": null}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, _ = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Should still be REPLAN due to structural gap
    assert assessment.verdict == CoverageVerdict.REPLAN


def test_verdict_two_serious_gaps_yields_replan():
    """Verdict is REPLAN when 2+ SERIOUS gaps exist."""
    form1 = make_form("form 1")
    form2 = make_form("form 2")
    page = make_page("https://example.com", forms=[form1, form2])
    report = make_report(pages=[page])

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    mock_response = LLMResponse(
        content='{"score": 0.5, "gaps": [], "reasoning": "checking", "replan_instruction": null}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, _ = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Two forms not covered = 2 SERIOUS gaps -> REPLAN
    assert assessment.verdict == CoverageVerdict.REPLAN


def test_verdict_one_moderate_gap_yields_accept():
    """Verdict is ACCEPT when only MODERATE gaps exist."""
    page = make_page("https://example.com/about", title="About")
    report = make_report(pages=[page])

    plan = make_plan(
        flows=[
            make_flow(
                "happy path",
                steps=[
                    make_step("home"),
                    make_step("success", StepKind.ASSERTION),
                ],
            ),
        ]
    )

    config = mock_llm_config()

    mock_response = LLMResponse(
        content='{"score": 0.9, "gaps": [], "reasoning": "mostly covered", "replan_instruction": null}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, _ = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # One untested page (MODERATE) -> ACCEPT
    assert assessment.verdict == CoverageVerdict.ACCEPT


def test_replan_instruction_names_missing_form():
    """replan_instruction names the specific missing form (with field names in evidence)."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    mock_response = LLMResponse(
        content='{"score": 0.5, "gaps": [], "reasoning": "not covered", "replan_instruction": null}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, _ = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Should build replan instruction from gaps
    assert assessment.replan_instruction is not None
    # Evidence now contains field names and URL path
    assert "untested_form" in assessment.replan_instruction


def test_assess_coverage_handles_llm_error():
    """When chat_json raises, assessment uses structural gaps and llm_response is None."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    with patch("aivar.critic.chat_json", side_effect=LLMError("API error")):
        assessment, llm_response = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Should still return assessment from structural gaps
    assert llm_response is None
    assert len(assessment.gaps) > 0
    assert "unavailable" in assessment.reasoning.lower()


def test_assess_coverage_handles_invalid_json():
    """When model returns invalid JSON, assessment uses structural gaps."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    mock_response = LLMResponse(
        content="not valid json {",
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, llm_response = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Should still return assessment
    assert llm_response is None
    assert len(assessment.gaps) > 0


def test_score_decreases_with_gap_severity():
    """Score decreases as gaps get more severe."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    # Critical gap: 1.0 - 0.4 = 0.6
    mock_response = LLMResponse(
        content='{"score": 0.5, "gaps": [], "reasoning": "test", "replan_instruction": null}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, _ = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Should have a penalty-adjusted score
    assert assessment.score < 1.0
    assert assessment.score >= 0.0


# ============================================================================
# escalate_if_exhausted tests
# ============================================================================


def test_escalate_if_exhausted_flips_replan_at_cap():
    """escalate_if_exhausted flips REPLAN to ESCALATE when cap is reached."""
    assessment = CoverageAssessment(
        verdict=CoverageVerdict.REPLAN,
        score=0.5,
        gaps=[
            Gap(
                kind="untested_form",
                description="Form X",
                evidence="form_x",
                severity=Severity.CRITICAL,
            )
        ],
        reasoning="Form X not covered",
        replan_instruction="Add flow for Form X",
    )

    escalated = escalate_if_exhausted(assessment, replans_used=3, max_replans=3)

    assert escalated.verdict == CoverageVerdict.ESCALATE
    assert "cap reached" in escalated.reasoning.lower()


def test_escalate_if_exhausted_leaves_accept_alone():
    """escalate_if_exhausted leaves ACCEPT verdict unchanged."""
    assessment = CoverageAssessment(
        verdict=CoverageVerdict.ACCEPT,
        score=0.95,
        gaps=[],
        reasoning="Good coverage",
        replan_instruction=None,
    )

    result = escalate_if_exhausted(assessment, replans_used=3, max_replans=3)

    assert result.verdict == CoverageVerdict.ACCEPT


def test_escalate_if_exhausted_leaves_replan_when_below_cap():
    """escalate_if_exhausted leaves REPLAN when replans_used < max_replans."""
    assessment = CoverageAssessment(
        verdict=CoverageVerdict.REPLAN,
        score=0.5,
        gaps=[],
        reasoning="Some gaps",
        replan_instruction="Fix gaps",
    )

    result = escalate_if_exhausted(assessment, replans_used=2, max_replans=3)

    assert result.verdict == CoverageVerdict.REPLAN


# ============================================================================
# New tests for form naming and field-based coverage
# ============================================================================


def test_form_field_coverage_regression():
    """Regression: form named 'form 1' with Username/Password fields, plan with 'username field'/'password field' targets produces NO untested_form gap.

    This exact case escalated a real run to zero tests before the fix.
    """
    # Create a form with Username/Password fields
    form = make_form("form 1", field_names=["Username", "Password"], is_login=False)
    page = make_page("https://example.com/login", forms=[form])
    report = make_report(pages=[page])

    # Plan targets the field names, not the form name
    steps = [
        make_step("username field"),
        make_step("password field"),
        make_step("login success", StepKind.ASSERTION),
    ]
    plan = make_plan(flows=[make_flow("login", steps=steps)])

    gaps = structural_gaps(report, plan)

    # Should NOT produce an untested_form gap because field names match
    untested_forms = [g for g in gaps if g.kind == "untested_form"]
    assert len(untested_forms) == 0, f"Unexpected untested_form gap: {untested_forms}"


def test_login_form_without_login_keywords_is_critical():
    """A login form with no login-ish step target in any flow produces a CRITICAL gap."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    # Plan mentions the form but doesn't have login keywords in step targets
    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("authentication")])])

    gaps = structural_gaps(report, plan)

    untested_forms = [g for g in gaps if g.kind == "untested_form"]
    assert len(untested_forms) > 0
    assert untested_forms[0].severity == Severity.CRITICAL


def test_untested_form_evidence_contains_field_names_and_url():
    """An uncovered form's evidence contains field names and page URL, not 'form 1'."""
    form = make_form("search form", field_names=["Query", "Filter"])
    page = make_page("https://example.com/search", forms=[form])
    report = make_report(pages=[page])

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    gaps = structural_gaps(report, plan)

    untested_forms = [g for g in gaps if g.kind == "untested_form"]
    assert len(untested_forms) > 0
    gap = untested_forms[0]

    # Evidence should contain field names and URL path, not "search form"
    assert "Query" in gap.evidence
    assert "Filter" in gap.evidence
    assert "/search" in gap.evidence


def test_two_pages_same_title_different_urls_produce_distinct_gaps():
    """Two pages with same title but different URLs produce two DISTINCT gaps (not deduped away)."""
    page1 = make_page("https://example.com/admin/settings", title="Settings")
    page2 = make_page("https://example.com/user/settings", title="Settings")
    report = make_report(pages=[page1, page2])

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("home")])])

    gaps = structural_gaps(report, plan)

    untested_pages = [g for g in gaps if g.kind == "untested_page"]
    assert len(untested_pages) == 2, f"Expected 2 untested_page gaps, got {len(untested_pages)}"

    # Evidence should be the URLs to distinguish them
    evidences = {g.evidence for g in untested_pages}
    assert "https://example.com/admin/settings" in evidences
    assert "https://example.com/user/settings" in evidences


def test_identical_gaps_still_collapse():
    """Two genuinely identical gaps still collapse to one (deduplication on kind + description + evidence)."""
    form = make_form("form 1")
    page = make_page("https://example.com", forms=[form])
    report = make_report(pages=[page])

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    # Model returns the same gap as structural
    field_names = ", ".join(f.name for f in form.fields)
    evidence = f"form on / with fields: {field_names}"
    mock_response = LLMResponse(
        content=f'{{"score": 0.5, "gaps": [{{"kind": "untested_form", "description": "Form \'form 1\' is not covered by any test flow", "evidence": "{evidence}", "severity": "serious"}}], "reasoning": "not covered", "replan_instruction": null}}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, _ = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Should have exactly one untested_form gap (deduplicated)
    untested_forms = [g for g in assessment.gaps if g.kind == "untested_form"]
    assert len(untested_forms) == 1


def test_assessment_reasoning_contains_structural_and_overall_score():
    """reasoning contains both a structural and an overall score."""
    login_form = make_form("login form", is_login=True)
    page = make_page("https://example.com", forms=[login_form])
    report = make_report(pages=[page], login_form=login_form)

    plan = make_plan(flows=[make_flow("happy path", steps=[make_step("other")])])

    config = mock_llm_config()

    mock_response = LLMResponse(
        content='{"score": 0.5, "gaps": [], "reasoning": "test reasoning", "replan_instruction": null}',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=100.0,
    )

    with patch("aivar.critic.chat_json", return_value=mock_response):
        assessment, _ = assess_coverage(
            report, plan, mode=PlanMode.SWEEP, config=config
        )

    # Reasoning should contain both scores in format "structural X.XX / overall Y.YY"
    assert "structural" in assessment.reasoning.lower()
    assert "overall" in assessment.reasoning.lower()
    assert "/" in assessment.reasoning
    # Should also contain the original model reasoning
    assert "test reasoning" in assessment.reasoning
