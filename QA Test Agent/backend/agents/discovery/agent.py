"""Discovery Agent: runs a real, bounded Playwright crawl of the target
application and converts raw browser observations into a structured
ApplicationMap. No LLM calls here - this agent's job is to *observe*, not
reason; the Planner reasons over its output.

If the run has stored credentials (username/password or token), Discovery
logs in first (best-effort, see browser.discovery.attempt_login) so the
crawl can see authenticated pages instead of only the login screen - most
real applications hide everything behind a login."""
from __future__ import annotations

from browser.discovery import attempt_login, crawl
from browser.playwright_manager import PlaywrightManager
from schemas.state import ApplicationMap, TestRunState
from security.domain_policy import validate_application_url
from security.secrets import get_secret_store
from storage.run_repository import run_dir


async def run_discovery(state: TestRunState) -> TestRunState:
    url = validate_application_url(state.config.application_url)
    base = run_dir(state.run_id)
    screenshot_dir = f"{base}/screenshots"
    dom_dir = f"{base}/dom"

    credential = None
    if state.config.credential_ref:
        credential = get_secret_store().get(state.config.credential_ref)

    manager = PlaywrightManager(engine="chromium", headless=True)
    await manager.start()
    logged_in = False
    try:
        async with manager.new_context() as context:
            async with manager.new_page(context) as page:
                start_url = url
                if credential is not None and credential.auth_type in ("username_password", "token"):
                    logged_in = await attempt_login(page, url, credential)
                    if logged_in:
                        start_url = page.url
                pages = await crawl(page, start_url, screenshot_dir, dom_dir)
    finally:
        await manager.stop()

    if not pages:
        raise RuntimeError(f"Discovery could not reach {url} (navigation failed or blocked by policy)")

    observations = [f"Discovered {len(pages)} page(s) within configured crawl limits"]
    if credential is not None and credential.auth_type in ("username_password", "token"):
        observations.append(
            "Logged in before crawling - authenticated pages are included"
            if logged_in
            else "Could not log in before crawling - only unauthenticated pages were discovered"
        )

    app_map = ApplicationMap(
        base_url=url,
        title=pages[0].title,
        pages=pages,
        observations=observations,
    )
    state.application_map = app_map
    return state
