"""Central strongly-typed state shared by every agent in the pipeline.

All agents read from and write to this structure via the orchestrator.
Nothing here ever holds raw secret values (see security/secrets.py) -
credentials are referenced by an opaque `credential_ref` and resolved
only at execution time, inside the browser layer, never inside a prompt.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthType(str, Enum):
    NONE = "none"
    USERNAME_PASSWORD = "username_password"
    TOKEN = "token"
    OAUTH = "oauth"


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineStage(str, Enum):
    INITIALIZING = "initializing"
    DISCOVERY = "discovery"
    PRD_ANALYSIS = "prd_analysis"
    PLANNING = "planning"
    PLAN_VALIDATION = "plan_validation"
    TEST_GENERATION = "test_generation"
    SCRIPT_GENERATION = "script_generation"
    SCRIPT_VALIDATION = "script_validation"
    EXECUTION = "execution"
    HEALING = "healing"
    REPORTING = "reporting"
    DONE = "done"


class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    HEALING = "healing"
    HEALED_PASSED = "healed_passed"
    HEALING_EXHAUSTED = "healing_exhausted"
    SKIPPED = "skipped"


class FailureCategory(str, Enum):
    APPLICATION_BUG = "APPLICATION_BUG"
    TEST_SCRIPT_BUG = "TEST_SCRIPT_BUG"
    SELECTOR_FAILURE = "SELECTOR_FAILURE"
    TIMING_FAILURE = "TIMING_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    DATA_FAILURE = "DATA_FAILURE"
    ASSERTION_FAILURE = "ASSERTION_FAILURE"
    UNKNOWN = "UNKNOWN"


class RunConfig(BaseModel):
    application_url: str
    authentication_type: AuthType = AuthType.NONE
    credential_ref: Optional[str] = None  # opaque id into the secret store, never the value
    requirements_filename: Optional[str] = None
    max_healing_attempts: int = 3
    parallel_execution: bool = True
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"


class Requirement(BaseModel):
    id: str
    description: str
    priority: str = "MEDIUM"
    acceptance_criteria: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    negative_scenarios: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class PageElement(BaseModel):
    type: str
    text: Optional[str] = None
    role: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    test_id: Optional[str] = None
    aria_label: Optional[str] = None
    selector_candidates: list[str] = Field(default_factory=list)


class ApplicationPage(BaseModel):
    url: str
    title: str = ""
    page_type: str = "unknown"
    elements: list[PageElement] = Field(default_factory=list)
    forms: list[dict] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    navigation: list[str] = Field(default_factory=list)
    screenshot_path: Optional[str] = None
    dom_snapshot_path: Optional[str] = None
    console_errors: list[str] = Field(default_factory=list)
    network_failures: list[dict] = Field(default_factory=list)


class ApplicationMap(BaseModel):
    base_url: str = ""
    title: str = ""
    pages: list[ApplicationPage] = Field(default_factory=list)
    workflows: list[dict] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)


class TestStep(BaseModel):
    step_number: int
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    expected_result: Optional[str] = None


class TestCase(BaseModel):
    test_case_id: str
    requirement_id: Optional[str] = None
    title: str
    priority: str = "MEDIUM"
    preconditions: list[str] = Field(default_factory=list)
    test_data: dict[str, Any] = Field(default_factory=dict)
    steps: list[TestStep] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)
    parallel_safe: bool = True
    depends_on: list[str] = Field(default_factory=list)


class GeneratedScript(BaseModel):
    test_case_id: str
    file_path: str
    source_preview: str = ""
    valid: Optional[bool] = None
    validation_issues: list[str] = Field(default_factory=list)


class ExecutionRecord(BaseModel):
    test_case_id: str
    status: TestStatus
    duration_seconds: Optional[float] = None
    steps_log: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    video_path: Optional[str] = None
    trace_path: Optional[str] = None
    console_logs: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class FailureAnalysis(BaseModel):
    test_case_id: str
    category: FailureCategory
    confidence: float
    root_cause: str
    evidence: list[str] = Field(default_factory=list)


class HealingAttempt(BaseModel):
    test_case_id: str
    attempt_number: int
    failure_category: FailureCategory
    diagnosis: str
    proposed_change_summary: str
    repair_validated: bool
    repair_rejected_reason: Optional[str] = None
    re_execution_status: Optional[TestStatus] = None
    timestamp: str = Field(default_factory=now_iso)


class AgentEvent(BaseModel):
    run_id: str
    timestamp: str = Field(default_factory=now_iso)
    agent: str
    event: str
    stage: Optional[PipelineStage] = None
    test_case_id: Optional[str] = None
    status: str = "INFO"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class TestRunState(BaseModel):
    run_id: str
    config: RunConfig
    status: RunStatus = RunStatus.CREATED
    current_stage: PipelineStage = PipelineStage.INITIALIZING
    current_node: Optional[str] = None  # exact LangGraph node key, for precise resume

    requirements: list[Requirement] = Field(default_factory=list)
    application_map: ApplicationMap = Field(default_factory=ApplicationMap)
    test_plan: dict[str, Any] = Field(default_factory=dict)
    plan_validation: dict[str, Any] = Field(default_factory=dict)
    plan_revision_count: int = 0

    test_cases: list[TestCase] = Field(default_factory=list)
    generated_scripts: list[GeneratedScript] = Field(default_factory=list)
    script_validation: dict[str, Any] = Field(default_factory=dict)

    execution_results: list[ExecutionRecord] = Field(default_factory=list)
    failures: list[FailureAnalysis] = Field(default_factory=list)
    healing_attempts: list[HealingAttempt] = Field(default_factory=list)

    final_report_path: Optional[str] = None
    error: Optional[str] = None

    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    class Config:
        use_enum_values = False
