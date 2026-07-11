"""
Firefox Playwright scraper for Pro Football Reference.

Uses Playwright's bundled Firefox (no external browser needed) with a
persistent profile so Cloudflare cookies carry over between runs.

A browser window will open on the first run — solve any Cloudflare challenge
manually, then the scraper takes over.
"""

from __future__ import annotations

import asyncio
import pathlib
import random
import threading
import time

from bs4 import BeautifulSoup

DEFAULT_PROFILE = str(pathlib.Path.home() / ".local" / "share" / "pfref_firefox_profile")


class FirefoxScraper:
    """
    Synchronous scraper backed by a real Firefox browser (Playwright-bundled).

    Same fetch / fetch_and_sleep interface as PFRefScraper and PlaywrightScraper.

    Args:
        sleep_min: Minimum seconds between requests (default 4.0)
        sleep_max: Maximum seconds between requests (default 7.0)
        profile_dir: Persistent Firefox profile directory
        headless: Run headlessly — set False (default) for Cloudflare to pass
        page_load_wait: Seconds to wait after page load for CF challenges (default 4)
    """

    def __init__(
        self,
        sleep_min: float = 4.0,
        sleep_max: float = 7.0,
        profile_dir: str | None = None,
        headless: bool = False,
        page_load_wait: float = 4.0,
    ):
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self.headless = headless
        self.page_load_wait = page_load_wait
        self._profile_dir = profile_dir or DEFAULT_PROFILE

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._context = self._run(self._setup())

    def _run(self, coro, timeout: float = 90.0):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _setup(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        context = await self._pw.firefox.launch_persistent_context(
            user_data_dir=self._profile_dir,
            headless=self.headless,
            timeout=60_000,
            firefox_user_prefs={
                "dom.webdriver.enabled": False,
            },
        )
        # Hide the webdriver flag before every page load
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true})"
        )
        self._page = context.pages[0] if context.pages else await context.new_page()
        # Bring the window to front on macOS so user can see any CF challenge
        import subprocess
        subprocess.run(
            ["osascript", "-e", 'tell application "Nightly" to activate'],
            capture_output=True,
        )
        return context

    async def _async_fetch(self, url: str, strip_comments: bool) -> BeautifulSoup:
        await self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        # Wait for Cloudflare to pass (auto or manual checkbox)
        deadline = asyncio.get_event_loop().time() + 120
        prompted = False
        while asyncio.get_event_loop().time() < deadline:
            title = await self._page.title()
            if "just a moment" not in title.lower():
                break
            if not prompted:
                import subprocess
                subprocess.run(
                    ["osascript", "-e", 'tell application "Nightly" to activate'],
                    capture_output=True,
                )
                print("\n[CF CHALLENGE] Firefox opened and brought to front.")
                print("  Click the 'Verify you are human' checkbox.")
                print("  The checkbox should pass now — webdriver flag is hidden.\n")
                prompted = True
            await asyncio.sleep(2)
        if self.page_load_wait > 0:
            await asyncio.sleep(self.page_load_wait)
        content = await self._page.content()
        if strip_comments:
            content = content.replace("<!--", "").replace("-->", "")
        return BeautifulSoup(content, "html.parser")

    async def _async_close(self):
        await self._context.close()
        await self._pw.stop()

    def fetch(self, url: str, strip_comments: bool = False) -> BeautifulSoup:
        return self._run(self._async_fetch(url, strip_comments), timeout=90.0)

    def fetch_and_sleep(self, url: str, strip_comments: bool = False) -> BeautifulSoup:
        soup = self.fetch(url, strip_comments)
        time.sleep(random.uniform(self.sleep_min, self.sleep_max))
        return soup

    def close(self):
        try:
            self._run(self._async_close(), timeout=15)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def refresh_cookies(self, browser: str = "firefox") -> None:
        pass  # cookies live in the persistent profile; no action needed
