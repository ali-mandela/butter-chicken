"""Test Run Manager: the service layer between the API and the LangGraph
orchestrator. Owns run creation, credential handoff, and kicking off the
pipeline as a background asyncio task so /start returns immediately and
progress streams over the run's WebSocket."""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from typing import Optional

from fastapi import UploadFile

from observability.events import get_event_bus
from orchestration.graph import build_graph
from schemas.state import (
    AgentEvent,
    AuthType,
    PipelineStage,
    RunConfig,
    RunStatus,
    TestRunState,
)
from config.settings import get_settings
from security.domain_policy import validate_application_url
from security.secrets import Credential, get_secret_store
from services.llm_provider import SUPPORTED_PROVIDERS
from storage.run_repository import ensure_run_dirs, load_state, save_state

ALLOWED_PRD_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


class RunManagerError(ValueError):
    pass


def _new_run_id() -> str:
    return f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


async def create_run(
    application_url: str,
    authentication_type: str,
    max_healing_attempts: int,
    parallel_execution: bool,
    username: Optional[str],
    password: Optional[str],
    token: Optional[str],
    prd_file: Optional[UploadFile],
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> TestRunState:
    validated_url = validate_application_url(application_url)

    settings = get_settings()
    resolved_provider = llm_provider or settings.llm_provider
    resolved_model = llm_model or settings.llm_model
    if resolved_provider not in SUPPORTED_PROVIDERS:
        raise RunManagerError(f"Unknown LLM provider: {resolved_provider} (supported: {SUPPORTED_PROVIDERS})")

    auth_type = AuthType(authentication_type)
    credential_ref = None
    if auth_type == AuthType.USERNAME_PASSWORD:
        if not username or not password:
            raise RunManagerError("username and password are required for this authentication type")
        credential_ref = get_secret_store().put(
            Credential(auth_type=auth_type.value, username=username, password=password)
        )
    elif auth_type == AuthType.TOKEN:
        if not token:
            raise RunManagerError("token is required for this authentication type")
        credential_ref = get_secret_store().put(Credential(auth_type=auth_type.value, token=token))
    elif auth_type == AuthType.OAUTH:
        raise RunManagerError(
            "OAuth requires a pre-configured secure app registration; see README for setup"
        )

    if max_healing_attempts < 1 or max_healing_attempts > 10:
        raise RunManagerError("max_healing_attempts must be between 1 and 10")

    run_id = _new_run_id()
    ensure_run_dirs(run_id)

    requirements_filename = None
    if prd_file is not None:
        ext = "." + prd_file.filename.rsplit(".", 1)[-1].lower() if "." in prd_file.filename else ""
        if ext not in ALLOWED_PRD_EXTENSIONS:
            raise RunManagerError(f"Unsupported requirements file type: {ext}")
        from storage.run_repository import run_dir
        import os

        dest = os.path.join(run_dir(run_id), "requirements", prd_file.filename)
        with open(dest, "wb") as out:
            shutil.copyfileobj(prd_file.file, out)
        requirements_filename = prd_file.filename

    config = RunConfig(
        application_url=validated_url,
        authentication_type=auth_type,
        credential_ref=credential_ref,
        requirements_filename=requirements_filename,
        max_healing_attempts=max_healing_attempts,
        parallel_execution=parallel_execution,
        llm_provider=resolved_provider,
        llm_model=resolved_model,
    )
    state = TestRunState(run_id=run_id, config=config)
    save_state(state)
    return state


async def start_run(run_id: str) -> TestRunState:
    state = load_state(run_id)
    if state is None:
        raise RunManagerError(f"Run {run_id} not found")
    if state.status != RunStatus.CREATED:
        raise RunManagerError(f"Run {run_id} has already been started (status={state.status})")

    state.status = RunStatus.RUNNING
    save_state(state)

    asyncio.create_task(_execute_pipeline(run_id, start_node="discovery"))
    return state


async def resume_run(run_id: str) -> TestRunState:
    """Resumes a failed run from the exact node it failed at, instead of
    restarting the whole pipeline. Safe because every node persists the
    full TestRunState after it runs (storage.run_repository.save_state) -
    whatever the run already produced (application map, requirements, test
    plan, test cases, scripts, execution results...) is still there, so
    resuming re-enters the graph at `current_node` and everything before it
    is genuinely skipped, not silently redone. If the failure happened mid
    node (e.g. a dropped browser connection), that same node simply runs
    again - never a partial/older node, since current_node is set before
    the node's work starts, not after it finishes."""
    state = load_state(run_id)
    if state is None:
        raise RunManagerError(f"Run {run_id} not found")
    if state.status != RunStatus.FAILED:
        raise RunManagerError(f"Run {run_id} is not in a failed state (status={state.status})")

    resume_node = state.current_node or "discovery"
    state.status = RunStatus.RUNNING
    state.error = None
    save_state(state)

    await get_event_bus().emit(
        AgentEvent(
            run_id=run_id,
            agent="Orchestrator",
            event="RUN_RESUMED",
            stage=state.current_stage,
            message=f"Resuming from '{resume_node}' - earlier stages are not re-run",
        )
    )

    asyncio.create_task(_execute_pipeline(run_id, start_node=resume_node))
    return state


async def _execute_pipeline(run_id: str, start_node: str = "discovery") -> None:
    bus = get_event_bus()
    state = load_state(run_id)
    await bus.emit(
        AgentEvent(
            run_id=run_id,
            agent="Orchestrator",
            event="RUN_STARTED",
            stage=PipelineStage.INITIALIZING,
            message=(
                "Autonomous test run started"
                if start_node == "discovery"
                else f"Pipeline resumed at '{start_node}'"
            ),
        )
    )
    try:
        graph = build_graph(start_node=start_node)
        result = await graph.ainvoke({"run": state})
        final_state: TestRunState = result["run"]
        if final_state.status != RunStatus.FAILED:
            final_state.status = RunStatus.COMPLETED
            final_state.current_stage = PipelineStage.DONE
    except Exception as exc:  # noqa: BLE001 - must always reach a persisted, reported failure state
        final_state = load_state(run_id) or state
        final_state.status = RunStatus.FAILED
        final_state.error = str(exc)
        await bus.emit(
            AgentEvent(
                run_id=run_id,
                agent="Orchestrator",
                event="RUN_FAILED",
                status="ERROR",
                message=str(exc),
            )
        )

    save_state(final_state)
    await bus.emit(
        AgentEvent(
            run_id=run_id,
            agent="Orchestrator",
            event="RUN_FINISHED",
            stage=final_state.current_stage,
            status=final_state.status.value,
            message=f"Run finished with status {final_state.status.value}",
        )
    )
