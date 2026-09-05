"""Real Playwright-driven page inspection + bounded crawler.

Never performs destructive actions (see security.domain_policy) and is
hard-bounded by MAX_PAGES / MAX_DEPTH / MAX_ACTIONS_PER_PAGE /
MAX_DISCOVERY_TIME_SECONDS so it can never crawl forever.
"""
from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page

from config.settings import get_settings
from schemas.state import ApplicationPage, PageElement
from security.domain_policy import is_destructive_action

INTERACTIVE_SELECTORS = "button, a, input, select, textarea, [role=button], [role=link], [role=tab]"

USERNAME_FIELD_SELECTOR = (
    'input[type="text"], input[type="email"], input[name*="user" i], input[id*="user" i], '
    'input[name*="email" i], input[id*="email" i]'
)
SUBMIT_SELECTOR = (
    'button[type="submit"], input[type="submit"], button:has-text("Log In"), '
    'button:has-text("Login"), button:has-text("Sign In"), button:has-text("Sign in")'
)


async def attempt_login(page: Page, url: str, credential) -> bool:
    """Best-effort heuristic login, run once before crawling.

    Many real applications (like this project's own SauceDemo test target)
    hide everything except the login page from an unauthenticated crawl -
    without this, Discovery only ever sees the login form and the Planner
    ends up proposing tests for pages that were never observed. This
    navigates to the app, looks for a password field as the signal that
    it's a login form, fills it (plus a paired username field, or a token
    into the password field for token auth) using common selector
    patterns, and submits. If no login form is found, or filling/submitting
    fails, this returns False and Discovery proceeds unauthenticated rather
    than blocking the whole run - login heuristics can't cover every app.
    """
    try:
        await page.goto(url, wait_until="networkidle", timeout=15000)
    except Exception:
        return False

    password_field = page.locator('input[type="password"]').first
    try:
        await password_field.wait_for(state="visible", timeout=3000)
    except Exception:
        return False  # no login form detected on the landing page

    try:
        if credential.auth_type == "username_password" and credential.username:
            username_field = page.locator(USERNAME_FIELD_SELECTOR).first
            await username_field.fill(credential.username)
            await password_field.fill(credential.password or "")
        elif credential.auth_type == "token" and credential.token:
            await password_field.fill(credential.token)
        else:
            return False

        await page.locator(SUBMIT_SELECTOR).first.click(timeout=3000)
        await page.wait_for_load_state("networkidle", timeout=10000)

        # If a password field is still visible after submitting, login
        # almost certainly failed (wrong creds, or an error banner reshown).
        remaining = page.locator('input[type="password"]').first
        if await remaining.count() and await remaining.is_visible():
            return False
        return True
    except Exception:
        return False


async def inspect_page(page: Page, url: str, screenshot_dir: str, dom_dir: str) -> ApplicationPage:
    title = await page.title()
    console_errors: list[str] = []
    network_failures: list[dict] = []

    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on(
        "requestfailed",
        lambda req: network_failures.append({"url": req.url, "failure": req.failure}),
    )

    elements: list[PageElement] = []
    handles = await page.query_selector_all(INTERACTIVE_SELECTORS)
    for handle in handles[: get_settings().max_actions_per_page]:
        try:
            tag = await handle.evaluate("el => el.tagName.toLowerCase()")
            text = (await handle.inner_text()).strip()[:120] if await handle.is_visible() else ""
            role = await handle.get_attribute("role")
            elem_id = await handle.get_attribute("id")
            name = await handle.get_attribute("name")
            test_id = await handle.get_attribute("data-testid")
            aria_label = await handle.get_attribute("aria-label")

            if is_destructive_action(text) or is_destructive_action(aria_label or ""):
                continue  # never record/interact with destructive controls during discovery

            candidates = []
            if test_id:
                candidates.append(f'get_by_test_id("{test_id}")')
            if role and (text or aria_label):
                candidates.append(f'get_by_role("{role}", name="{aria_label or text}")')
            if elem_id:
                candidates.append(f"#{elem_id}")

            elements.append(
                PageElement(
                    type=tag,
                    text=text or None,
                    role=role,
                    id=elem_id,
                    name=name,
                    test_id=test_id,
                    aria_label=aria_label,
                    selector_candidates=candidates,
                )
            )
        except Exception:
            continue

    forms = []
    for form in await page.query_selector_all("form"):
        try:
            inputs = await form.query_selector_all("input, select, textarea")
            field_names = [await i.get_attribute("name") or await i.get_attribute("id") or "" for i in inputs]
            forms.append({"field_names": [f for f in field_names if f]})
        except Exception:
            continue

    links = []
    base = urlparse(url)
    for a in await page.query_selector_all("a[href]"):
        href = await a.get_attribute("href")
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = urljoin(url, href)
        if urlparse(absolute).netloc == base.netloc:
            links.append(absolute)

    tables = []
    for table in await page.query_selector_all("table"):
        try:
            headers = await table.eval_on_selector_all("th", "els => els.map(e => e.innerText.trim())")
            tables.append({"headers": headers})
        except Exception:
            continue

    safe_name = "".join(c if c.isalnum() else "_" for c in url)[:100]
    screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
    dom_path = os.path.join(dom_dir, f"{safe_name}.html")
    await page.screenshot(path=screenshot_path, full_page=True)
    with open(dom_path, "w", encoding="utf-8") as f:
        f.write(await page.content())

    return ApplicationPage(
        url=url,
        title=title,
        elements=elements,
        forms=forms,
        links=sorted(set(links)),
        tables=tables,
        navigation=[l for l in links if l != url],
        screenshot_path=screenshot_path,
        dom_snapshot_path=dom_path,
        console_errors=console_errors[:20],
        network_failures=network_failures[:20],
    )


async def crawl(page: Page, start_url: str, screenshot_dir: str, dom_dir: str) -> list[ApplicationPage]:
    settings = get_settings()
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start_url, 0)]
    pages: list[ApplicationPage] = []
    start_time = time.monotonic()

    while queue and len(pages) < settings.max_pages:
        if time.monotonic() - start_time > settings.max_discovery_time_seconds:
            break
        url, depth = queue.pop(0)
        if url in visited or depth > settings.max_depth:
            continue
        visited.add(url)
        try:
            await page.goto(url, wait_until="networkidle", timeout=15000)
        except Exception:
            continue

        app_page = await inspect_page(page, url, screenshot_dir, dom_dir)
        pages.append(app_page)

        if depth < settings.max_depth:
            for link in app_page.links:
                if link not in visited and len(queue) + len(pages) < settings.max_pages:
                    queue.append((link, depth + 1))

    return pages
