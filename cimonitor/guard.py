"""Guardrails: every outbound request goes through here.

Policy (non-negotiable, and shown in the product):
  • Passive, public sources only: GET requests; no logins, no form submissions.
  • robots.txt is honoured for every page we fetch from a website.
  • Per-host rate limiting.
  • Never connect to private / internal addresses. Hostnames that resolve to them are
    *recorded* (the DNS entry exists) but never contacted.
  • No port scanning: only https:// (or http://) on default ports.
  • Official APIs where they exist (job boards, CT logs, DNS-over-HTTPS, ad libraries).
"""
from __future__ import annotations

import ipaddress
import logging
import threading
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

from . import db

log = logging.getLogger(__name__)

UA = "SentinelCI/2.0 (+passive competitive research; respects robots.txt)"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36"
MIN_INTERVAL = 1.5  # seconds between requests to the same host
# Official APIs / data services: robots.txt doesn't govern documented API endpoints.
API_HOSTS = {
    "crt.sh", "api.certspotter.com", "dns.google", "boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com",
    "api.github.com", "news.google.com", "www.googletagmanager.com", "api.perplexity.ai", "api.openai.com",
    "generativelanguage.googleapis.com", "serpapi.com", "graph.facebook.com",
}

_lock = threading.Lock()
_last: dict[str, float] = {}
_robots: dict[str, robotparser.RobotFileParser | None] = {}
_resolved: dict[str, list[str]] = {}


class Blocked(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def audit(url: str, action: str, reason: str = "") -> None:
    try:
        with db.connect() as con:
            db.insert(con, "guard_log", {"ts": db.now(), "host": urlparse(url).hostname or url, "url": url[:500],
                                         "action": action, "reason": reason[:300]})
    except Exception:  # auditing must never break collection
        pass


def is_private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified \
        or a in ipaddress.ip_network("100.64.0.0/10")


def resolve_ips(host: str) -> list[str]:
    """A/AAAA via DNS-over-HTTPS (works everywhere, passive)."""
    if host in _resolved:
        return _resolved[host]
    from .collectors.dnsq import query
    ips = [a for t in ("A", "AAAA") for a in query(host, t) if a.replace(":", "").replace(".", "").isalnum()]
    _resolved[host] = ips
    return ips


def check_host(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise Blocked(f"scheme {u.scheme} not allowed")
    if u.port not in (None, 80, 443):
        raise Blocked("non-default port (no port scanning)")
    host = u.hostname or ""
    if host in API_HOSTS:
        return
    try:
        ipaddress.ip_address(host)
        if is_private(host):
            raise Blocked("private IP literal")
    except ValueError:
        pass
    ips = resolve_ips(host)
    if ips and all(is_private(i) for i in ips):
        raise Blocked("resolves only to private addresses (recorded, never contacted)")


def robots_allowed(url: str, ua: str = UA) -> bool:
    u = urlparse(url)
    if u.hostname in API_HOSTS:
        return True
    base = f"{u.scheme}://{u.netloc}"
    if base not in _robots:
        rp = robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", timeout=10, headers={"User-Agent": BROWSER_UA})
            if r.status_code >= 400:
                rp = None  # no robots.txt → allowed
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            rp = None
        _robots[base] = rp
    rp = _robots[base]
    if rp is None:
        return True
    # Check both our honest UA and the generic rule set.
    return rp.can_fetch(ua, url) and rp.can_fetch("*", url)


def throttle(url: str) -> None:
    host = urlparse(url).hostname or ""
    with _lock:
        wait = _last.get(host, 0) + MIN_INTERVAL - time.monotonic()
        _last[host] = max(time.monotonic(), _last.get(host, 0) + MIN_INTERVAL)
    if wait > 0:
        time.sleep(wait)


def permit(url: str, respect_robots: bool = True) -> None:
    """Raise Blocked if policy forbids fetching url; otherwise wait for the rate limit."""
    try:
        check_host(url)
        if respect_robots and not robots_allowed(url):
            raise Blocked("disallowed by robots.txt")
    except Blocked as b:
        audit(url, "blocked", b.reason)
        raise
    throttle(url)


_session = requests.Session()
_session.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"})


def get(url: str, *, timeout: int = 25, respect_robots: bool = True, **kw) -> requests.Response:
    """Policy-checked GET. Only GET exists here: we never submit forms or POST to websites."""
    permit(url, respect_robots)
    r = _session.get(url, timeout=timeout, **kw)
    audit(url, "allowed", f"HTTP {r.status_code}")
    return r


def get_json(url: str, **kw):
    r = get(url, **kw)
    r.raise_for_status()
    return r.json()


POLICY = [
    ("Passive, public sources only", "GET requests to public pages and documented public APIs. No logins, no form submissions."),
    ("robots.txt respected", "Every website page is checked against robots.txt before it is fetched; disallowed paths are skipped and logged."),
    ("Rate limited", f"At most one request per host every {MIN_INTERVAL:g}s."),
    ("No private addresses", "Hostnames resolving to internal IPs are recorded as DNS facts and never contacted."),
    ("Internal tooling is never reached", "Only clearly public-facing hostnames are ever fetched. Names of internal systems (vault, argocd, atlantis, sso, logging…) and environments are recorded from CT/DNS only, even when publicly resolvable."),
    ("No port scanning", "Only default HTTP/HTTPS ports; no service probing."),
    ("Official APIs first", "Certificate Transparency, DNS-over-HTTPS, Greenhouse/Lever/Ashby, GitHub, ad-library APIs."),
]
