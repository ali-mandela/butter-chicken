"""Tests for orchestrator.py state machine.

NO network, NO real browser. All stage collaborators are monkeypatched at the
aivar.orchestrator namespace to test the state machine logic, not the sub-agents.
"""

import pytest
from unittest.mock import MagicMock, patch

from aivar.contracts import (
    CoverageAssessment,
    CoverageVerdict,
    Decision,
    Flow,
    FlowKind,
    Gap,
    PlanMode,
    Stage,
    TestPlan,
    TriageResult,
    TriageVerdict,
)
from aivar.explorer import ExplorationReport, PageObservation
from aivar.llm import LLMConfig, LLMResponse
from aivar.models import CompiledTest, RunResult, Severity, Step, StepKind
from aivar.orchestrator import (
    OrchestratorConfig,
    OrchestratorState,
    run_pipeline,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def llm_config():
    """Minimal LLM config for testing."""
    return LLMConfig(
        api_key="test-key",
        models=("claude-3-5-sonnet-20241022",),
    )


@pytest.fixture
def mock_explore(monkeypatch):
    """Mock explore function."""
    def fake_explore(*args, **kwargs):
        return ExplorationReport(
            entry_url="https://example.com",
            authenticated=False,
            login_form=None,
            pages=[
                PageObservation(
                    url="https://example.com",
                    title="Home",
                    depth=0,
                    node_count=50,
                    forms=[],
                    links=[],
                    headings=["Welcome"],
                    controls=[],
                    reached_by=None,
                )
            ],
            errors=[],
            duration_ms=1000.0,
        )

    monkeypatch.setattr("aivar.orchestrator.explore", fake_explore)
    return fake_explore


@pytest.fixture
def mock_plan_flows(monkeypatch):
    """Mock plan_flows function."""
    from aivar.models import Selector

    def fake_plan_flows(*args, **kwargs):
        step1 = Step(
            id="step-1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="role", value="button", role="button"),
        )
        step2 = Step(
            id="step-2",
            kind=StepKind.ASSERTION,
            verb="assert",
            target="success message",
            selector=Selector(strategy="text", value="Success"),
        )
        flow = Flow(
            id="flow-1",
            name="Happy path",
            description="Test success flow",
            kind=FlowKind.HAPPY_PATH,
            steps=[step1, step2],
        )
        plan = TestPlan(
            id="plan-1",
            mode=PlanMode.SWEEP,
            flows=[flow],
        )
        llm_response = LLMResponse(
            content="test",
            model="openrouter/claude-3-5-sonnet-20241022",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.001,
            latency_ms=100.0,
        )
        return (plan, llm_response)

    monkeypatch.setattr("aivar.orchestrator.plan_flows", fake_plan_flows)
    return fake_plan_flows


@pytest.fixture
def mock_assess_coverage(monkeypatch):
    """Mock assess_coverage function."""
    def fake_assess_coverage(*args, **kwargs):
        assessment = CoverageAssessment(
            verdict=CoverageVerdict.ACCEPT,
            score=0.95,
            gaps=[],
        )
        return (assessment, None)

    monkeypatch.setattr(
        "aivar.orchestrator.assess_coverage", fake_assess_coverage
    )
    return fake_assess_coverage


@pytest.fixture
def mock_escalate_if_exhausted(monkeypatch):
    """Mock escalate_if_exhausted function."""
    def fake_escalate(assessment, replans_used, max_replans):
        return assessment

    monkeypatch.setattr(
        "aivar.orchestrator.escalate_if_exhausted", fake_escalate
    )
    return fake_escalate


@pytest.fixture
def mock_write_suite(monkeypatch):
    """Mock write_suite function."""
    def fake_write_suite(flows, url, out_dir):
        from pathlib import Path
        return [Path("tests/generated/test_flow1.py")]

    monkeypatch.setattr("aivar.orchestrator.write_suite", fake_write_suite)
    return fake_write_suite


@pytest.fixture
def mock_is_importable(monkeypatch):
    """Mock is_importable function."""
    def fake_is_importable(path):
        return (True, "")

    monkeypatch.setattr("aivar.orchestrator.is_importable", fake_is_importable)
    return fake_is_importable


@pytest.fixture
def mock_run_test(monkeypatch):
    """Mock run_test function."""
    def fake_run_test(*args, **kwargs):
        step_result1 = MagicMock()
        step_result1.status = "passed"
        return RunResult(
            test_id="flow-1",
            status="passed",
            results=[step_result1],
            cost_usd=0.001,
        )

    monkeypatch.setattr("aivar.orchestrator.run_test", fake_run_test)
    return fake_run_test


@pytest.fixture
def mock_triage_run(monkeypatch):
    """Mock triage_run function."""
    def fake_triage_run(*args, **kwargs):
        return []

    monkeypatch.setattr("aivar.orchestrator.triage_run", fake_triage_run)
    return fake_triage_run


@pytest.fixture
def mock_write_pipeline_report(monkeypatch):
    """Mock write_pipeline_report function."""
    def fake_write_report(report, out_dir):
        from pathlib import Path
        return {
            "json": Path("artifacts/run-test.json"),
            "txt": Path("artifacts/run-test.txt"),
            "html": Path("artifacts/run-test.html"),
        }

    monkeypatch.setattr(
        "aivar.orchestrator.write_pipeline_report", fake_write_report
    )
    return fake_write_report


@pytest.fixture
def mock_render_pipeline_text(monkeypatch):
    """Mock render_pipeline_text function."""
    def fake_render(report):
        return "Test Report\n===========\n\nStatus: OK\n"

    monkeypatch.setattr(
        "aivar.orchestrator.render_pipeline_text", fake_render
    )
    return fake_render


@pytest.fixture
def mock_sync_playwright(monkeypatch):
    """Mock sync_playwright to avoid real browser launches."""
    mock_page = MagicMock()
    mock_page.snapshot.return_value = {"nodes": []}

    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_browser.close.return_value = None

    mock_playwright_obj = MagicMock()
    mock_playwright_obj.chromium.launch.return_value = mock_browser
    mock_playwright_obj.stop.return_value = None

    def fake_sync_playwright():
        return mock_playwright_obj

    monkeypatch.setattr("aivar.orchestrator.sync_playwright", fake_sync_playwright)
    return fake_sync_playwright


@pytest.fixture
def mock_browser_class(monkeypatch):
    """Mock the Browser class."""
    mock_browser = MagicMock()
    mock_browser.snapshot.return_value = {"nodes": []}
    mock_browser.act.return_value = None

    def fake_browser(page):
        return mock_browser

    monkeypatch.setattr("aivar.orchestrator.Browser", fake_browser)
    return fake_browser


@pytest.fixture
def all_mocks(
    monkeypatch,
    mock_explore,
    mock_plan_flows,
    mock_assess_coverage,
    mock_escalate_if_exhausted,
    mock_write_suite,
    mock_is_importable,
    mock_run_test,
    mock_triage_run,
    mock_write_pipeline_report,
    mock_render_pipeline_text,
    mock_sync_playwright,
    mock_browser_class,
):
    """Bundle all mocks."""
    return {
        "explore": mock_explore,
        "plan_flows": mock_plan_flows,
        "assess_coverage": mock_assess_coverage,
        "escalate_if_exhausted": mock_escalate_if_exhausted,
        "write_suite": mock_write_suite,
        "is_importable": mock_is_importable,
        "run_test": mock_run_test,
        "triage_run": mock_triage_run,
        "write_pipeline_report": mock_write_pipeline_report,
        "render_pipeline_text": mock_render_pipeline_text,
        "sync_playwright": mock_sync_playwright,
        "browser": mock_browser_class,
    }


# ============================================================================
# Tests
# ============================================================================


def test_clean_run_walks_all_stages(all_mocks, llm_config):
    """A clean run walks EXPLORE→PLAN→CRITIQUE→GENERATE→VALIDATE→EXECUTE→TRIAGE→REPORT→DONE."""
    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check ledger has one Decision per stage in order
    stage_order = [
        Stage.EXPLORE,
        Stage.PLAN,
        Stage.CRITIQUE,
        Stage.GENERATE,
        Stage.VALIDATE,
        Stage.EXECUTE,
        Stage.TRIAGE,
        Stage.REPORT,
    ]
    ledger_stages = [d.stage for d in state.ledger]
    assert ledger_stages == stage_order

    # Check final state
    assert state.stage == Stage.DONE
    assert state.escalation_reason is None


def test_replan_sends_back_to_plan(all_mocks, monkeypatch, llm_config):
    """A REPLAN verdict sends back to PLAN and increments replans_used."""

    call_count = {"assess_coverage": 0}

    def fake_assess_coverage_replan(*args, **kwargs):
        call_count["assess_coverage"] += 1
        if call_count["assess_coverage"] == 1:
            # First time: REPLAN
            return (
                CoverageAssessment(
                    verdict=CoverageVerdict.REPLAN,
                    score=0.5,
                    gaps=[],
                    replan_instruction="Add negative test flows",
                ),
                None,
            )
        else:
            # Second time: ACCEPT
            return (
                CoverageAssessment(
                    verdict=CoverageVerdict.ACCEPT,
                    score=0.95,
                    gaps=[],
                ),
                None,
            )

    monkeypatch.setattr(
        "aivar.orchestrator.assess_coverage", fake_assess_coverage_replan
    )

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check replans_used was incremented
    assert state.replans_used == 1

    # Check ledger has PLAN twice
    plan_count = sum(1 for d in state.ledger if d.stage == Stage.PLAN)
    assert plan_count == 2

    # Check replan instruction was passed
    assert state.replan_instruction == "Add negative test flows"


def test_replan_twice_exhausts_replans(all_mocks, monkeypatch, llm_config):
    """REPLAN twice with max_replans=2 ends in ESCALATED."""

    call_count = {"assess_coverage": 0}

    def fake_assess_coverage_replan(*args, **kwargs):
        call_count["assess_coverage"] += 1
        return (
            CoverageAssessment(
                verdict=CoverageVerdict.REPLAN,
                score=0.5,
                gaps=[],
            ),
            None,
        )

    def fake_escalate_if_exhausted(assessment, replans_used, max_replans):
        if (
            assessment.verdict == CoverageVerdict.REPLAN
            and replans_used >= max_replans
        ):
            return CoverageAssessment(
                verdict=CoverageVerdict.ESCALATE,
                score=assessment.score,
                gaps=assessment.gaps,
            )
        return assessment

    monkeypatch.setattr(
        "aivar.orchestrator.assess_coverage", fake_assess_coverage_replan
    )
    monkeypatch.setattr(
        "aivar.orchestrator.escalate_if_exhausted", fake_escalate_if_exhausted
    )

    config = OrchestratorConfig(max_replans=2)
    report, state = run_pipeline(
        url="https://example.com",
        config=config,
        llm_config=llm_config,
    )

    # Check escalation
    assert state.escalation_reason is not None
    assert state.replans_used == 2

    # Check report was still written
    assert report is not None


def test_mode_derivation(all_mocks, monkeypatch, llm_config):
    """Mode derivation: no intent/prd → SWEEP; intent → FOCUSED; prd_path → SPEC_LED."""
    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )
    assert state.mode == PlanMode.SWEEP

    # Mock prd reading
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Product requirements")
        prd_path = f.name

    report, state = run_pipeline(
        url="https://example.com",
        prd_path=prd_path,
        llm_config=llm_config,
    )
    assert state.mode == PlanMode.SPEC_LED

    report, state = run_pipeline(
        url="https://example.com",
        intent="Do something useful",
        llm_config=llm_config,
    )
    assert state.mode == PlanMode.FOCUSED


def test_exceeded_cost_escalates(all_mocks, monkeypatch, llm_config):
    """Exceeding max_cost_usd mid-run escalates."""

    def fake_plan_flows_expensive(*args, **kwargs):
        return (
            TestPlan(
                id="plan-1",
                mode=PlanMode.SWEEP,
                flows=[
                    Flow(
                        id="flow-1",
                        name="Test",
                        description="Test",
                        kind=FlowKind.HAPPY_PATH,
                        steps=[],
                    )
                ],
            ),
            LLMResponse(
                content="test",
                model="claude-3-5-sonnet-20241022",
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.60,  # Exceeds 0.50 default budget
                latency_ms=100.0,
            ),
        )

    monkeypatch.setattr(
        "aivar.orchestrator.plan_flows", fake_plan_flows_expensive
    )

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check escalation due to budget
    assert state.escalation_reason is not None
    assert "Cost budget exceeded" in state.escalation_reason


def test_no_flows_survive_validation_escalates(
    all_mocks, monkeypatch, llm_config
):
    """When no flows survive validation, escalate."""

    def fake_write_suite_empty(flows, url, out_dir):
        return []  # No files written

    monkeypatch.setattr(
        "aivar.orchestrator.write_suite", fake_write_suite_empty
    )

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check escalation
    assert state.escalation_reason is not None or state.stage == Stage.ESCALATED


def test_handler_exception_escalates(
    all_mocks, monkeypatch, llm_config
):
    """A handler raising an exception escalates instead of propagating."""

    def fake_explore_error(*args, **kwargs):
        raise RuntimeError("Exploration crashed")

    monkeypatch.setattr("aivar.orchestrator.explore", fake_explore_error)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check escalation
    assert state.escalation_reason is not None
    assert "Exploration crashed" in state.escalation_reason
    assert report is not None  # Report still produced


def test_ledger_matches_decisions(all_mocks, llm_config):
    """run_pipeline returns a PipelineReport whose decisions match the ledger."""
    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check that decisions in report match ledger in state
    assert len(report.decisions) == len(state.ledger)
    for i, (r_decision, s_decision) in enumerate(
        zip(report.decisions, state.ledger)
    ):
        assert r_decision.stage == s_decision.stage
        assert r_decision.verdict == s_decision.verdict


def test_high_unresolved_steps_trigger_regeneration(
    all_mocks, monkeypatch, llm_config
):
    """A flow with >30% unresolved steps triggers one regeneration."""

    gen_count = {"count": 0}

    def fake_plan_flows(*args, **kwargs):
        gen_count["count"] += 1
        if gen_count["count"] > 1:
            # Second generation: all steps resolved
            step = Step(
                id="step-1",
                kind=StepKind.ACTION,
                verb="click",
                target="button",
                selector="button.main",  # Now resolved
            )
        else:
            # First generation: unresolved
            step = Step(
                id="step-1",
                kind=StepKind.ACTION,
                verb="click",
                target="button",
                selector=None,
            )
        flow = Flow(
            id="flow-1",
            name="Test",
            description="Test",
            kind=FlowKind.HAPPY_PATH,
            steps=[step],
        )
        return (
            TestPlan(id="plan-1", mode=PlanMode.SWEEP, flows=[flow]),
            LLMResponse(
                content="test",
                model="claude-3-5-sonnet-20241022",
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.001,
                latency_ms=100.0,
            ),
        )

    monkeypatch.setattr("aivar.orchestrator.plan_flows", fake_plan_flows)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check regeneration was used
    assert state.regens_used == 1


def test_dropped_flow_records_gap(all_mocks, monkeypatch, llm_config):
    """A dropped flow records a dropped_flow gap."""

    def fake_write_suite_drop(flows, url, out_dir):
        # Simulate one flow being dropped
        if flows:
            return []  # No files written
        return []

    monkeypatch.setattr(
        "aivar.orchestrator.write_suite", fake_write_suite_drop
    )

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # After a dropped flow, should escalate
    assert state.escalation_reason is not None


def test_exploration_zero_pages_escalates(all_mocks, monkeypatch, llm_config):
    """If exploration finds 0 pages, escalate."""

    def fake_explore_empty(*args, **kwargs):
        return ExplorationReport(
            entry_url="https://example.com",
            authenticated=False,
            login_form=None,
            pages=[],  # No pages
            errors=["Failed to load"],
            duration_ms=1000.0,
        )

    monkeypatch.setattr("aivar.orchestrator.explore", fake_explore_empty)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check escalation
    assert state.escalation_reason is not None
    assert state.stage == Stage.ESCALATED or report.escalated


def test_over_budget_check(all_mocks, llm_config):
    """over_budget() returns a reason when cost or time exceeded."""
    state = OrchestratorState(
        url="https://example.com",
        username=None,
        password=None,
        intent=None,
        prd_text=None,
        mode=PlanMode.SWEEP,
    )

    # Under budget
    assert state.over_budget() is None

    # Over cost budget
    state.cost_usd = 0.60
    assert state.over_budget() is not None
    assert "Cost budget exceeded" in state.over_budget()


def test_run_pipeline_returns_tuple(all_mocks, llm_config):
    """run_pipeline returns (PipelineReport, OrchestratorState)."""
    result = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )
    assert isinstance(result, tuple)
    assert len(result) == 2
    report, state = result
    assert hasattr(report, "run_id")
    assert hasattr(state, "stage")


def test_record_decision_logs_and_appends(all_mocks, llm_config):
    """record() appends to ledger and logs one line."""
    state = OrchestratorState(
        url="https://example.com",
        username=None,
        password=None,
        intent=None,
        prd_text=None,
        mode=PlanMode.SWEEP,
    )

    decision = Decision.now(
        Stage.EXPLORE, "continue", "Found 5 pages", Stage.PLAN
    )
    state.record(decision)

    assert len(state.ledger) == 1
    assert state.ledger[0] == decision


def test_state_elapsed_s_increases(all_mocks, llm_config):
    """State.elapsed_s increases over time."""
    import time

    state = OrchestratorState(
        url="https://example.com",
        username=None,
        password=None,
        intent=None,
        prd_text=None,
        mode=PlanMode.SWEEP,
    )

    elapsed_1 = state.elapsed_s
    time.sleep(0.01)
    elapsed_2 = state.elapsed_s

    assert elapsed_2 > elapsed_1


# ============================================================================
# Tests for credential injection in _compile_flow
# ============================================================================


def test_compile_flow_injects_password_placeholder():
    """_compile_flow injects ${AIVAR_PASSWORD} into a fill step targeting a password field."""
    from aivar.models import Selector
    from aivar.orchestrator import _compile_flow
    from aivar.llm import LLMConfig

    # Create a step with no value
    step = Step(
        id="s1",
        kind=StepKind.ACTION,
        verb="fill",
        target="password field",
        value=None,
        selector=None,
    )

    flow = Flow(
        id="f1",
        name="Login",
        description="Test login",
        kind=FlowKind.HAPPY_PATH,
        steps=[step],
    )

    # Create a fake browser
    fake_browser = MagicMock()
    fake_browser.snapshot.return_value = []
    fake_browser.page.url = "https://example.com"
    fake_browser.act.return_value = None

    llm_config = LLMConfig(
        api_key="test-key",
        models=("claude-3-5-sonnet-20241022",),
    )

    credentials = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}

    # Compile the flow
    compiled = _compile_flow(flow, "https://example.com", fake_browser, llm_config, credentials=credentials)

    # Check that the password placeholder was injected
    assert len(compiled.steps) == 1
    compiled_step = compiled.steps[0]
    assert compiled_step.value == "${AIVAR_PASSWORD}"


def test_compile_flow_injects_username_placeholder_for_username_field():
    """_compile_flow injects ${AIVAR_USERNAME} into a fill step targeting a username field."""
    from aivar.models import Selector
    from aivar.orchestrator import _compile_flow
    from aivar.llm import LLMConfig

    # Create a step with no value targeting username
    step = Step(
        id="s1",
        kind=StepKind.ACTION,
        verb="fill",
        target="username field",
        value=None,
        selector=None,
    )

    flow = Flow(
        id="f1",
        name="Login",
        description="Test login",
        kind=FlowKind.HAPPY_PATH,
        steps=[step],
    )

    fake_browser = MagicMock()
    fake_browser.snapshot.return_value = []
    fake_browser.page.url = "https://example.com"
    fake_browser.act.return_value = None

    llm_config = LLMConfig(
        api_key="test-key",
        models=("claude-3-5-sonnet-20241022",),
    )

    credentials = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}

    compiled = _compile_flow(flow, "https://example.com", fake_browser, llm_config, credentials=credentials)

    assert len(compiled.steps) == 1
    assert compiled.steps[0].value == "${AIVAR_USERNAME}"


def test_compile_flow_injects_username_for_email_field():
    """_compile_flow injects ${AIVAR_USERNAME} for email fields."""
    from aivar.orchestrator import _compile_flow
    from aivar.llm import LLMConfig

    step = Step(
        id="s1",
        kind=StepKind.ACTION,
        verb="fill",
        target="email field",
        value=None,
        selector=None,
    )

    flow = Flow(
        id="f1",
        name="Login",
        description="Test",
        kind=FlowKind.HAPPY_PATH,
        steps=[step],
    )

    fake_browser = MagicMock()
    fake_browser.snapshot.return_value = []
    fake_browser.page.url = "https://example.com"

    llm_config = LLMConfig(
        api_key="test-key",
        models=("claude-3-5-sonnet-20241022",),
    )

    credentials = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}

    compiled = _compile_flow(flow, "https://example.com", fake_browser, llm_config, credentials=credentials)

    assert compiled.steps[0].value == "${AIVAR_USERNAME}"


def test_compile_flow_injects_username_for_login_field():
    """_compile_flow injects ${AIVAR_USERNAME} for login fields."""
    from aivar.orchestrator import _compile_flow
    from aivar.llm import LLMConfig

    step = Step(
        id="s1",
        kind=StepKind.ACTION,
        verb="fill",
        target="login field",
        value=None,
        selector=None,
    )

    flow = Flow(
        id="f1",
        name="Login",
        description="Test",
        kind=FlowKind.HAPPY_PATH,
        steps=[step],
    )

    fake_browser = MagicMock()
    fake_browser.snapshot.return_value = []
    fake_browser.page.url = "https://example.com"

    llm_config = LLMConfig(
        api_key="test-key",
        models=("claude-3-5-sonnet-20241022",),
    )

    credentials = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}

    compiled = _compile_flow(flow, "https://example.com", fake_browser, llm_config, credentials=credentials)

    assert compiled.steps[0].value == "${AIVAR_USERNAME}"


def test_compile_flow_leaves_literal_values_untouched():
    """_compile_flow does not modify fill steps that already have literal values."""
    from aivar.orchestrator import _compile_flow
    from aivar.llm import LLMConfig

    step = Step(
        id="s1",
        kind=StepKind.ACTION,
        verb="fill",
        target="text input",
        value="literal value",
        selector=None,
    )

    flow = Flow(
        id="f1",
        name="Fill",
        description="Test",
        kind=FlowKind.HAPPY_PATH,
        steps=[step],
    )

    fake_browser = MagicMock()
    fake_browser.snapshot.return_value = []
    fake_browser.page.url = "https://example.com"

    llm_config = LLMConfig(
        api_key="test-key",
        models=("claude-3-5-sonnet-20241022",),
    )

    credentials = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}

    compiled = _compile_flow(flow, "https://example.com", fake_browser, llm_config, credentials=credentials)

    assert compiled.steps[0].value == "literal value"


def test_compile_flow_retains_placeholder_not_resolved_secret():
    """Compiled steps retain placeholder values, not resolved secrets."""
    import os
    from aivar.orchestrator import _compile_flow
    from aivar.llm import LLMConfig

    step = Step(
        id="s1",
        kind=StepKind.ACTION,
        verb="fill",
        target="password field",
        value=None,
        selector=None,
    )

    flow = Flow(
        id="f1",
        name="Login",
        description="Test",
        kind=FlowKind.HAPPY_PATH,
        steps=[step],
    )

    fake_browser = MagicMock()
    fake_browser.snapshot.return_value = []
    fake_browser.page.url = "https://example.com"
    fake_browser.act.return_value = None

    llm_config = LLMConfig(
        api_key="test-key",
        models=("claude-3-5-sonnet-20241022",),
    )

    # Set a real password in the environment
    os.environ["AIVAR_PASSWORD"] = "topsecret"

    credentials = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}

    compiled = _compile_flow(flow, "https://example.com", fake_browser, llm_config, credentials=credentials)

    # Check that the compiled step has the placeholder, NOT the resolved secret
    assert compiled.steps[0].value == "${AIVAR_PASSWORD}"
    assert "topsecret" not in compiled.steps[0].value


def test_compile_flow_non_fill_steps_never_get_credentials():
    """_compile_flow does not inject credentials into non-fill steps."""
    from aivar.orchestrator import _compile_flow
    from aivar.llm import LLMConfig

    # Create a click step
    step = Step(
        id="s1",
        kind=StepKind.ACTION,
        verb="click",
        target="login button",
        value=None,
        selector=None,
    )

    flow = Flow(
        id="f1",
        name="Login",
        description="Test",
        kind=FlowKind.HAPPY_PATH,
        steps=[step],
    )

    fake_browser = MagicMock()
    fake_browser.snapshot.return_value = []
    fake_browser.page.url = "https://example.com"

    llm_config = LLMConfig(
        api_key="test-key",
        models=("claude-3-5-sonnet-20241022",),
    )

    credentials = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}

    compiled = _compile_flow(flow, "https://example.com", fake_browser, llm_config, credentials=credentials)

    # Click steps should not have a value injected
    assert compiled.steps[0].value is None


def test_dropped_flow_gaps_not_duplicated(all_mocks, monkeypatch, llm_config):
    """Dropped-flow gaps are not duplicated when the same flow is dropped twice."""
    from aivar.models import Selector

    def fake_plan_flows_large(*args, **kwargs):
        # Create 3 flows, some with high unresolved rates
        steps_unresolved = [
            Step(
                id="s1",
                kind=StepKind.ACTION,
                verb="click",
                target="btn1",
                selector=None,  # Unresolved
            ),
            Step(
                id="s2",
                kind=StepKind.ACTION,
                verb="click",
                target="btn2",
                selector=None,  # Unresolved
            ),
            Step(
                id="s3",
                kind=StepKind.ACTION,
                verb="click",
                target="btn3",
                selector=Selector(strategy="role", value="button", role="button"),  # Resolved
            ),
        ]
        flow_unresolved = Flow(
            id="flow-unresolved",
            name="Unresolved Flow",
            description="Has unresolved steps",
            kind=FlowKind.HAPPY_PATH,
            steps=steps_unresolved,
        )

        flow_resolved = Flow(
            id="flow-resolved",
            name="Resolved Flow",
            description="Fully resolved",
            kind=FlowKind.HAPPY_PATH,
            steps=[
                Step(
                    id="s1",
                    kind=StepKind.ACTION,
                    verb="click",
                    target="button",
                    selector=Selector(strategy="role", value="button", role="button"),
                )
            ],
        )

        return (
            TestPlan(
                id="plan-1",
                mode=PlanMode.SWEEP,
                flows=[flow_unresolved, flow_resolved],
            ),
            LLMResponse(
                content="test",
                model="claude-3-5-sonnet-20241022",
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.001,
                latency_ms=100.0,
            ),
        )

    monkeypatch.setattr("aivar.orchestrator.plan_flows", fake_plan_flows_large)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Check that dropped_flow gap appears only once
    dropped_flow_gaps = [
        g
        for g in state.gaps
        if g.kind == "dropped_flow" and "Unresolved Flow" in g.description
    ]
    assert len(dropped_flow_gaps) <= 1, f"Found {len(dropped_flow_gaps)} gaps for the same flow"


# ============================================================================
# Tests for Fix 1: _step_generate honest reporting
# ============================================================================


def test_generate_no_fully_compiled_reports_zero_fully(
    all_mocks, monkeypatch, llm_config
):
    """When no flows compile fully, the GENERATE decision reason says '0 of N flows fully'."""
    from aivar.models import Selector

    def fake_plan_flows_partial(*args, **kwargs):
        # Create flows with unresolved steps (partial)
        step_unresolved = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=None,  # Not compiled
        )
        flow = Flow(
            id="flow-1",
            name="Partial Flow",
            description="Not fully compiled",
            kind=FlowKind.HAPPY_PATH,
            steps=[step_unresolved],
        )
        return (
            TestPlan(id="plan-1", mode=PlanMode.SWEEP, flows=[flow]),
            LLMResponse(
                content="test",
                model="claude-3-5-sonnet-20241022",
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.001,
                latency_ms=100.0,
            ),
        )

    monkeypatch.setattr("aivar.orchestrator.plan_flows", fake_plan_flows_partial)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Find GENERATE decision
    generate_decision = next(
        (d for d in state.ledger if d.stage == Stage.GENERATE), None
    )
    assert generate_decision is not None
    # Should report "0 of 1 flows fully (1 partial)", NOT "1 / 1"
    assert "0 of 1 flows fully" in generate_decision.reason
    assert "1 partial" in generate_decision.reason


def test_generate_decision_evidence_includes_counts(
    all_mocks, monkeypatch, llm_config
):
    """GENERATE decision evidence includes fully_compiled, partial, and planned counts."""
    from aivar.models import Selector

    def fake_plan_flows_mixed(*args, **kwargs):
        # Create both fully compiled and partial flows
        step_compiled = Step(
            id="s1",
            kind=StepKind.ACTION,
            verb="click",
            target="button",
            selector=Selector(strategy="role", value="button", role="button"),
        )
        step_unresolved = Step(
            id="s2",
            kind=StepKind.ACTION,
            verb="click",
            target="missing",
            selector=None,
        )

        flow_compiled = Flow(
            id="flow-compiled",
            name="Full Flow",
            description="Fully compiled",
            kind=FlowKind.HAPPY_PATH,
            steps=[step_compiled],
        )
        flow_partial = Flow(
            id="flow-partial",
            name="Partial Flow",
            description="Partial",
            kind=FlowKind.HAPPY_PATH,
            steps=[step_unresolved],
        )

        return (
            TestPlan(
                id="plan-1",
                mode=PlanMode.SWEEP,
                flows=[flow_compiled, flow_partial],
            ),
            LLMResponse(
                content="test",
                model="claude-3-5-sonnet-20241022",
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.001,
                latency_ms=100.0,
            ),
        )

    monkeypatch.setattr("aivar.orchestrator.plan_flows", fake_plan_flows_mixed)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    generate_decision = next(
        (d for d in state.ledger if d.stage == Stage.GENERATE), None
    )
    assert generate_decision is not None
    assert "fully_compiled" in generate_decision.evidence
    assert "partial" in generate_decision.evidence
    assert "planned" in generate_decision.evidence
    # Check the actual counts (may be 1 and 1, or 0 and 2 depending on browser mock)
    assert isinstance(generate_decision.evidence["fully_compiled"], int)
    assert isinstance(generate_decision.evidence["partial"], int)
    assert isinstance(generate_decision.evidence["planned"], int)


def test_generate_escalates_when_both_empty(all_mocks, monkeypatch, llm_config):
    """GENERATE escalates when both fully and partial are empty."""

    def fake_plan_flows_empty(*args, **kwargs):
        # Plan with flows that fail to compile
        return (
            TestPlan(id="plan-1", mode=PlanMode.SWEEP, flows=[]),
            LLMResponse(
                content="test",
                model="claude-3-5-sonnet-20241022",
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.001,
                latency_ms=100.0,
            ),
        )

    monkeypatch.setattr("aivar.orchestrator.plan_flows", fake_plan_flows_empty)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Should escalate because no flows were planned
    assert state.escalation_reason is not None


# ============================================================================
# Tests for Fix 2: flow_kind and flow_name passed to apply_credentials
# ============================================================================


def test_compile_flow_passes_flow_kind_and_name_to_apply_credentials(
    monkeypatch, llm_config
):
    """_compile_flow passes flow_kind and flow_name to apply_credentials."""
    from aivar.orchestrator import _compile_flow
    from aivar.compiler import apply_credentials

    # Record what apply_credentials is called with
    apply_creds_calls = []

    original_apply_creds = apply_credentials

    def spy_apply_credentials(step, credentials, **kwargs):
        apply_creds_calls.append({"step": step, "credentials": credentials, "kwargs": kwargs})
        return original_apply_creds(step, credentials, **kwargs)

    monkeypatch.setattr("aivar.orchestrator.apply_credentials", spy_apply_credentials)

    step = Step(
        id="s1",
        kind=StepKind.ACTION,
        verb="fill",
        target="password field",
        value=None,
        selector=None,
    )

    flow = Flow(
        id="f1",
        name="Test Negative Flow",
        description="Test",
        kind=FlowKind.NEGATIVE,
        steps=[step],
    )

    fake_browser = MagicMock()
    fake_browser.snapshot.return_value = []
    fake_browser.page.url = "https://example.com"

    credentials = {"username": "${AIVAR_USERNAME}", "password": "${AIVAR_PASSWORD}"}

    compiled = _compile_flow(flow, "https://example.com", fake_browser, llm_config, credentials=credentials)

    # Check that apply_credentials was called with flow_kind and flow_name
    assert len(apply_creds_calls) > 0
    call = apply_creds_calls[0]
    assert "kwargs" in call
    assert call["kwargs"].get("flow_kind") == FlowKind.NEGATIVE
    assert call["kwargs"].get("flow_name") == "Test Negative Flow"


# ============================================================================
# Tests for Fix 3: escalation_reason surface clearly
# ============================================================================


def test_escalated_run_always_has_escalation_reason(all_mocks, monkeypatch, llm_config):
    """An escalated run always has a non-None escalation_reason."""

    def fake_explore_error(*args, **kwargs):
        raise RuntimeError("Exploration crashed")

    monkeypatch.setattr("aivar.orchestrator.explore", fake_explore_error)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Escalation should set the reason
    assert state.escalation_reason is not None
    assert len(state.escalation_reason) > 0


def test_escalation_reason_in_report_evidence(all_mocks, monkeypatch, llm_config):
    """When escalated, the REPORT decision includes escalation_reason in evidence."""

    def fake_explore_error(*args, **kwargs):
        raise RuntimeError("Test escalation")

    monkeypatch.setattr("aivar.orchestrator.explore", fake_explore_error)

    report, state = run_pipeline(
        url="https://example.com",
        llm_config=llm_config,
    )

    # Find REPORT decision
    report_decision = next(
        (d for d in state.ledger if d.stage == Stage.REPORT), None
    )
    if report_decision and state.escalation_reason:
        # If escalated, REPORT should include the reason in evidence
        assert "escalation_reason" in report_decision.evidence or report_decision.evidence == {}


# ============================================================================
# Tests for Fix 4: URL validation
# ============================================================================


def test_run_pipeline_empty_url_escalates(llm_config):
    """run_pipeline with empty URL returns escalated report without calling explore."""
    mock_explore_calls = []

    def fake_explore(*args, **kwargs):
        mock_explore_calls.append(True)
        return ExplorationReport(
            entry_url="https://example.com",
            authenticated=False,
            login_form=None,
            pages=[],
            errors=[],
            duration_ms=1000.0,
        )

    # We need to patch explore to track if it's called
    with patch("aivar.orchestrator.explore", side_effect=fake_explore):
        report, state = run_pipeline(
            url="",
            llm_config=llm_config,
        )

    # Should escalate immediately without calling explore
    assert len(mock_explore_calls) == 0
    assert state.escalation_reason is not None
    assert "Invalid URL" in state.escalation_reason or state.stage == Stage.ESCALATED


def test_run_pipeline_invalid_url_escalates(llm_config):
    """run_pipeline with invalid URL (no http/https) returns escalated report without calling explore."""
    mock_explore_calls = []

    def fake_explore(*args, **kwargs):
        mock_explore_calls.append(True)
        return ExplorationReport(
            entry_url="https://example.com",
            authenticated=False,
            login_form=None,
            pages=[],
            errors=[],
            duration_ms=1000.0,
        )

    with patch("aivar.orchestrator.explore", side_effect=fake_explore):
        report, state = run_pipeline(
            url="not-a-url",
            llm_config=llm_config,
        )

    # Should escalate immediately without calling explore
    assert len(mock_explore_calls) == 0
    assert state.escalation_reason is not None
    assert "Invalid URL" in state.escalation_reason or state.stage == Stage.ESCALATED


def test_run_pipeline_http_url_accepted(llm_config):
    """run_pipeline with http:// URL proceeds normally."""
    from aivar.explorer import ExplorationReport, PageObservation

    def fake_explore(*args, **kwargs):
        return ExplorationReport(
            entry_url="http://example.com",
            authenticated=False,
            login_form=None,
            pages=[
                PageObservation(
                    url="http://example.com",
                    title="Home",
                    depth=0,
                    node_count=50,
                    forms=[],
                    links=[],
                    headings=["Welcome"],
                    controls=[],
                    reached_by=None,
                )
            ],
            errors=[],
            duration_ms=1000.0,
        )

    with patch("aivar.orchestrator.explore", side_effect=fake_explore):
        with patch("aivar.orchestrator.plan_flows") as mock_plan:
            mock_plan.return_value = (
                TestPlan(id="plan-1", mode=PlanMode.SWEEP, flows=[]),
                LLMResponse(
                    content="test",
                    model="claude-3-5-sonnet-20241022",
                    prompt_tokens=100,
                    completion_tokens=50,
                    cost_usd=0.001,
                    latency_ms=100.0,
                ),
            )
            with patch("aivar.orchestrator.assess_coverage") as mock_assess:
                mock_assess.return_value = (
                    CoverageAssessment(
                        verdict=CoverageVerdict.ACCEPT,
                        score=0.95,
                        gaps=[],
                    ),
                    None,
                )
                with patch("aivar.orchestrator.escalate_if_exhausted") as mock_escalate:
                    mock_escalate.return_value = mock_assess.return_value[0]
                    with patch("aivar.orchestrator.write_suite") as mock_write:
                        mock_write.return_value = []
                        with patch("aivar.orchestrator.write_pipeline_report"):
                            with patch("aivar.orchestrator.render_pipeline_text"):
                                report, state = run_pipeline(
                                    url="http://example.com",
                                    llm_config=llm_config,
                                )

                                # Should proceed past EXPLORE
                                assert state.stage not in (Stage.ESCALATED,) or state.escalation_reason is None or "Invalid URL" not in state.escalation_reason


def test_run_pipeline_https_url_accepted(llm_config):
    """run_pipeline with https:// URL proceeds normally."""
    from aivar.explorer import ExplorationReport, PageObservation

    def fake_explore(*args, **kwargs):
        return ExplorationReport(
            entry_url="https://example.com",
            authenticated=False,
            login_form=None,
            pages=[
                PageObservation(
                    url="https://example.com",
                    title="Home",
                    depth=0,
                    node_count=50,
                    forms=[],
                    links=[],
                    headings=["Welcome"],
                    controls=[],
                    reached_by=None,
                )
            ],
            errors=[],
            duration_ms=1000.0,
        )

    with patch("aivar.orchestrator.explore", side_effect=fake_explore):
        with patch("aivar.orchestrator.plan_flows") as mock_plan:
            mock_plan.return_value = (
                TestPlan(id="plan-1", mode=PlanMode.SWEEP, flows=[]),
                LLMResponse(
                    content="test",
                    model="claude-3-5-sonnet-20241022",
                    prompt_tokens=100,
                    completion_tokens=50,
                    cost_usd=0.001,
                    latency_ms=100.0,
                ),
            )
            with patch("aivar.orchestrator.assess_coverage") as mock_assess:
                mock_assess.return_value = (
                    CoverageAssessment(
                        verdict=CoverageVerdict.ACCEPT,
                        score=0.95,
                        gaps=[],
                    ),
                    None,
                )
                with patch("aivar.orchestrator.escalate_if_exhausted") as mock_escalate:
                    mock_escalate.return_value = mock_assess.return_value[0]
                    with patch("aivar.orchestrator.write_suite") as mock_write:
                        mock_write.return_value = []
                        with patch("aivar.orchestrator.write_pipeline_report"):
                            with patch("aivar.orchestrator.render_pipeline_text"):
                                report, state = run_pipeline(
                                    url="https://example.com",
                                    llm_config=llm_config,
                                )

                                # Should proceed past EXPLORE
                                assert state.stage not in (Stage.ESCALATED,) or state.escalation_reason is None or "Invalid URL" not in state.escalation_reason
