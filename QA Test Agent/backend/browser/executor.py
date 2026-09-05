"""Executes one already-validated generated Playwright script against a
real, isolated browser context and captures a full execution record.

Security note: the script has already passed script_validator's static
checks (no os.system/subprocess/eval/exec/time.sleep, required signature,
at least one real assertion) before it is ever loaded here. This is a
controlled environment, not a full untrusted-code sandbox (e.g. no separate
OS process/container per script) - see README security notes for the
tradeoff and what a hardened deployment should add.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import traceback
import uuid
from typing import Optional

# Generated test scripts live under the run's own artifacts/scripts folder;
# never let Python drop __pycache__/*.pyc alongside them (it would show up
# as a bogus "artifact" in the Artifacts tab / download endpoint).
sys.dont_write_bytecode = True

from browser.playwright_manager import PlaywrightManager
from schemas.state import ExecutionRecord, GeneratedScript, TestStatus, now_iso
from security.secrets import Credential


def _load_test_function(file_path: str):
    module_name = f"generated_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "test_case", None)
    if fn is None:
        raise RuntimeError("Generated script does not define test_case(page, base_url, credentials)")
    return fn


def _credential_dict(credential: Optional[Credential]) -> dict:
    if credential is None:
        return {}
    return {
        "username": credential.username,
        "password": credential.password,
        "token": credential.token,
    }


async def execute_script(
    manager: PlaywrightManager,
    script: GeneratedScript,
    base_url: str,
    credential: Optional[Credential],
    artifacts_dir: str,
) -> ExecutionRecord:
    test_case_id = script.test_case_id
    console_logs: list[str] = []
    network_errors: list[str] = []
    screenshots: list[str] = []
    started_at = now_iso()
    start = time.monotonic()

    video_dir = os.path.join(artifacts_dir, "videos")
    trace_path = os.path.join(artifacts_dir, "traces", f"{test_case_id}.zip")
    screenshot_path = os.path.join(artifacts_dir, "screenshots", f"{test_case_id}_failure.png")

    errors: list[str] = []
    status = TestStatus.PASSED
    video_path: Optional[str] = None

    async with manager.new_context(record_video_dir=video_dir) as context:
        await context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = await context.new_page()
        page.on(
            "console",
            lambda msg: console_logs.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None,
        )
        page.on("requestfailed", lambda req: network_errors.append(f"{req.url}: {req.failure}"))

        try:
            fn = _load_test_function(script.file_path)
            await fn(page, base_url, _credential_dict(credential))
        except Exception as exc:  # noqa: BLE001 - must capture, classify, never crash the run
            status = TestStatus.FAILED
            errors.append(f"{type(exc).__name__}: {exc}")
            errors.append(traceback.format_exc()[-4000:])
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
                screenshots.append(screenshot_path)
            except Exception:
                pass
        finally:
            try:
                await context.tracing.stop(path=trace_path)
            except Exception:
                trace_path = None
            try:
                video_path = await page.video.path() if page.video else None
            except Exception:
                video_path = None

    duration = time.monotonic() - start
    return ExecutionRecord(
        test_case_id=test_case_id,
        status=status,
        duration_seconds=round(duration, 2),
        screenshots=screenshots,
        video_path=video_path,
        trace_path=trace_path if trace_path and os.path.exists(trace_path) else None,
        console_logs=console_logs[:50],
        network_errors=network_errors[:50],
        errors=errors,
        started_at=started_at,
        finished_at=now_iso(),
    )
