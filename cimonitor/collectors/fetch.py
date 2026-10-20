"""Page loading: headless Chromium (Playwright) behind the guardrails, HTTP fallback.

Also provides the instrumented load used by stack fingerprinting: every request,
script, cookie and response header is recorded, before and after cookie consent.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .. import guard, tenancy

log = logging.getLogger(__name__)

# Consent banners: (selector) for the common CMPs, then text fallbacks. Clicking "accept"
# on a cookie banner is ordinary browsing, not a form submission.
CONSENT_SELECTORS = [
    "#onetrust-accept-btn-handler", "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept", "button[data-cky-tag='accept-button']", ".cky-btn-accept",
    "#hs-eu-confirmation-button", "button#truste-consent-button", "[data-testid='uc-accept-all-button']",
    ".osano-cm-accept-all", "#didomi-notice-agree-button", ".fs-cc-banner_button[fs-cc='allow']",
    "[fs-cc='allow']", "button.iubenda-cs-accept-btn", "#termly-code-snippet-support button[data-tid='banner-accept']",
]
CONSENT_TEXT = re.compile(r"^\s*(accept( all)?( cookies)?|allow( all)?( cookies)?|agree|i agree|got it|ok(ay)?)\s*$", re.I)


def chromium_path() -> str | None:
    for p in (os.environ.get("SENTINEL_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if p and Path(p).exists():
            return p
    return None


def evidence_dir() -> Path:
    d = tenancy.data_dir() / "evidence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_shot(png: bytes, prefix: str) -> str:
    name = f"{prefix}-{hashlib.sha1(png).hexdigest()[:12]}.png"
    (evidence_dir() / name).write_bytes(png)
    return name


@dataclass
class Fetched:
    url: str
    status: int
    html: str
    error: str | None = None
    headers: dict = field(default_factory=dict)
    screenshot: str | None = None
    final_url: str | None = None


@dataclass
class Capture:
    """Instrumented page load for stack fingerprinting."""
    url: str
    html: str = ""
    requests: list[str] = field(default_factory=list)           # every request URL
    requests_post: list[str] = field(default_factory=list)      # requests that started after consent
    cookies_pre: list[str] = field(default_factory=list)
    cookies_post: list[str] = field(default_factory=list)
    headers: dict = field(default_factory=dict)
    consent: str | None = None                                  # which CMP/button we clicked
    screenshot: str | None = None
    error: str | None = None
    status: int = 0

    @property
    def hosts(self) -> set[str]:
        return {urlparse(u).hostname or "" for u in self.requests + self.requests_post} - {""}


def route_guard(route) -> None:
    """Browser request filter: a page's scripts, images, iframes and redirects may not reach private or internal
    addresses. robots.txt governs pages we choose to load, not the resources a page pulls in, so only the host is checked."""
    url = route.request.url
    if url.startswith(("http://", "https://")):
        try:
            guard.check_host(url)
        except guard.Blocked as b:
            guard.audit(url, "blocked", f"browser request: {b.reason}")
            route.abort("blockedbyclient")
            return
    route.continue_()


def _playwright_ok() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


class Fetcher:
    """Context manager so one browser is reused across a whole run."""

    def __init__(self, settings: dict | None = None):
        f = (settings or {}).get("fetch", {})
        self.timeout = f.get("timeout_s", 30)
        mode = f.get("renderer", "auto")
        self.use_browser = mode == "playwright" or (mode == "auto" and _playwright_ok())
        self._pw = self._browser = None

    def __enter__(self):
        if self.use_browser:
            try:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
                kw = {"executable_path": chromium_path()} if chromium_path() else {}
                self._browser = self._pw.chromium.launch(**kw)
            except Exception as e:
                log.warning("Playwright unavailable (%s), falling back to HTTP", e)
                self.use_browser = False
        return self

    def __exit__(self, *a):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def _ctx(self):
        ctx = self._browser.new_context(user_agent=guard.BROWSER_UA, viewport={"width": 1440, "height": 900},
                                        locale="en-US")
        ctx.route("**/*", route_guard)  # every request the page makes, redirects included, is vetted
        return ctx

    def get(self, url: str, render: bool = True, screenshot: str | None = None) -> Fetched:
        """screenshot: filename prefix to save an evidence screenshot (browser only)."""
        try:
            guard.permit(url)
        except guard.Blocked as b:
            return Fetched(url, 0, "", f"blocked: {b.reason}")
        if render and self.use_browser:
            try:
                ctx = self._ctx()
                page = ctx.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                shot = save_shot(page.screenshot(full_page=False), screenshot) if screenshot else None
                f = Fetched(url, resp.status if resp else 0, page.content(), headers=dict(resp.headers) if resp else {},
                            screenshot=shot, final_url=page.url)
                ctx.close()
                guard.audit(url, "allowed", f"browser {f.status}")
                return f
            except Exception as e:
                log.info("browser fetch failed for %s: %s, retrying over HTTP", url, e)
        try:
            r = guard.get(url, timeout=self.timeout)  # checks every redirect hop
            return Fetched(url, r.status_code, r.text, None if r.ok else f"HTTP {r.status_code}", dict(r.headers),
                           final_url=r.url)
        except guard.Blocked as b:
            return Fetched(url, 0, "", f"blocked: {b.reason}")
        except Exception as e:
            return Fetched(url, 0, "", str(e)[:300])

    def capture(self, url: str, screenshot_prefix: str | None = None) -> Capture:
        """Load url, record everything pre-consent, accept the cookie banner, record post-consent."""
        cap = Capture(url)
        try:
            guard.permit(url)
        except guard.Blocked as b:
            cap.error = f"blocked: {b.reason}"
            return cap
        if not self.use_browser:  # degraded mode: HTML only
            f = self.get(url, render=False)
            cap.html, cap.error, cap.status, cap.headers = f.html, f.error, f.status, f.headers
            cap.requests = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)', f.html)
            return cap
        ctx = self._ctx()
        page = ctx.new_page()
        phase = {"post": False}
        page.on("request", lambda r: (cap.requests_post if phase["post"] else cap.requests).append(r.url))
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            cap.status = resp.status if resp else 0
            cap.headers = dict(resp.headers) if resp else {}
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            cap.cookies_pre = sorted({c["name"] for c in ctx.cookies()})
            if screenshot_prefix:
                cap.screenshot = save_shot(page.screenshot(full_page=False), screenshot_prefix)
            phase["post"] = True
            cap.consent = self._accept_consent(page)
            if cap.consent:
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(2500)
            # scroll to trigger lazy tags
            try:
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1200)
            except Exception:
                pass
            cap.cookies_post = sorted({c["name"] for c in ctx.cookies()})
            cap.html = page.content()
            guard.audit(url, "allowed", f"capture {cap.status}; consent={cap.consent or 'none'}")
        except Exception as e:
            cap.error = str(e)[:300]
        finally:
            ctx.close()
        return cap

    @staticmethod
    def _accept_consent(page) -> str | None:
        for sel in CONSENT_SELECTORS:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=2000)
                    return sel
            except Exception:
                continue
        try:
            for el in page.query_selector_all("button, a[role=button], [role=button]")[:200]:
                t = (el.inner_text() or "").strip()
                if t and len(t) < 30 and CONSENT_TEXT.match(t) and el.is_visible():
                    el.click(timeout=2000)
                    return f"text:{t}"
        except Exception:
            pass
        return None


def has_browser() -> bool:
    return _playwright_ok()
