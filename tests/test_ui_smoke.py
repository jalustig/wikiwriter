# ABOUTME: Playwright smoke test — verifies Streamlit app loads and run initiates correctly.
# ABOUTME: Does not wait for full LLM run; checks UI structure and initial stage rendering only.

import subprocess
import sys
import time

import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope="module")
def streamlit_server():
    """Start Streamlit on port 8599, yield base URL, then kill."""
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.port", "8599",
            "--server.headless", "true",
            "--server.fileWatcherType", "none",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(8)
    yield "http://localhost:8599"
    proc.terminate()
    proc.wait()


def test_app_loads(streamlit_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(streamlit_server, timeout=15000)
        expect(page.locator("text=WikiWriter")).to_be_visible(timeout=10000)
        browser.close()


def test_input_and_button_present(streamlit_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(streamlit_server, timeout=15000)
        page.wait_for_selector("text=WikiWriter", timeout=10000)
        expect(page.locator("input[type='text']")).to_be_visible(timeout=5000)
        expect(page.locator("button", has_text="Analyse & draft edit")).to_be_visible(timeout=5000)
        browser.close()


def test_run_shows_tabs_and_agent_loop(streamlit_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(streamlit_server, timeout=15000)
        page.wait_for_selector("input[type='text']", timeout=10000)

        page.fill("input[type='text']", "https://en.wikipedia.org/wiki/Super_Bowl_XXV")
        page.click("button:has-text('Analyse & draft edit')")

        # Tabs appear almost immediately
        expect(page.locator("[data-baseweb='tab']", has_text="Run")).to_be_visible(timeout=15000)
        expect(page.locator("[data-baseweb='tab']", has_text="Debug")).to_be_visible(timeout=5000)

        # Sidebar agent loop image appears immediately on run start
        expect(page.locator("[data-testid='stSidebar'] img")).to_be_visible(timeout=15000)

        # Agent Loop label present
        expect(page.locator("[data-testid='stSidebar']").locator("text=Agent Loop")).to_be_visible(
            timeout=5000
        )

        browser.close()
