from __future__ import annotations

from pathlib import Path

import pytest

from aivar.browser import Browser, Node


@pytest.fixture
def fixture_url() -> str:
    """Return a file:// URL to the local login.html fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "login.html"
    return fixture_path.resolve().as_uri()


@pytest.fixture
def saucedemo_fixture_url() -> str:
    """Return a file:// URL to the saucedemo_like.html fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "saucedemo_like.html"
    return fixture_path.resolve().as_uri()


@pytest.fixture
def saucedemo_browser(saucedemo_fixture_url: str):
    """Fixture that creates a Browser instance with saucedemo_like.html loaded."""
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(saucedemo_fixture_url)
        browser_wrapper = Browser(page)
        yield browser_wrapper
    finally:
        page.close()
        browser.close()
        playwright.stop()


@pytest.fixture
def browser(fixture_url: str):
    """Fixture that creates a Browser instance with a page loaded to login.html."""
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(fixture_url)
        browser_wrapper = Browser(page)
        yield browser_wrapper
    finally:
        page.close()
        browser.close()
        playwright.stop()


class TestSnapshot:
    """Test Browser.snapshot() method."""

    def test_snapshot_returns_list_of_nodes(self, browser: Browser):
        """snapshot() should return a list of Node objects."""
        nodes = browser.snapshot()
        assert isinstance(nodes, list)
        assert len(nodes) > 0
        assert all(isinstance(n, Node) for n in nodes)

    def test_snapshot_nodes_have_refs(self, browser: Browser):
        """Every node should have a non-empty ref like e0, e1, etc."""
        nodes = browser.snapshot()
        for i, node in enumerate(nodes):
            assert node.ref == f"e{i}"
            assert node.ref != ""

    def test_snapshot_includes_testid_node(self, browser: Browser):
        """snapshot() should include node with data-testid='login-submit'."""
        nodes = browser.snapshot()
        testid_nodes = [n for n in nodes if n.testid == "login-submit"]
        assert len(testid_nodes) > 0
        node = testid_nodes[0]
        assert node.role == "button"

    def test_snapshot_includes_username_input(self, browser: Browser):
        """snapshot() should include the Username input."""
        nodes = browser.snapshot()
        username_nodes = [n for n in nodes if n.placeholder == "Username"]
        assert len(username_nodes) > 0
        node = username_nodes[0]
        assert node.role == "textbox"
        assert node.visible

    def test_snapshot_includes_password_input(self, browser: Browser):
        """snapshot() should include the Password input."""
        nodes = browser.snapshot()
        password_nodes = [n for n in nodes if n.placeholder == "Password"]
        assert len(password_nodes) > 0
        node = password_nodes[0]
        assert node.role == "textbox"
        assert node.visible

    def test_snapshot_includes_labels(self, browser: Browser):
        """snapshot() should include label elements."""
        nodes = browser.snapshot()
        labels = [n for n in nodes if n.tag == "label"]
        assert len(labels) >= 2

    def test_snapshot_includes_hidden_element(self, browser: Browser):
        """snapshot() should include the hidden Products header."""
        nodes = browser.snapshot()
        product_nodes = [n for n in nodes if "products" in n.name.lower()]
        # The Products h1 exists in the HTML but is hidden
        # It will have visible=False
        assert len(product_nodes) >= 1

    def test_snapshot_marks_visible_correctly(self, browser: Browser):
        """Visible elements should have visible=True, hidden should have visible=False."""
        nodes = browser.snapshot()
        username_nodes = [n for n in nodes if n.placeholder == "Username"]
        assert len(username_nodes) > 0
        assert username_nodes[0].visible

        # Hidden Products header
        product_nodes = [n for n in nodes if n.tag == "h1"]
        if product_nodes:
            # It starts hidden
            assert not product_nodes[0].visible

    def test_snapshot_reports_data_test_attribute(self, saucedemo_browser: Browser):
        """Against saucedemo_like.html, a node with data-test should report testid_attr='data-test'."""
        nodes = saucedemo_browser.snapshot()
        username_nodes = [n for n in nodes if n.testid == "username"]
        assert len(username_nodes) > 0
        node = username_nodes[0]
        assert node.testid == "username"
        assert node.testid_attr == "data-test"

    def test_snapshot_reports_data_testid_attribute(self, browser: Browser):
        """Against login.html, a node with data-testid should report testid_attr='data-testid'."""
        nodes = browser.snapshot()
        testid_nodes = [n for n in nodes if n.testid == "login-submit"]
        assert len(testid_nodes) > 0
        node = testid_nodes[0]
        assert node.testid == "login-submit"
        assert node.testid_attr == "data-testid"


class TestActAndWaitAttached:
    """Test Browser.act() and wait_attached() methods."""

    def test_fill_username(self, browser: Browser):
        """Should be able to fill the username input."""
        from aivar.models import Selector

        selector = Selector(strategy="placeholder", value="Username")
        browser.act(selector, "fill", "testuser", 5000)
        # Verify by checking the input value
        value = browser._page.evaluate(
            'document.getElementById("user").value'
        )
        assert value == "testuser"

    def test_click_button(self, browser: Browser):
        """Should be able to click the login button."""
        from aivar.models import Selector

        # Fill username and password first
        username_sel = Selector(strategy="placeholder", value="Username")
        password_sel = Selector(strategy="placeholder", value="Password")
        browser.act(username_sel, "fill", "test", 5000)
        browser.act(password_sel, "fill", "test", 5000)

        # Click login
        login_sel = Selector(strategy="testid", value="login-submit")
        browser.act(login_sel, "click", None, 5000)

        # The Products header should now be visible
        visible = browser._page.evaluate(
            'document.getElementById("products").style.display !== "none"'
        )
        assert visible

    def test_wait_visible(self, browser: Browser):
        """Should be able to wait for element to become visible."""
        from aivar.models import Selector

        # First, click the button to make Products visible
        username_sel = Selector(strategy="placeholder", value="Username")
        password_sel = Selector(strategy="placeholder", value="Password")
        login_sel = Selector(strategy="testid", value="login-submit")

        browser.act(username_sel, "fill", "test", 5000)
        browser.act(password_sel, "fill", "test", 5000)
        browser.act(login_sel, "click", None, 5000)

        # Now wait for Products to be visible
        products_sel = Selector(strategy="text", value="Products")
        browser.act(products_sel, "wait_visible", None, 5000)
        # If no exception, the wait succeeded

    def test_wait_attached(self, browser: Browser):
        """Should be able to wait for element to be attached."""
        from aivar.models import Selector

        selector = Selector(strategy="placeholder", value="Username")
        browser.wait_attached(selector, 5000)
        # If no exception, element is attached
