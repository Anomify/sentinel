"""Module 1, GTM stack fingerprinting.

Loads key pages in headless Chromium, records every request/script/cookie before and
after cookie consent, matches the tool-signature library, and infers the go-to-market
motion (sales-led vs product-led) from the stack plus the site's conversion paths.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .. import db, facts
from ..config import Config, Entity
from ..facts import Fact, Rule, ev
from ..signatures import BY_ID, CATEGORIES, detect
from .fetch import Capture, Fetcher

log = logging.getLogger(__name__)
MODULE = "stack"

CONVERSION_RX = {
    "demo": r"\b(book|request|get|schedule|see)\s+(a\s+)?(live\s+)?demo\b",
    "contact_sales": r"\b(contact|talk to|speak (to|with))\s+(sales|an expert|us)\b",
    "free_trial": r"\b(free trial|start (your )?(free )?trial|try (it )?(for )?free|try free)\b",
    "signup": r"\b(sign up|get started( free)?|start (for )?free|create (an )?account)\b",
    "open_source": r"\b(github|open[- ]source|pip install|npm install)\b",
    "login": r"\b(log ?in|sign ?in)\b",
}
# A bare "Demo" button is ambiguous: a booking form is a sales step, a live/interactive demo is self-serve.
BARE_DEMO = re.compile(r"^(live |interactive |product |try (the |a )?)?demo$", re.I)
DEMO_FORM_HREF = re.compile(r"(book|request|schedule|get)[-_]?(a[-_])?demo|demo[-_]?request|/contact|/talk|calendly|chilipiper|hubspot\.com/meetings", re.I)
CONV_LABEL = {"product_demo": "Self-serve product demo", "demo": "Book a demo", "contact_sales": "Contact sales", "free_trial": "Free trial", "signup": "Self-serve sign-up",
              "open_source": "Open source / GitHub", "login": "Product login", "pricing_public": "Public pricing"}
KEY_PAGE_RX = re.compile(r"/(pricing|plans|demo|book-a-demo|request-a-demo|contact|contact-sales|get-started|signup|sign-up|trial|start)(/|$)", re.I)


def key_pages(comp: Entity, home: Capture) -> list[str]:
    urls = []
    for p in comp.pages:
        if p.kind == "pricing" and urlparse(p.url).hostname and any(urlparse(p.url).hostname.endswith(d) for d in comp.domains):
            urls.append(p.url)
    if home.html:
        soup = BeautifulSoup(home.html, "html.parser")
        for a in soup.find_all("a", href=True):
            u = urljoin(home.url, a["href"].split("#")[0])
            h = urlparse(u).hostname or ""
            if any(h == d or h.endswith("." + d) for d in comp.domains) and KEY_PAGE_RX.search(urlparse(u).path):
                urls.append(u)
    seen, out = set(), []
    for u in urls:
        k = urlparse(u)._replace(query="", fragment="").geturl().rstrip("/")
        if k not in seen and k.rstrip("/") != home.url.rstrip("/"):
            seen.add(k)
            out.append(u)
    # prefer a demo page and a pricing page
    out.sort(key=lambda u: (0 if re.search("demo", u) else 1 if re.search("pric|plan", u) else 2))
    return out[:2]


def conversion_paths(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    links = []
    for a in soup.find_all(["a", "button"]):
        t = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        if 2 <= len(t) <= 40:
            links.append((t, a.get("href") or ""))
    found = {}
    for k, rx in CONVERSION_RX.items():
        m = next((t for t, _ in links if re.search(rx, t, re.I)), None)
        if m:
            found[k] = m
    for t, href in links:
        if BARE_DEMO.match(t):
            found.setdefault("demo" if DEMO_FORM_HREF.search(href) else "product_demo", t)
    if re.search(r"[$€£]\s?\d", soup.get_text(" ")) and re.search(r"/(mo|month|year|yr|user|seat)", soup.get_text(" "), re.I):
        found["pricing_public"] = "prices shown"
    return found


def classify_motion(tools: set[str], conv: dict[str, str]) -> dict:
    """Score: positive = sales-led, negative = product-led. Every point is explained."""
    score, reasons = 0.0, []
    sales = [BY_ID[t].name for t in tools if t in BY_ID and BY_ID[t].motion == "sales"]
    prod = [BY_ID[t].name for t in tools if t in BY_ID and BY_ID[t].motion == "product"]
    if sales:
        score += min(4, len(sales)) * 1.0
        reasons.append(f"Sales-motion tooling: {', '.join(sorted(sales)[:6])}")
    if prod:
        score -= min(4, len(prod)) * 1.0
        reasons.append(f"Product-led tooling: {', '.join(sorted(prod)[:6])}")
    if "demo" in conv or "contact_sales" in conv:
        score += 2
        reasons.append(f"Primary CTA routes to sales (“{conv.get('demo') or conv.get('contact_sales')}”)")
    if "product_demo" in conv and "demo" not in conv:
        score -= 1
        reasons.append(f"Public product demo, no booking form (“{conv['product_demo']}”)")
    if "free_trial" in conv or "signup" in conv:
        score -= 2.5
        reasons.append(f"Self-serve entry point (“{conv.get('free_trial') or conv.get('signup')}”)")
    else:
        score += 1
        reasons.append("No self-serve sign-up or free trial on key pages")
    if "pricing_public" in conv:
        score -= 1
        reasons.append("Prices are published")
    if "open_source" in conv:
        score -= 0.5
        reasons.append("Open-source / developer entry point")
    label = "Sales-led" if score >= 2 else "Product-led" if score <= -2 else "Hybrid"
    return {"label": label, "score": round(score, 1), "reasons": reasons}


# What adding a tool of each kind says about the company, as a sentence: "{who} {verb}".
TOOL_VERB = {
    "ads": "added the {name} tag to their site", "abm": "started using {name} to spot which companies visit their site",
    "map": "started using {name} for marketing automation", "analytics": "added {name} (web analytics)",
    "product": "added {name} (product analytics)", "replay": "started recording visitor sessions with {name}",
    "chat": "added {name} live chat to their site", "scheduling": "now lets visitors book a meeting straight from the site ({name})",
    "demo": "added interactive product demos ({name})", "testing": "started A/B testing their site ({name})",
    "consent": "added a {name} cookie banner", "cms": "now runs their site on {name}", "video": "added {name} video",
    "support": "added {name} for support and docs", "tag": "added {name} (tag management)",
    "partner": "started running a partner or referral programme ({name})", "events": "started running events or webinars with {name}",
    "reviews": "added {name} reviews to their site", "calltracking": "started tracking calls from their marketing ({name})",
    "monitoring": "added {name} (site monitoring)", "payments": "now takes payments on their site ({name})",
    "hiring": "added {name} to their careers pages",
}
# Buying online is a real change in how they sell; ad tags are the ads module's call (it checks the ad libraries).
TOOL_SEV = {"payments": "high", "abm": "medium", "partner": "medium", "scheduling": "medium", "demo": "medium", "map": "medium",
            "chat": "medium", "testing": "medium", "events": "medium", "calltracking": "medium", "product": "medium"}
TOOL_RULE = Rule(
    severity="low",
    severity_fn=lambda f: TOOL_SEV.get(f.value.get("category"), "low"),
    title_add=lambda f: "{who} " + TOOL_VERB.get(f.value.get("category"), "added {name} to their site").format(name=f.label),
    title_remove=lambda r: f"{{who}} stopped using {r['label']}",
    so_what=lambda f: BY_ID[f.key].means if f.key in BY_ID else None,
)
RULES = {
    "tool": TOOL_RULE,
    "conversion_path": Rule(severity="medium",
                            # A free trial, self-serve sign-up or public prices is a shift towards selling without a salesperson.
                            severity_fn=lambda f: "high" if f.key in ("free_trial", "signup", "pricing_public") else "medium",
                            title_add=lambda f: f"{{who}} added a new way to get started: {f.label}",
                            title_remove=lambda r: f"{{who}} no longer offers: {r['label']}",
                            so_what=lambda f: "A shift towards letting buyers start without talking to sales." if f.key in ("free_trial", "signup", "pricing_public") else None),
    # Only a change of label is news; the score behind it moves with every tool added or removed.
    "motion": Rule(severity="high", on_add=False, on_remove=False, on_change=True,
                   alert_change=lambda cur, f: (cur.get("value") or {}).get("label") != f.value.get("label"),
                   title_change=lambda cur, f: f"{{who}}'s sales approach changed: {(cur.get('value') or {}).get('label', '?')} → {f.label}"),
    "third_party": Rule(on_add=False, on_remove=False),
}


def analyse(comp: Entity, caps: list[Capture]) -> list[Fact]:
    out: list[Fact] = []
    tools: dict[str, dict] = {}
    cmp_present = False
    for cap in caps:
        if cap.error and not cap.html:
            continue
        pre = detect(cap.requests, {urlparse(u).hostname or "" for u in cap.requests}, cap.cookies_pre, cap.html)
        allreq = cap.requests + cap.requests_post
        post = detect(allreq, {urlparse(u).hostname or "" for u in allreq}, cap.cookies_post, cap.html)
        for sid, hits in post.items():
            t = tools.setdefault(sid, {"phases": set(), "pages": set(), "hits": [], "shot": cap.screenshot, "url": cap.url})
            t["phases"].add("pre-consent" if sid in pre else "post-consent")
            t["pages"].add(cap.url)
            t["hits"] += hits
        cmp_present |= any(BY_ID[s].cat == "consent" for s in post)
    for sid, t in tools.items():
        s = BY_ID[sid]
        strong = any(not h.startswith(("html:", "cookie:")) for h in t["hits"])
        val = {"category": s.cat, "category_label": CATEGORIES[s.cat], "phases": sorted(t["phases"]),
               "pages": sorted(t["pages"]), "matched": t["hits"][:4], "motion": s.motion}
        if cmp_present and s.cat in ("ads", "abm", "replay") and "pre-consent" in t["phases"]:
            val["fires_before_consent"] = True
        out.append(Fact("tool", sid, s.name, val, facts.CONFIRMED if strong else facts.LIKELY,
                        [ev(t["url"], "headless browser network capture", f"matched {t['hits'][0][:120]}", t["shot"])]))
    hosts = set()
    for cap in caps:
        hosts |= cap.hosts
    own = tuple(comp.domains)
    for h in sorted(hosts):
        if not any(h == d or h.endswith("." + d) for d in own):
            out.append(Fact("third_party", h, h, {}, facts.CONFIRMED, [ev(caps[0].url, "network capture")]))
    conv: dict[str, str] = {}
    for cap in caps:
        for k, v in conversion_paths(cap.html).items():
            conv.setdefault(k, v)
    for k, v in conv.items():
        out.append(Fact("conversion_path", k, CONV_LABEL[k], {"cta": v}, facts.CONFIRMED, [ev(caps[0].url, "CTA extraction", f"“{v}”")]))
    if tools or conv:
        m = classify_motion(set(tools), conv)
        out.append(Fact("motion", "motion", m["label"], m, facts.INFERRED, [ev(caps[0].url, "motion classifier over detected stack + CTAs")]))
    cookies = sorted({c for cap in caps for c in cap.cookies_post})
    out.append(Fact("cookies", "all", f"{len(cookies)} cookies", {"names": cookies,
                    "consent_banner": next((c.consent for c in caps if c.consent), None)}, facts.CONFIRMED,
                    [ev(caps[0].url, "browser cookie jar after consent")]))
    return out


def run_one(con, cfg: Config, fetcher: Fetcher, comp: Entity) -> tuple[dict, list[Capture]]:
    if not comp.domain:
        return {"skipped": "no domain"}, []
    home = fetcher.capture(f"https://{comp.domain}/" if not comp.domain.startswith("www.") else f"https://{comp.domain}/",
                           screenshot_prefix=f"{comp.id}-home")
    if home.error and not home.html and not comp.domain.startswith("www."):
        home = fetcher.capture(f"https://www.{comp.domain}/", screenshot_prefix=f"{comp.id}-home")
    caps = [home]
    for u in key_pages(comp, home):
        caps.append(fetcher.capture(u, screenshot_prefix=f"{comp.id}-key"))
    if all(c.error and not c.html for c in caps):
        return {"error": home.error}, caps
    observed = analyse(comp, caps)
    kinds = ["tool", "third_party", "conversion_path", "motion", "cookies"]
    # A page that failed to load hides whatever only it loads: nothing is "removed" on a partial capture.
    unread = set(kinds) if any(c.error and not c.html for c in caps) else set()
    stats = facts.sync(con, comp.id, MODULE, observed, kinds, RULES, unread=unread)
    stats["pages"] = [c.url for c in caps]
    return stats, caps


def run(cfg: Config, only: str | None = None) -> dict:
    """Runs Module 1 and hands the captures to Module 2 (GTM forensics) in the same pass."""
    from . import gtm
    out = {}
    with Fetcher(cfg.settings) as fetcher:
        for comp in cfg.competitors:
            if only and comp.id != only:
                continue
            try:
                with db.connect() as con:
                    stats, caps = run_one(con, cfg, fetcher, comp)
                with db.connect() as con:
                    stats["gtm"] = gtm.run_one(con, cfg, comp, caps)
                out[comp.id] = stats
            except Exception as e:
                log.exception("stack failed for %s", comp.id)
                out[comp.id] = {"error": str(e)[:200]}
            log.info("stack %-20s %s", comp.id, {k: v for k, v in out[comp.id].items() if k != "pages"})
    with db.connect() as con:
        gtm.link_ids(con, cfg)
    return out
