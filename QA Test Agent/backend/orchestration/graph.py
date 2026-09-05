"""LangGraph state machine wiring the full pipeline from the spec:

Discovery -> PRD Analysis -> Planning -> Plan Validation -> Test Case Generation
-> Script Generation -> Script Validation -> Execution
   -> (if any real failures) Failure Classification -> Healing -> Reporting
   -> (else) Reporting directly

Every node here does real work: Discovery drives a real Playwright crawl,
Execution runs real generated scripts in real browser contexts, Healing
re-executes real repairs. Nothing downstream of Execution ever reports a
PASS/FAIL that didn't come from an actual Playwright run (Principle 10 /
Section 39). The Healing loop is bounded by config.max_healing_attempts
(enforced inside agents/healer/agent.py) - never infinite.

Because the compiled graph is a langchain-core Runnable, once LangSmith
tracing is enabled (LANGCHAIN_TRACING_V2=true, see
observability/langsmith_tracing.py) every node run here shows up as a span
in LangSmith automatically, with the LLM calls inside each agent nested
underneath as their own spans (see services/llm_provider.py's @traceable).
"""
from __future__ import annotations

from typing import Callable

from langgraph.graph import END, StateGraph

from agents.discovery.agent import run_discovery
from agents.executor.agent import run_execution
from agents.failure_classifier.agent import run_failure_classification
from agents.healer.agent import run_healing
from agents.plan_validator.agent import run_plan_validation
from agents.planner.agent import run_planning
from agents.prd_analyzer.agent import run_prd_analysis
from agents.reporter.agent import run_reporting
from agents.script_generator.agent import run_script_generation
from agents.script_validator.agent import run_script_validation
from agents.test_generator.agent import run_test_generation
from observability.events import get_event_bus
from schemas.state import AgentEvent, PipelineStage, RunStatus, TestRunState, TestStatus
from storage.run_repository import save_state

GraphState = dict  # LangGraph works over a plain dict; we keep TestRunState under "run"


async def _emit(run_id: str, agent: str, event: str, message: str, stage: PipelineStage, **data):
    await get_event_bus().emit(
        AgentEvent(run_id=run_id, agent=agent, event=event, stage=stage, message=message, data=data)
    )


def _wrap(node_key: str, stage: PipelineStage, agent_name: str, fn: Callable):
    """Wraps an agent function with: stage transition events, error handling,
    and the never-silently-ignore-errors rule (Section 38). Also records the
    exact node key the run is in - `current_stage` is a human-facing summary
    (several nodes can share one PipelineStage, e.g. failure_classification
    and healing both show as HEALING), but resuming a failed run needs to
    know precisely which node to re-enter, hence `current_node`."""

    async def node(graph_state: GraphState) -> GraphState:
        state: TestRunState = graph_state["run"]
        state.current_stage = stage
        state.current_node = node_key
        await _emit(state.run_id, agent_name, "STARTED", f"{agent_name} started", stage)
        try:
            state = await fn(state)
            await _emit(state.run_id, agent_name, "COMPLETED", f"{agent_name} completed", stage)
        except Exception as exc:  # noqa: BLE001 - deliberately broad: must reach a controlled failure state
            state.status = RunStatus.FAILED
            state.error = f"{agent_name} failed: {exc}"
            await _emit(state.run_id, agent_name, "FAILED", str(exc), stage, error=str(exc))
        save_state(state)
        graph_state["run"] = state
        return graph_state

    return node


def _route_after(graph_state: GraphState) -> str:
    state: TestRunState = graph_state["run"]
    return "end" if state.status == RunStatus.FAILED else "continue"


def _route_after_execution(graph_state: GraphState) -> str:
    state: TestRunState = graph_state["run"]
    if state.status == RunStatus.FAILED:
        return "end"
    if any(r.status == TestStatus.FAILED for r in state.execution_results):
        return "classify"
    return "report"


# Every node this graph can be entered at, in pipeline order - used both to
# build the graph and to validate/resolve a resume request's start node.
NODE_KEYS = (
    "discovery",
    "prd_analysis",
    "planning",
    "plan_validation",
    "test_generation",
    "script_generation",
    "script_validation",
    "execution",
    "failure_classification",
    "healing",
    "reporting",
)


def build_graph(start_node: str = "discovery"):
    if start_node not in NODE_KEYS:
        raise ValueError(f"Unknown start_node: {start_node} (must be one of {NODE_KEYS})")

    graph = StateGraph(GraphState)

    graph.add_node("discovery", _wrap("discovery", PipelineStage.DISCOVERY, "DiscoveryAgent", run_discovery))
    graph.add_node(
        "prd_analysis", _wrap("prd_analysis", PipelineStage.PRD_ANALYSIS, "PRDAnalyzerAgent", run_prd_analysis)
    )
    graph.add_node("planning", _wrap("planning", PipelineStage.PLANNING, "PlannerAgent", run_planning))
    graph.add_node(
        "plan_validation",
        _wrap("plan_validation", PipelineStage.PLAN_VALIDATION, "PlanValidatorAgent", run_plan_validation),
    )
    graph.add_node(
        "test_generation",
        _wrap("test_generation", PipelineStage.TEST_GENERATION, "TestCaseGeneratorAgent", run_test_generation),
    )
    graph.add_node(
        "script_generation",
        _wrap("script_generation", PipelineStage.SCRIPT_GENERATION, "ScriptGeneratorAgent", run_script_generation),
    )
    graph.add_node(
        "script_validation",
        _wrap("script_validation", PipelineStage.SCRIPT_VALIDATION, "ScriptValidatorAgent", run_script_validation),
    )
    graph.add_node("execution", _wrap("execution", PipelineStage.EXECUTION, "ExecutorAgent", run_execution))
    graph.add_node(
        "failure_classification",
        _wrap("failure_classification", PipelineStage.HEALING, "FailureClassifierAgent", run_failure_classification),
    )
    graph.add_node("healing", _wrap("healing", PipelineStage.HEALING, "HealingAgent", run_healing))
    graph.add_node("reporting", _wrap("reporting", PipelineStage.REPORTING, "ReporterAgent", run_reporting))

    graph.set_entry_point(start_node)
    graph.add_conditional_edges("discovery", _route_after, {"continue": "prd_analysis", "end": END})
    graph.add_conditional_edges("prd_analysis", _route_after, {"continue": "planning", "end": END})
    graph.add_conditional_edges("planning", _route_after, {"continue": "plan_validation", "end": END})
    graph.add_conditional_edges("plan_validation", _route_after, {"continue": "test_generation", "end": END})
    graph.add_conditional_edges("test_generation", _route_after, {"continue": "script_generation", "end": END})
    graph.add_conditional_edges("script_generation", _route_after, {"continue": "script_validation", "end": END})
    graph.add_conditional_edges("script_validation", _route_after, {"continue": "execution", "end": END})
    graph.add_conditional_edges(
        "execution",
        _route_after_execution,
        {"classify": "failure_classification", "report": "reporting", "end": END},
    )
    graph.add_conditional_edges(
        "failure_classification", _route_after, {"continue": "healing", "end": END}
    )
    graph.add_conditional_edges("healing", _route_after, {"continue": "reporting", "end": END})
    graph.add_edge("reporting", END)

    return graph.compile()
