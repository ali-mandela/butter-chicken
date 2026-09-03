import logging
import time

from playwright.sync_api import sync_playwright

from app.llm import heal_selector
from app.memory import get_healed_selector, save_healed_selector

logger = logging.getLogger("aivar")

GENERIC_WORDS = {"input", "field", "box", "button", "header", "page", "label", "the", "a", "an", "text"}


def normalize_target(target: str) -> str:
    words = [w for w in target.lower().split() if w not in GENERIC_WORDS]
    return " ".join(words) if words else target


def substitute_value(target: str, value: str, username: str, password: str) -> str:
    t = target.lower()
    if "user" in t:
        return username
    if "pass" in t:
        return password
    return value


def resolve_locator(page, target: str):
    query = normalize_target(target)
    candidates = [
        lambda: page.get_by_role("button", name=query, exact=False),
        lambda: page.get_by_label(query, exact=False),
        lambda: page.get_by_placeholder(query, exact=False),
        lambda: page.get_by_text(query, exact=False),
    ]
    for make in candidates:
        try:
            loc = make()
            if loc.count() > 0:
                return loc.first
        except Exception:
            continue
    return None


def build_locator(page, strategy: dict):
    kind = strategy.get("strategy")
    value = strategy.get("value", "")
    if kind == "text":
        return page.get_by_text(value, exact=False)
    if kind == "role":
        return page.get_by_role(strategy.get("role") or "button", name=value, exact=False)
    if kind == "placeholder":
        return page.get_by_placeholder(value, exact=False)
    if kind == "label":
        return page.get_by_label(value, exact=False)
    raise ValueError(f"unknown strategy: {kind!r}")


def run_test(steps: list, url: str, username: str, password: str) -> dict:
    results = []
    healing_events = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        t0 = time.perf_counter()
        page.goto(url)
        logger.info(f"goto {url} ({(time.perf_counter() - t0) * 1000:.0f}ms)")

        for i, step in enumerate(steps):
            action = step.get("action")
            target = step.get("target", "")
            value = substitute_value(target, step.get("value", ""), username, password)
            t_step = time.perf_counter()
            logger.info(f"step {i}: action={action} target={target!r}")

            source = "cache"
            cached = get_healed_selector(url, target)
            locator = build_locator(page, cached) if cached else None
            logger.info(f"step {i}: cache lookup -> {'hit' if cached else 'miss'} ({(time.perf_counter() - t_step) * 1000:.0f}ms)")

            if locator is None:
                t_h = time.perf_counter()
                locator = resolve_locator(page, target)
                source = "heuristic"
                logger.info(f"step {i}: heuristic -> {'found' if locator else 'miss'} ({(time.perf_counter() - t_h) * 1000:.0f}ms)")

            if locator is None:
                t_heal = time.perf_counter()
                snapshot = page.locator("body").aria_snapshot()
                try:
                    healed = heal_selector(target, snapshot)
                    locator = build_locator(page, healed)
                    source = "healed"
                    logger.info(f"step {i}: healed -> {healed} ({(time.perf_counter() - t_heal) * 1000:.0f}ms)")
                    save_healed_selector(
                        url, target, healed["strategy"], healed["value"], healed.get("role"), healed.get("reasoning", "")
                    )
                    healing_events.append(
                        {
                            "target": target,
                            "old_attempt": "heuristic locators (role/label/placeholder/text)",
                            "new_selector": f"{healed['strategy']}={healed['value']}",
                            "reasoning": healed.get("reasoning", ""),
                        }
                    )
                except Exception as e:
                    logger.info(f"step {i}: healing failed -> {e}")
                    results.append({"step": step, "status": "failed", "error": str(e), "source": "healing_failed"})
                    continue

            try:
                t_act = time.perf_counter()
                if action == "click":
                    locator.click(timeout=8000)
                elif action == "type":
                    locator.fill(value, timeout=8000)
                elif action == "assert_visible":
                    locator.wait_for(state="visible", timeout=8000)
                logger.info(f"step {i}: {action} ok ({(time.perf_counter() - t_act) * 1000:.0f}ms)")
                results.append({"step": step, "status": "passed", "source": source})
            except Exception as e:
                logger.info(f"step {i}: {action} failed -> {e}")
                results.append({"step": step, "status": "failed", "error": str(e), "source": source})

        browser.close()

    overall = "passed" if all(r["status"] == "passed" for r in results) else "failed"
    return {"status": overall, "results": results, "healing_events": healing_events}
