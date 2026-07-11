"""
nodriver-based scraper for Pro Football Reference.

nodriver uses Chrome with all automation markers removed — passes Cloudflare
Turnstile without any manual checkbox interaction.

Requires: pip install nodriver
"""

from __future__ import annotations

import asyncio
import random
import threading
import time

from bs4 import BeautifulSoup


class NoDriverScraper:
    """
    Synchronous scraper backed by Chrome via nodriver (CF-transparent).

    Same fetch / fetch_and_sleep interface as FirefoxScraper.

    Args:
        sleep_min: Minimum seconds between requests (default 4.0)
        sleep_max: Maximum seconds between requests (default 7.0)
        headless: Run headlessly (default False — visible helps CF pass)
        page_load_wait: Extra seconds after page loads (default 3.0)
    """

    def __init__(
        self,
        sleep_min: float = 4.0,
        sleep_max: float = 7.0,
        headless: bool = False,
        page_load_wait: float = 3.0,
    ):
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self.headless = headless
        self.page_load_wait = page_load_wait

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._browser = self._run(self._setup())

    def _run(self, coro, timeout: float = 90.0):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _setup(self):
        import nodriver as uc
        browser = await uc.start(
            headless=self.headless,
            browser_executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            no_sandbox=True,
        )
        self._page = await browser.get("about:blank")
        return browser

    async def _async_fetch(self, url: str, strip_comments: bool) -> BeautifulSoup:
        await self._page.get(url)
        # Wait for CF to clear (nodriver handles it automatically, but give it time)
        await asyncio.sleep(self.page_load_wait)
        # If CF spinner still present, wait longer
        for _ in range(10):
            title = await self._page.evaluate("document.title")
            if "just a moment" not in str(title).lower():
                break
            await asyncio.sleep(2)
        content = await self._page.get_content()
        if strip_comments:
            content = content.replace("<!--", "").replace("-->", "")
        return BeautifulSoup(content, "html.parser")

    async def _async_close(self):
        self._browser.stop()

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

    def refresh_cookies(self, browser: str = "chrome") -> None:
        pass
