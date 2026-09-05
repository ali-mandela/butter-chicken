"""Reads/writes TestRunState to SQLite and manages the per-run artifact
directory tree described in the spec's Artifact Management section."""
from __future__ import annotations

import os

from config.settings import get_settings
from schemas.state import TestRunState
from storage.db import TestRunRecord, get_session

ARTIFACT_SUBDIRS = (
    "requirements",
    "application-map",
    "dom",
    "screenshots",
    "videos",
    "traces",
    "test-plans",
    "test-cases",
    "scripts",
    "execution",
    "healing",
    "logs",
    "report",
)


def run_dir(run_id: str) -> str:
    settings = get_settings()
    base = os.path.join(os.path.dirname(__file__), "..", settings.artifacts_root, run_id)
    return os.path.normpath(base)


def ensure_run_dirs(run_id: str) -> str:
    base = run_dir(run_id)
    for sub in ARTIFACT_SUBDIRS:
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    return base


def save_state(state: TestRunState) -> None:
    session = get_session()
    try:
        record = session.get(TestRunRecord, state.run_id)
        if record is None:
            record = TestRunRecord(run_id=state.run_id)
            session.add(record)
        record.application_url = state.config.application_url
        record.status = state.status.value if hasattr(state.status, "value") else state.status
        record.current_stage = (
            state.current_stage.value if hasattr(state.current_stage, "value") else state.current_stage
        )
        record.state_json = state.model_dump_json()
        session.commit()
    finally:
        session.close()


def load_state(run_id: str) -> TestRunState | None:
    session = get_session()
    try:
        record = session.get(TestRunRecord, run_id)
        if record is None:
            return None
        return TestRunState.model_validate_json(record.state_json)
    finally:
        session.close()


def list_runs() -> list[TestRunState]:
    session = get_session()
    try:
        records = session.query(TestRunRecord).order_by(TestRunRecord.created_at.desc()).all()
        return [TestRunState.model_validate_json(r.state_json) for r in records]
    finally:
        session.close()
