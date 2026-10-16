"""Product intelligence: new products, features and releases.

  • Product catalogue: product / platform / solution / feature pages from the production sitemap and the
    homepage navigation. A new one is usually a new product or a newly packaged capability.
  • Release notes: changelog / "what's new" / release-notes pages linked from their own site; each new
    entry (heading) is a shipped feature.
  • Launch announcements: their own blog posts and relevant press coverage whose headline announces a
    launch ("introduces", "now generally available", "new feature"...).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .. import db, facts, guard
from ..config import Config, Entity
from ..facts import Fact, Rule, ev
from . import money, radar

log = logging.getLogger(__name__)
MODULE = "product"

PRODUCT_PATH = re.compile(r"^/(products?|platform|solutions?|features?|capabilities|modules?|integrations?|use-cases?|offerings?)/[^/]+", re.I)
SKIP_PATH = re.compile(r"/(blog|news|press|resources?|events?|webinars?|case-stud(y|ies)|careers|legal|privacy|terms|tag|category|author)(/|$)", re.I)
CHANGELOG_PATH = re.compile(r"/(changelog|change-log|release-notes?|releases|whats-new|what-s-new|product-updates?|updates)/?$", re.I)
LAUNCH_RX = re.compile(r"\b(launch(es|ed|ing)?|introduc(es|ed|ing)|unveil(s|ed)?|debut(s|ed)?|announc(es|ed|ing)\b.{0,40}\b(new|general availability|availability|release)|"
                       r"now (generally )?available|general availability|generally available|\bGA\b|new feature|releases?\b.{0,30}\b(new|version|v\d)|"
                       r"rolls? out|expands?\b.{0,30}\b(platform|product|capabilit)|adds? support for|beta|preview)\b", re.I)
HEADING_JUNK = re.compile(r"^(changelog|release notes?|what'?s new|updates?|subscribe|newsletter|filter|categories|related|share|menu|"
                          r"latest|archive|previous|next|search|contact|resources|product|company|legal)$", re.I)


ACRONYMS = re.compile(r"\b(Ai|Mcp|Llm|Llms|Api|Sdk|Spm|Dlp|Soc|Siem|Ml|Gpu|Saas|Iam|Rag)\b")
FUNDING_HEADLINE = re.compile(r"\b(raises?|raised|funding|series [a-f]|valuation|investment|acquir\w*)\b", re.I)


def _title(path: str) -> str:
    slug = path.rstrip("/").split("/")[-1]
    t = re.sub(r"[-_]+", " ", slug).strip().title() or path
    return ACRONYMS.sub(lambda m: m.group(1).upper().replace("LLMS", "LLMs"), t)


def is_launch(comp: Entity, title: str) -> bool:
    """The company itself announces something new: name first, then a launch verb; funding news is not a launch."""
    if FUNDING_HEADLINE.search(title):
        return False
    name, verb = comp.mention_regex().search(title), LAUNCH_RX.search(title)
    return bool(name and verb and name.start() < verb.start())


# Audience pages (by role or industry) are positioning, not products.
AUDIENCE = re.compile(r"/(ciso|cto|cio|leaders?|developers?|application-developers|ai-leaders|security-teams?|executives?|"
                      r"financial|finance|banking|insurance|government|public-sector|federal|healthcare|health|life-sciences|"
                      r"technology|retail|manufacturing|energy|telecom\w*|education|media|[\w-]*-services|by-(role|industry))[\w-]*/?$", re.I)


def catalogue(comp: Entity, links: list[str]) -> dict[str, str]:
    """{path: label} of product-type pages on their own domain."""
    own = comp.domain.removeprefix("www.")
    base = f"https://{comp.domain}" if comp.domain.startswith("www.") else f"https://www.{comp.domain}"
    paths = radar._sitemap(base) or radar._sitemap(f"https://{comp.domain}")
    paths |= {urlparse(u).path.rstrip("/") for u in links if (urlparse(u).hostname or "").endswith(own)}
    return {p: _title(p) for p in sorted(paths) if PRODUCT_PATH.match(p) and not SKIP_PATH.search(p) and not AUDIENCE.search(p) and p.count("/") <= 3}


def changelog_urls(comp: Entity, links: list[str]) -> list[str]:
    own = comp.domain.removeprefix("www.")
    out = [u.split("#")[0].rstrip("/") for u in links
           if (urlparse(u).hostname or "").endswith(own) and CHANGELOG_PATH.search(urlparse(u).path)]
    return list(dict.fromkeys(out + list(getattr(comp, "changelog", []) or [])))[:3]


def release_entries(url: str, limit: int = 40) -> list[str]:
    try:
        r = guard.get(url)
    except Exception:
        return []
    if not r.ok:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["nav", "header", "footer", "script", "style"]):
        t.decompose()
    out = []
    for h in soup.find_all(["h2", "h3"]):
        t = " ".join(h.get_text(" ", strip=True).split())
        if 4 <= len(t) <= 120 and not HEADING_JUNK.match(t) and t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def launch_items(con, comp: Entity, news: list[dict]) -> list[dict]:
    posts = db.rows(con.execute("SELECT title, url, published, first_seen FROM posts WHERE competitor=? ORDER BY first_seen DESC LIMIT 200",
                                (comp.id,)))
    out = [{"title": p["title"], "url": p["url"], "published": p["published"] or p["first_seen"], "source": "their blog"}
           for p in posts if p["title"] and LAUNCH_RX.search(p["title"]) and not FUNDING_HEADLINE.search(p["title"])]
    for n in news:
        src = n["source"] or "press"
        title = re.sub(rf"\s+-\s+{re.escape(src)}$", "", n["title"]) if n["source"] else n["title"]
        if is_launch(comp, title):
            out.append({"title": title, "url": n["url"], "published": n["published"], "source": src})
    return out


RULES = {
    "product_page": Rule(severity="high", on_remove=True,
                         title_add=lambda f: f"New product page: {f.label}",
                         title_remove=lambda r: f"Product page removed: {r['label']}",
                         so_what=lambda f: "A new product, platform or solution page usually means a new product or a newly packaged capability. Check how it is positioned and priced."),
    "release": Rule(severity="medium", on_remove=False,
                    title_add=lambda f: f"Shipped: {f.label}",
                    so_what=lambda f: "A new entry in their release notes: a feature that is live now. Compare it with our roadmap."),
    "launch": Rule(severity="high", on_remove=False,
                   title_add=lambda f: f"Launch announced: {f.label}",
                   so_what=lambda f: "A public launch announcement. Expect sales and marketing to push it; prepare a response for deals in flight."),
}


def run_one(con, comp: Entity) -> dict:
    if not comp.domain:
        return {"skipped": "no domain"}
    links, _ = money._home_links(comp)
    obs: list[Fact] = []
    cat = catalogue(comp, links)
    base = f"https://{comp.domain}"
    for p, label in cat.items():
        obs.append(Fact("product_page", p, label, {"url": urljoin(base, p)}, facts.CONFIRMED, [ev(urljoin(base, p), "sitemap / site navigation")]))
    logs = changelog_urls(comp, links)
    n_rel = 0
    for u in logs:
        for t in release_entries(u):
            n_rel += 1
            obs.append(Fact("release", f"{u}#{t.lower()}"[:300], t, {"page": u}, facts.CONFIRMED, [ev(u, "release notes / changelog")]))
    try:
        news = money.news(comp)
    except Exception as e:
        log.info("news failed for %s: %s", comp.id, e)
        news = []
    launches = launch_items(con, comp, news)
    for it in launches:
        obs.append(Fact("launch", it["url"][:300], it["title"][:200], {"source": it["source"], "published": it["published"]},
                        facts.CONFIRMED if it["source"] == "their blog" else facts.LIKELY, [ev(it["url"], it["source"])]))
    stats = facts.sync(con, comp.id, MODULE, obs, ["product_page", "release", "launch"], RULES)
    stats.update(products=len(cat), changelogs=logs, releases=n_rel, launches=len(launches))
    return stats


def run(cfg: Config, only: str | None = None) -> dict:
    out = {}
    for comp in cfg.competitors:
        if only and comp.id != only:
            continue
        try:
            with db.connect() as con:
                out[comp.id] = run_one(con, comp)
        except Exception as e:
            log.exception("product failed for %s", comp.id)
            out[comp.id] = {"error": str(e)[:200]}
        log.info("product %-20s %s", comp.id, out[comp.id])
    return out
