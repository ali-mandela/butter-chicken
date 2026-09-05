from __future__ import annotations

import os

from pydantic import BaseModel

from agents.script_generator.prompt import SYSTEM_PROMPT
from schemas.state import GeneratedScript, TestRunState
from services.llm_provider import get_llm_provider
from storage.run_repository import run_dir


class _ScriptOutput(BaseModel):
    source_code: str


async def run_script_generation(state: TestRunState) -> TestRunState:
    provider = get_llm_provider(state.config.llm_provider, state.config.llm_model)
    base = run_dir(state.run_id)
    scripts_dir = os.path.join(base, "scripts")

    scripts: list[GeneratedScript] = []
    for tc in state.test_cases:
        prompt = f"TEST CASE:\n{tc.model_dump()}"
        result = await provider.generate_structured(SYSTEM_PROMPT, prompt, _ScriptOutput)
        file_path = os.path.join(scripts_dir, f"{tc.test_case_id}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(result.source_code)
        scripts.append(
            GeneratedScript(
                test_case_id=tc.test_case_id,
                file_path=file_path,
                source_preview=result.source_code[:400],
            )
        )

    if not scripts:
        raise RuntimeError("Script Generator produced zero scripts")
    state.generated_scripts = scripts
    return state
