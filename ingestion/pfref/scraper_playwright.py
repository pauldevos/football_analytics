"""
Playwright-based scraper using the real Brave browser.

Drop-in replacement for PFRefScraper when curl_cffi is being blocked by
Cloudflare Managed Challenge.  Launches the actual Brave executable so the
TLS fingerprint and browser identity are genuine — no spoofing needed.

Usage:
    from pfref.scraper_playwright import PlaywrightScraper

    scraper = PlaywrightScraper()
    soup = scraper.fetch_and_sleep("https://www.pro-football-reference.com/...")
    scraper.close()

    # or as a context manager:
    with PlaywrightScraper() as scraper:
        soup = scraper.fetch_and_sleep(url)
"""

import asyncio
import pathlib
import random
import threading
import time

from bs4 import BeautifulSoup

BRAVE_EXE = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
# Persistent profile dir so Cloudflare cookies carry over between runs
DEFAULT_PROFILE = str(pathlib.Path.home() / ".local" / "share" / "pfref_brave_profile")


class PlaywrightScraper:
    """
    Synchronous scraper backed by a real Brave browser running in a
    background asyncio event loop.

    Exposes the same fetch / fetch_and_sleep interface as PFRefScraper so
    it can be passed directly to any scraper function that accepts a scraper.

    Args:
        sleep_min: Minimum seconds between requests (default 4.0)
        sleep_max: Maximum seconds between requests (default 7.0)
        profile_dir: Path to Brave user-data-dir.  Persisting this across
                     runs keeps the cf_clearance cookie alive.
        headless: Run Brave headlessly.  Leave False (default) — Cloudflare
                  blocks headless Chromium even with stealth patches.
        page_load_wait: Extra seconds to wait after domcontentloaded for
                        dynamic content / CF challenges to resolve (default 3).
    """

    def __init__(
        self,
        sleep_min: float = 4.0,
        sleep_max: float = 7.0,
        profile_dir: str | None = None,
        headless: bool = False,
        page_load_wait: float = 3.0,
    ):
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self.headless = headless
        self.page_load_wait = page_load_wait
        self._profile_dir = profile_dir or DEFAULT_PROFILE

        # Spin up a background thread running an asyncio event loop so we
        # can bridge async Playwright calls to a synchronous interface.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

        # Initialize Playwright + browser synchronously before returning
        self._context = self._run(self._setup())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, coro, timeout: float = 60.0):
        """Submit a coroutine to the background loop and block until done."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _setup(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=self._profile_dir,
            executable_path=BRAVE_EXE,
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Reuse the first tab that Brave opens
        self._page = context.pages[0] if context.pages else await context.new_page()
        return context

    async def _async_fetch(self, url: str, strip_comments: bool) -> BeautifulSoup:
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if self.page_load_wait > 0:
            await asyncio.sleep(self.page_load_wait)
        content = await self._page.content()
        if strip_comments:
            content = content.replace("<!--", "").replace("-->", "")
        return BeautifulSoup(content, "html.parser")

    async def _async_close(self):
        await self._context.close()
        await self._pw.stop()

    # ------------------------------------------------------------------
    # Public interface (mirrors PFRefScraper)
    # ------------------------------------------------------------------

    def fetch(self, url: str, strip_comments: bool = False) -> BeautifulSoup:
        """Fetch a URL and return a BeautifulSoup object. Does NOT sleep."""
        return self._run(self._async_fetch(url, strip_comments))

    def fetch_and_sleep(self, url: str, strip_comments: bool = False) -> BeautifulSoup:
        """Fetch a URL, then sleep the configured delay. Use this in loops."""
        soup = self.fetch(url, strip_comments)
        time.sleep(random.uniform(self.sleep_min, self.sleep_max))
        return soup

    def close(self):
        """Shut down the browser and background event loop."""
        try:
            self._run(self._async_close(), timeout=15)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # Table extraction helpers  (identical logic to PFRefScraper)
    # ------------------------------------------------------------------

    @staticmethod
    def extract_table_headers(
        soup: BeautifulSoup,
        table_id: str,
        header_row_index: int = 1,
    ) -> list[str]:
        """Extract and normalize column headers from a PFRef HTML table."""
        table = soup.find("table", {"id": table_id})
        if not table:
            raise ValueError(f"Table '{table_id}' not found on page")
        thead_rows = table.find("thead").find_all("tr")
        row = thead_rows[header_row_index] if len(thead_rows) > header_row_index else thead_rows[0]
        headers = []
        for th in row.find_all("th"):
            h = th.text.strip().lower()
            h = h.replace("%", "pct").replace("/", "_per_").replace(" ", "_")
            headers.append(h)
        return headers

    @staticmethod
    def extract_table_rows(
        soup: BeautifulSoup,
        table_id: str,
        skip_label: str | None = "League Average",
    ) -> list[list[str]]:
        """Extract all data rows from a PFRef HTML table body."""
        table = soup.find("table", {"id": table_id})
        if not table:
            raise ValueError(f"Table '{table_id}' not found on page")
        rows = []
        for tr in table.find("tbody").find_all("tr"):
            row = [td.text.strip() for td in tr.find_all(["th", "td"])]
            if not row:
                continue
            if skip_label and len(row) > 1 and row[1] == skip_label:
                continue
            rows.append(row)
        return rows

    @staticmethod
    def extract_player_links(soup: BeautifulSoup, table_id: str) -> list[str]:
        """Extract player page hrefs from each row of a table (empty string if none)."""
        table = soup.find("table", {"id": table_id})
        if not table:
            return []
        links = []
        for tr in table.find("tbody").find_all("tr"):
            href = ""
            for a in tr.find_all("a"):
                if "players" in a.get("href", ""):
                    href = a["href"].strip()
                    break
            links.append(href)
        return links

    # ------------------------------------------------------------------
    # Pass-through stubs so calling code that checks these attributes doesn't break
    # ------------------------------------------------------------------

    @property
    def sleep_range(self):
        return (self.sleep_min, self.sleep_max)

    def refresh_cookies(self, browser: str = "brave") -> None:
        """No-op: Playwright manages cookies through the live browser session."""
        pass
