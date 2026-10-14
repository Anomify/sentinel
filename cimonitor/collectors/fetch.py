"""Page fetching: Playwright (JS-rendered) when available, plain HTTP otherwise."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


@dataclass
class Fetched:
    url: str
    status: int
    html: str
    error: str | None = None


def _playwright_ok() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


class Fetcher:
    """Context manager so one browser is reused across a whole run."""

    def __init__(self, settings: dict):
        f = settings.get("fetch", {})
        self.timeout = f.get("timeout_s", 30)
        self.ua = f.get("user_agent", "Mozilla/5.0")
        mode = f.get("renderer", "auto")
        self.use_browser = mode == "playwright" or (mode == "auto" and _playwright_ok())
        self._pw = self._browser = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.ua, "Accept-Language": "en-US,en;q=0.9"})

    def __enter__(self):
        if self.use_browser:
            try:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch()
            except Exception as e:
                log.warning("Playwright unavailable (%s) — falling back to HTTP", e)
                self.use_browser = False
        return self

    def __exit__(self, *a):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def get(self, url: str, render: bool = True) -> Fetched:
        if render and self.use_browser:
            try:
                ctx = self._browser.new_context(user_agent=self.ua, viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                html, status = page.content(), resp.status if resp else 0
                ctx.close()
                return Fetched(url, status, html)
            except Exception as e:
                log.info("browser fetch failed for %s: %s — retrying over HTTP", url, e)
        try:
            r = self.session.get(url, timeout=self.timeout)
            return Fetched(url, r.status_code, r.text, None if r.ok else f"HTTP {r.status_code}")
        except requests.RequestException as e:
            return Fetched(url, 0, "", str(e))
