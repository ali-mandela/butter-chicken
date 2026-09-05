from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from api.schemas_api import CreateRunResponse, RunStatusResponse
from observability.events import get_event_bus
from services.run_manager import RunManagerError, create_run, resume_run, start_run
from storage.run_repository import list_runs, load_state, run_dir

router = APIRouter(prefix="/api/test-runs", tags=["test-runs"])


def _to_status_response(state) -> RunStatusResponse:
    return RunStatusResponse(
        run_id=state.run_id,
        application_url=state.config.application_url,
        llm_provider=state.config.llm_provider,
        llm_model=state.config.llm_model,
        status=state.status.value,
        current_stage=state.current_stage.value,
        current_node=state.current_node,
        plan_revision_count=state.plan_revision_count,
        total_test_cases=len(state.test_cases),
        total_scripts=len(state.generated_scripts),
        error=state.error,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


@router.post("", response_model=CreateRunResponse)
async def create_test_run(
    application_url: str = Form(...),
    authentication_type: str = Form("none"),
    username: str | None = Form(None),
    password: str | None = Form(None),
    token: str | None = Form(None),
    max_healing_attempts: int = Form(3),
    parallel_execution: bool = Form(True),
    llm_provider: str | None = Form(None),
    llm_model: str | None = Form(None),
    requirements_file: UploadFile | None = File(None),
):
    try:
        state = await create_run(
            application_url=application_url,
            authentication_type=authentication_type,
            max_healing_attempts=max_healing_attempts,
            parallel_execution=parallel_execution,
            username=username,
            password=password,
            token=token,
            prd_file=requirements_file,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
    except RunManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CreateRunResponse(run_id=state.run_id, status=state.status.value)


@router.post("/{run_id}/start", response_model=RunStatusResponse)
async def start_test_run(run_id: str):
    try:
        state = await start_run(run_id)
    except RunManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_status_response(state)


@router.post("/{run_id}/resume", response_model=RunStatusResponse)
async def resume_test_run(run_id: str):
    """Resumes a FAILED run from the exact node it failed at - a dropped
    Playwright driver connection, a transient LLM error, etc. don't require
    starting the whole pipeline (and re-paying for every LLM call) over."""
    try:
        state = await resume_run(run_id)
    except RunManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_status_response(state)


@router.get("", response_model=list[RunStatusResponse])
async def list_test_runs():
    return [_to_status_response(s) for s in list_runs()]


@router.get("/{run_id}", response_model=RunStatusResponse)
async def get_test_run(run_id: str):
    state = load_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_status_response(state)


@router.get("/{run_id}/tests")
async def get_test_cases(run_id: str):
    state = load_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "test_cases": [t.model_dump() for t in state.test_cases],
        "generated_scripts": [s.model_dump() for s in state.generated_scripts],
        "script_validation": state.script_validation,
    }


@router.get("/{run_id}/traces")
async def get_traces(run_id: str):
    state = load_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    events = get_event_bus().history(run_id)
    return {"events": [e.model_dump() for e in events]}


@router.get("/{run_id}/execution")
async def get_execution(run_id: str):
    state = load_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"execution_results": [r.model_dump() for r in state.execution_results]}


@router.get("/{run_id}/healing")
async def get_healing(run_id: str):
    state = load_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "failures": [f.model_dump() for f in state.failures],
        "healing_attempts": [h.model_dump() for h in state.healing_attempts],
    }


@router.get("/{run_id}/artifacts")
async def get_artifacts(run_id: str):
    state = load_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    base = run_dir(run_id)
    if not os.path.isdir(base):
        return {"artifacts": {}}
    tree: dict[str, list[str]] = {}
    for sub in sorted(os.listdir(base)):
        sub_path = os.path.join(base, sub)
        if os.path.isdir(sub_path):
            tree[sub] = sorted(
                f for f in os.listdir(sub_path) if os.path.isfile(os.path.join(sub_path, f))
            )
    return {"run_id": run_id, "artifacts": tree}


@router.get("/{run_id}/artifacts/{category}/{filename}")
async def download_artifact(run_id: str, category: str, filename: str):
    base = os.path.normpath(run_dir(run_id))
    path = os.path.normpath(os.path.join(base, category, filename))
    if not path.startswith(base) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path)


@router.get("/{run_id}/report")
async def get_report(run_id: str):
    state = load_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not state.final_report_path or not os.path.isfile(state.final_report_path):
        raise HTTPException(status_code=404, detail="Report not yet available for this run")
    return FileResponse(state.final_report_path, media_type="text/markdown")


@router.websocket("/{run_id}/events")
async def run_events_ws(websocket: WebSocket, run_id: str):
    await websocket.accept()
    bus = get_event_bus()

    for event in bus.history(run_id):
        await websocket.send_json(event.model_dump())

    queue = bus.subscribe(run_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(run_id, queue)
