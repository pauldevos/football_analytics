"""
Base scraper for Pro Football Reference.

Handles rate limiting, user-agent rotation, and common HTML table extraction.

Cloudflare bot protection strategy
------------------------------------
The site uses Cloudflare Managed Challenge, which scores requests on:
  - TLS / JA3/JA4 fingerprint  ("requests" is instantly flagged)
  - HTTP/2 header ordering and pseudo-header presence
  - Active JavaScript challenge requiring real browser runtime
  - Cookie continuity (cf_clearance / __cf_bm bound to session + IP)

This scraper bypasses the first two layers by using ``curl_cffi``, which
compiles against Chrome's BoringSSL and can impersonate real browser TLS
handshakes exactly.  The JS challenge layer is bypassed by injecting the
``cf_clearance`` cookie that your real Brave/Chrome browser already earned.

Workflow:
  1. Open https://www.pro-football-reference.com in Brave (or Chrome) once.
     Cloudflare will issue a cf_clearance cookie to your browser.
  2. Run your scraping job.  PFRefScraper will read that cookie automatically
     via browser_cookie3 and attach it to every request.
  3. cf_clearance typically lasts 30 min–1 hour.  If you start getting 403s
     again, just reload the site in your browser and re-run.

User-agent strings are loaded from pfref/config/user_agent_strings.csv
or the legacy location (~/.data/config/user_agent_strings.csv).
"""

import pathlib
import random
import time
import warnings

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as _cf_requests
    from curl_cffi.requests import Session as _CfSession
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    import requests as _cf_requests  # type: ignore[no-redef]
    _CURL_CFFI_AVAILABLE = False
    warnings.warn(
        "curl_cffi not installed – falling back to requests (likely to hit Cloudflare blocks). "
        "Install with: pip install curl_cffi",
        stacklevel=2,
    )

try:
    import browser_cookie3 as _bc3
    _BROWSER_COOKIE3_AVAILABLE = True
except ImportError:
    _bc3 = None  # type: ignore[assignment]
    _BROWSER_COOKIE3_AVAILABLE = False

BASE_URL = "https://www.pro-football-reference.com"

# Bundled config within the package directory
_BUNDLED_CONFIG = pathlib.Path(__file__).parent / "config" / "user_agent_strings.csv"
# Legacy location used by older notebooks
_LEGACY_CONFIG = pathlib.Path.home() / "data" / "config" / "user_agent_strings.csv"


class PFRefScraper:
    """
    Base scraper with rate limiting, user-agent rotation, and Cloudflare bypass.

    Uses curl_cffi to impersonate a real Chrome TLS fingerprint and loads the
    cf_clearance cookie automatically from your Brave or Chrome browser via
    browser_cookie3.  Visit the site once in your browser before running a
    scrape job so Cloudflare issues a fresh cf_clearance cookie.

    Args:
        sleep_min: Minimum seconds to sleep between requests (default 4.0)
        sleep_max: Maximum seconds to sleep between requests (default 7.0)
        config_path: Optional path to user_agent_strings.csv
        timeout: Per-request timeout in seconds (default 30)
        extra_headers: Optional additional HTTP headers merged into every request
        impersonate: curl_cffi browser profile to impersonate (default 'chrome136')
        browser: Browser to load cf_clearance cookies from.
                 One of 'brave', 'chrome', 'chromium', 'edge', or None to disable.
    """

    # UA matching the Brave/Chrome profile used when cf_clearance was earned
    _DEFAULT_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        sleep_min: float = 4.0,
        sleep_max: float = 7.0,
        config_path: pathlib.Path | None = None,
        timeout: int = 30,
        extra_headers: dict[str, str] | None = None,
        impersonate: str = "chrome136",
        browser: str | None = "brave",
    ):
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self.timeout = timeout
        self.impersonate = impersonate
        self.extra_headers = extra_headers or {}
        self._user_agents = self._load_user_agents(config_path)
        self._browser_cookies = self._load_browser_cookies(browser)

        if _CURL_CFFI_AVAILABLE:
            self._session = _CfSession(impersonate=impersonate)
        else:
            import requests as _requests
            self._session = _requests.Session()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _load_user_agents(self, config_path: pathlib.Path | None) -> list[str]:
        candidates = [p for p in [config_path, _LEGACY_CONFIG, _BUNDLED_CONFIG] if p]
        for path in candidates:
            if path and path.exists():
                agents = [line.strip() for line in path.read_text().splitlines() if line.strip()]
                if agents:
                    return agents
        return [self._DEFAULT_UA]

    def _load_browser_cookies(self, browser: str | None) -> dict[str, str]:
        """Load cf_clearance and companion cookies from the specified browser."""
        if not browser or not _BROWSER_COOKIE3_AVAILABLE:
            return {}
        loaders = {
            "brave": _bc3.brave,
            "chrome": _bc3.chrome,
            "chromium": _bc3.chromium,
            "edge": _bc3.edge,
        }
        loader = loaders.get(browser.lower())
        if loader is None:
            warnings.warn(f"Unknown browser '{browser}'. Supported: {list(loaders)}", stacklevel=3)
            return {}
        try:
            cj = loader(domain_name=".pro-football-reference.com")
            cookies = {c.name: c.value for c in cj}
            if "cf_clearance" not in cookies:
                warnings.warn(
                    "No cf_clearance cookie found in your browser for pro-football-reference.com. "
                    "Open https://www.pro-football-reference.com in Brave/Chrome, wait for the page "
                    "to load fully, then re-run. Scraping without it will likely be blocked.",
                    stacklevel=3,
                )
            return cookies
        except Exception as exc:
            warnings.warn(f"Could not load browser cookies ({exc}). Continuing without them.", stacklevel=3)
            return {}

    def refresh_cookies(self, browser: str = "brave") -> None:
        """Reload browser cookies mid-session (call this if you start getting 403s again)."""
        self._browser_cookies = self._load_browser_cookies(browser)

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    def _random_agent(self) -> str:
        return random.choice(self._user_agents)

    def _build_headers(self, user_agent: str) -> dict[str, str]:
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
            "Sec-GPC": "1",
            "Connection": "keep-alive",
        }
        headers.update(self.extra_headers)
        return headers

    @staticmethod
    def _is_cf_challenge(response) -> bool:
        server = response.headers.get("server", "").lower()
        has_cf_header = any(k.lower().startswith("cf-") for k in response.headers)
        text = response.text.lower()
        markers = ("verify you are human", "just a moment", "challenge-platform", "cf-chl", "cloudflare")
        return ("cloudflare" in server or has_cf_header) and any(m in text for m in markers)

    def _sleep(self) -> None:
        time.sleep(random.uniform(self.sleep_min, self.sleep_max))

    def fetch(self, url: str, strip_comments: bool = False) -> BeautifulSoup:
        """Fetch a URL and return a BeautifulSoup object. Does NOT sleep."""
        # Use the Brave UA when we have cf_clearance so the fingerprint matches
        ua = self._DEFAULT_UA if self._browser_cookies.get("cf_clearance") else self._random_agent()
        headers = self._build_headers(ua)

        if _CURL_CFFI_AVAILABLE:
            response = self._session.get(
                url,
                headers=headers,
                cookies=self._browser_cookies,
                timeout=self.timeout,
            )
        else:
            response = self._session.get(
                url,
                headers=headers,
                cookies=self._browser_cookies,
                timeout=self.timeout,
            )

        if response.status_code == 403 and self._is_cf_challenge(response):
            raise PermissionError(
                "Request blocked by Cloudflare challenge.\n"
                "  → Open https://www.pro-football-reference.com in Brave/Chrome, "
                "let it load fully, then call scraper.refresh_cookies() and retry."
            )

        response.raise_for_status()
        text = response.text
        if strip_comments:
            text = text.replace("<!--", "").replace("-->", "")
        return BeautifulSoup(text, "html.parser")

    def fetch_and_sleep(self, url: str, strip_comments: bool = False) -> BeautifulSoup:
        """Fetch a URL, then sleep the configured delay. Use this in loops."""
        soup = self.fetch(url, strip_comments)
        self._sleep()
        return soup

    # ------------------------------------------------------------------
    # Table extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_table_headers(
        soup: BeautifulSoup,
        table_id: str,
        header_row_index: int = 1,
    ) -> list[str]:
        """
        Extract and normalize column headers from a PFRef HTML table.

        Args:
            soup: Parsed page
            table_id: The HTML id attribute of the target <table>
            header_row_index: Which <tr> in <thead> to use (0 = first, 1 = second)
        """
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
        """
        Extract all data rows from a PFRef HTML table body.

        Args:
            soup: Parsed page
            table_id: The HTML id attribute of the target <table>
            skip_label: Skip rows where column index 1 equals this value (e.g. totals rows)
        """
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
        """
        Extract player page hrefs from each row of a table.
        Returns one href per row (empty string if no player link in that row).
        """
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
