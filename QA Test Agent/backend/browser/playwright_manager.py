"""Thin wrapper around Playwright's async API: browser lifecycle, isolated
contexts, and low-level capture helpers shared by discovery and execution.
No LLM code lives here - this module only does real browser operations."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

ENGINES = {"chromium", "firefox", "webkit"}


class PlaywrightManager:
    def __init__(self, engine: str = "chromium", headless: bool = True):
        if engine not in ENGINES:
            raise ValueError(f"Unsupported engine: {engine}")
        self.engine = engine
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, self.engine)
        self._browser = await launcher.launch(headless=self.headless)

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @asynccontextmanager
    async def new_context(self, **kwargs) -> AsyncIterator[BrowserContext]:
        assert self._browser is not None, "PlaywrightManager not started"
        context = await self._browser.new_context(**kwargs)
        try:
            yield context
        finally:
            await context.close()

    @asynccontextmanager
    async def new_page(self, context: BrowserContext) -> AsyncIterator[Page]:
        page = await context.new_page()
        try:
            yield page
        finally:
            await page.close()
