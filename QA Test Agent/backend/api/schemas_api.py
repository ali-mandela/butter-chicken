"""Request/response models for the HTTP API (kept separate from the
internal pipeline state schema in schemas/state.py)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CreateRunResponse(BaseModel):
    run_id: str
    status: str


class RunStatusResponse(BaseModel):
    run_id: str
    application_url: str
    llm_provider: str
    llm_model: str
    status: str
    current_stage: str
    current_node: Optional[str] = None
    plan_revision_count: int
    total_test_cases: int
    total_scripts: int
    error: Optional[str] = None
    created_at: str
    updated_at: str
