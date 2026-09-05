"""PRD Analyzer Agent: extracts raw text from the uploaded requirements
document (PDF/DOCX/TXT/MD), then asks the LLM to structure it into
requirements, validated against the Requirement schema."""
from __future__ import annotations

import os

from pydantic import BaseModel, Field

from agents.prd_analyzer.prompt import SYSTEM_PROMPT
from schemas.state import Requirement, TestRunState
from services.llm_provider import get_llm_provider
from storage.run_repository import run_dir


class _RequirementList(BaseModel):
    requirements: list[Requirement] = Field(default_factory=list)


def _extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".txt", ".md"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == ".docx":
        import docx

        doc = docx.Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs)
    raise ValueError(f"Unsupported requirements file type: {ext}")


async def run_prd_analysis(state: TestRunState) -> TestRunState:
    if not state.config.requirements_filename:
        raise RuntimeError("No requirements document was uploaded for this run")

    base = run_dir(state.run_id)
    file_path = os.path.join(base, "requirements", state.config.requirements_filename)
    if not os.path.exists(file_path):
        raise RuntimeError(f"Requirements file not found on disk: {file_path}")

    text = _extract_text(file_path)
    if not text.strip():
        raise RuntimeError("Requirements document contained no extractable text")

    provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
    result = await provider.generate_structured(
        SYSTEM_PROMPT,
        f"REQUIREMENTS DOCUMENT:\n\n{text[:60000]}",
        _RequirementList,
    )
    if not result.requirements:
        raise RuntimeError("PRD Analyzer produced zero requirements from the document")

    state.requirements = result.requirements
    return state
