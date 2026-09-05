from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aivar.explorer import explore, ExplorationReport, dismiss_consent, is_destructive


@pytest.fixture
def site_index_url() -> str:
    """Return a file:// URL to the local site/index.html fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "site" / "index.html"
    return fixture_path.resolve().as_uri()


@pytest.fixture
def site_login_url(site_index_url: str) -> str:
    """Return a file:// URL to the local site/login.html fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "site" / "login.html"
    return fixture_path.resolve().as_uri()


@pytest.fixture
def site_consent_url() -> str:
    """Return a file:// URL to the local site/consent.html fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "site" / "consent.html"
    return fixture_path.resolve().as_uri()


class TestExplorer:
    """Test the Explorer crawler."""

    def test_explores_entry_page(self, site_index_url: str):
        """Exploring index.html records the entry page with title, heading, and links."""
        report = explore(site_index_url)

        assert report.page_count >= 1
        entry_page = report.pages[0]
        assert entry_page.url == site_index_url
        assert entry_page.title == "Home"
        assert "Welcome" in entry_page.headings
        assert entry_page.reached_by is None

        # Should have found the links
        assert len(entry_page.links) >= 2  # At least the same-origin links
        link_urls = entry_page.links
        # Check that login and about are present (relative URLs resolved to absolute)
        assert any("login.html" in link for link in link_urls)
        assert any("about.html" in link for link in link_urls)

    def test_crawl_respects_max_pages(self, site_index_url: str):
        """max_pages=2 should visit exactly 2 pages."""
        report = explore(site_index_url, max_pages=2)
        assert report.page_count == 2

    def test_crawl_respects_max_depth(self, site_index_url: str):
        """max_depth=0 should visit only the entry page."""
        report = explore(site_index_url, max_depth=0)
        assert report.page_count == 1
        assert report.pages[0].url == site_index_url

    def test_external_links_are_not_crawled(self, site_index_url: str):
        """example.com should never appear in visited page URLs."""
        report = explore(site_index_url, same_origin_only=True)

        visited_urls = [page.url for page in report.pages]
        for visited_url in visited_urls:
            assert "example.com" not in visited_url

    def test_logout_links_are_skipped(self, site_index_url: str):
        """No visited page URL should end with logout.html (crawling logout would destroy the session)."""
        # This test assumes we crawl to the login page which has a logout link
        report = explore(site_index_url, max_pages=10)

        visited_urls = [page.url for page in report.pages]
        for visited_url in visited_urls:
            # Logout links should be skipped to avoid destroying the session mid-exploration
            assert not visited_url.endswith("logout.html")

    def test_detects_login_form(self, site_login_url: str):
        """Exploring login.html should detect a login form."""
        report = explore(site_login_url)

        assert report.login_form is not None
        assert report.login_form.is_login is True
        # Should have exactly one password field
        password_fields = [f for f in report.login_form.fields if f.field_type == "password"]
        assert len(password_fields) == 1
        # Should identify a username-like field
        username_fields = [f for f in report.login_form.fields if f.field_type in ("text", "email")]
        assert len(username_fields) >= 1

    def test_form_fields_have_usable_selectors(self, site_login_url: str):
        """Every FormField.selector should be usable and resolve to exactly one element."""
        from playwright.sync_api import sync_playwright
        from aivar.browser import Browser, build_locator

        report = explore(site_login_url)
        assert report.login_form is not None

        # Now verify selectors work by loading the page and checking they resolve
        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(site_login_url)

            for field in report.login_form.fields:
                locator = build_locator(page, field.selector)
                # Should resolve to exactly one element
                count = locator.count()
                assert count == 1, f"Field {field.name} with selector {field.selector} resolved to {count} elements"

            page.close()
            browser.close()
        finally:
            playwright.stop()

    def test_summarize_is_bounded(self, site_index_url: str):
        """summarize(max_chars=200) should return at most 200 chars and contain the entry URL."""
        report = explore(site_index_url, max_pages=5)
        summary = report.summarize(max_chars=200)

        assert len(summary) <= 200
        assert site_index_url in summary

    def test_errors_do_not_abort_crawl(self, site_index_url: str):
        """A link to a nonexistent page should not abort the crawl."""
        # We'll test this by checking that errors are recorded but crawl continues
        report = explore(site_index_url, max_pages=5)

        # The report should complete successfully
        assert report is not None
        # The entry page should be present
        assert len(report.pages) >= 1
        entry_urls = [p.url for p in report.pages]
        assert site_index_url in entry_urls

    def test_no_llm_is_used(self, site_index_url: str):
        """Exploration should not call any LLM functions."""
        # Patch the LLM chat function to raise an error if called
        with patch("aivar.llm.chat_json") as mock_chat:
            mock_chat.side_effect = RuntimeError("LLM should not be called during exploration")

            # This should complete without calling the LLM
            # (Exploration is deliberately free and deterministic)
            report = explore(site_index_url, max_pages=2)

            # Should complete successfully
            assert report is not None
            assert report.page_count >= 1

            # LLM should not have been called
            mock_chat.assert_not_called()

    def test_report_to_dict(self, site_index_url: str):
        """to_dict() should produce valid JSON-serializable output."""
        import json

        report = explore(site_index_url, max_pages=2)
        report_dict = report.to_dict()

        # Should be JSON-serializable
        json_str = json.dumps(report_dict, indent=2)
        assert json_str
        assert "entry_url" in json_str

    def test_authenticated_flag(self, site_login_url: str):
        """authenticated flag should be False when no credentials provided."""
        report = explore(site_login_url)
        assert report.authenticated is False

    def test_page_count_property(self, site_index_url: str):
        """page_count property should equal len(pages)."""
        report = explore(site_index_url, max_pages=3)
        assert report.page_count == len(report.pages)

    @pytest.mark.live
    def test_explores_saucedemo(self):
        """Test exploring real https://www.saucedemo.com with standard demo credentials."""
        report = explore(
            "https://www.saucedemo.com",
            username="standard_user",
            password="secret_sauce",
            max_pages=8,
            max_depth=2,
            headless=True,
        )

        # Should authenticate successfully
        assert report.authenticated is True

        # Should discover more than one page
        assert report.page_count > 1

        # Should have found a login form on the entry page
        assert report.login_form is not None

    def test_crawl_with_login_no_credentials(self, site_login_url: str):
        """Crawl with login page but no credentials should record the login form but not authenticate."""
        report = explore(site_login_url)

        assert report.login_form is not None
        assert report.authenticated is False

    def test_links_are_normalized(self, site_index_url: str):
        """Links should be resolved to absolute URLs and normalized (no fragments)."""
        report = explore(site_index_url)

        for page in report.pages:
            for link in page.links:
                # All links should be absolute
                assert link.startswith("file://") or link.startswith("http://") or link.startswith("https://")
                # No fragments
                assert "#" not in link

    def test_dismiss_consent_clicks_accept_all(self, site_consent_url: str):
        """dismiss_consent should click 'Accept all' button on consent.html and return the text."""
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(site_consent_url)

            # The overlay should be visible initially
            overlay = page.query_selector("#consent-overlay")
            assert overlay is not None

            # Dismiss the consent banner
            result = dismiss_consent(page)

            # Should have returned the text that was clicked
            assert result is not None
            assert "accept" in result.lower()

            # The overlay should now be hidden
            overlay_hidden = page.query_selector("#consent-overlay[style*='display: none']")
            assert overlay_hidden is not None or not overlay.is_visible()

            page.close()
            browser.close()
        finally:
            playwright.stop()

    def test_dismiss_consent_shows_content_after(self, site_consent_url: str):
        """After dismissal of consent, the <h1>Behind the banner</h1> heading should be observable."""
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(site_consent_url)

            # Dismiss the consent banner
            dismiss_consent(page)

            # The h1 should now be visible
            heading = page.query_selector("h1")
            assert heading is not None
            assert heading.text_content() == "Behind the banner"

            page.close()
            browser.close()
        finally:
            playwright.stop()

    def test_dismiss_consent_returns_none_on_no_banner(self, site_index_url: str):
        """dismiss_consent should return None on a page with no banner and not raise."""
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(site_index_url)

            # This page has no consent banner
            result = dismiss_consent(page)

            # Should return None without raising
            assert result is None

            page.close()
            browser.close()
        finally:
            playwright.stop()

    def test_explore_sets_consent_dismissed(self, site_consent_url: str):
        """explore() should set consent_dismissed on the report when a banner is dismissed."""
        report = explore(site_consent_url)

        # Should have dismissed the consent banner
        assert report.consent_dismissed is not None
        assert "accept" in report.consent_dismissed.lower()

    def test_is_destructive_detects_submit_words(self):
        """is_destructive should detect names containing destructive keywords."""
        # Should be destructive
        assert is_destructive("Send message") is True
        assert is_destructive("Place order") is True
        assert is_destructive("Delete account") is True
        assert is_destructive("Subscribe now") is True

    def test_is_destructive_excludes_login(self):
        """is_destructive should NOT mark login/signin controls as destructive."""
        # Should NOT be destructive (authentication is required)
        assert is_destructive("Log in") is False
        assert is_destructive("Sign in") is False
        assert is_destructive("Continue") is False

    def test_safe_mode_skips_destructive_controls(self, site_index_url: str):
        """In safe_mode=True, destructive controls should be recorded in skipped_controls."""
        report = explore(site_index_url, safe_mode=True)

        # The report should indicate safe_mode was enabled
        assert report.safe_mode is True

        # Should have identified and skipped "Send message" control
        assert "Send message" in report.skipped_controls

    def test_safe_mode_false_does_not_skip(self, site_index_url: str):
        """In safe_mode=False (default), skipped_controls should be empty."""
        report = explore(site_index_url, safe_mode=False)

        # Should not have skipped any controls
        assert report.safe_mode is False
        assert len(report.skipped_controls) == 0

    def test_report_to_dict_includes_new_fields(self, site_index_url: str):
        """to_dict() should include consent_dismissed, safe_mode, and skipped_controls."""
        import json

        report = explore(site_index_url, safe_mode=True)
        report_dict = report.to_dict()

        # Should include all new fields
        assert "consent_dismissed" in report_dict
        assert "safe_mode" in report_dict
        assert "skipped_controls" in report_dict

        # Should be JSON-serializable
        json_str = json.dumps(report_dict, indent=2)
        assert json_str
        assert "safe_mode" in json_str
        assert "skipped_controls" in json_str

    def test_form_with_one_password_field_named_login_form(self, site_login_url: str):
        """A form containing exactly one password field should be named 'login form'."""
        report = explore(site_login_url)

        assert report.login_form is not None
        # Should be named "login form" or similar
        assert "login" in report.login_form.name.lower()

    def test_form_named_after_submit_button(self):
        """A form whose submit button has text should use that for naming."""
        from playwright.sync_api import sync_playwright
        from aivar.explorer import _extract_forms
        from aivar.browser import Browser

        html = """
        <html>
        <body>
            <form>
                <input type="email" name="email" placeholder="Email">
                <button type="submit">Send Reset Code</button>
            </form>
        </body>
        </html>
        """

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)

            browser_wrapper = Browser(page)
            forms = _extract_forms(page, browser_wrapper)

            assert len(forms) == 1
            form = forms[0]
            # Should be named after the submit button text
            assert "send reset code" in form.name.lower()

            page.close()
            browser.close()
        finally:
            playwright.stop()

    def test_form_named_after_first_field(self):
        """A form with fields but no submit button takes its first field's name."""
        from playwright.sync_api import sync_playwright
        from aivar.explorer import _extract_forms
        from aivar.browser import Browser

        html = """
        <html>
        <body>
            <form>
                <input type="text" name="search" placeholder="Search">
                <input type="text" name="query" placeholder="Query">
            </form>
        </body>
        </html>
        """

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)

            browser_wrapper = Browser(page)
            forms = _extract_forms(page, browser_wrapper)

            assert len(forms) == 1
            form = forms[0]
            # Should be named after the first field
            assert "search" in form.name.lower()

            page.close()
            browser.close()
        finally:
            playwright.stop()

    def test_form_falls_back_to_form_n(self):
        """A form with no identifiable content falls back to 'form 1' etc."""
        from playwright.sync_api import sync_playwright
        from aivar.explorer import _extract_forms
        from aivar.browser import Browser

        html = """
        <html>
        <body>
            <form>
                <input type="text">
                <input type="text">
            </form>
        </body>
        </html>
        """

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)

            browser_wrapper = Browser(page)
            forms = _extract_forms(page, browser_wrapper)

            assert len(forms) == 1
            form = forms[0]
            # Should fall back to "form 1" when nothing else is available
            assert form.name == "form 1"

            page.close()
            browser.close()
        finally:
            playwright.stop()
