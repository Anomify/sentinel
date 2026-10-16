"""Module 5, Pre-launch radar.

  • Public staging sites (configured, discovered from CT, or Webflow's <name>-stg.webflow.io
    convention): pages on staging that aren't on production are pre-launch pages.
  • Production sitemap diffs: new pages as they go live.
  • Webflow "Last Published" stamps → release cadence.
  • Public GitHub org repos: new repos and push cadence.
  • Launch probability: combines recent weak signals into one score (inferred).
"""
from __future__ import annotations

import logging
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .. import db, facts, guard
from ..config import Config, Entity
from ..facts import Fact, Rule, ev

log = logging.getLogger(__name__)
MODULE = "radar"
LP_RX = re.compile(r"Last Published: (.+?)\s*-->")
NOISE_PATH = re.compile(r"/(blog|insight|insights|research|news|press|resources?|events?|webinars?|podcasts?|glossary|"
                        r"case-stud(y|ies)|careers|jobs|tag|tags|category|author|authors|legal|privacy|terms|cookie)(/|$)", re.I)


def _sitemap(base: str, limit: int = 5000) -> set[str]:
    paths: set[str] = set()
    todo, seen = [base.rstrip("/") + "/sitemap.xml"], set()
    while todo and len(seen) < 6:
        u = todo.pop()
        seen.add(u)
        try:
            r = guard.get(u)
            if not r.ok or "<" not in r.text[:200]:
                continue
            root = ET.fromstring(r.content)
        except Exception:
            continue
        for loc in root.iter():
            if loc.tag.endswith("loc") and loc.text:
                t = loc.text.strip()
                if t.endswith(".xml") and len(seen) + len(todo) < 6:
                    todo.append(t)
                else:
                    p = urlparse(t).path.rstrip("/") or "/"
                    paths.add(p)
                    if len(paths) >= limit:
                        return paths
    return paths


def _last_published(url: str) -> tuple[str | None, str]:
    try:
        r = guard.get(url)
        m = LP_RX.search(r.text)
        title = BeautifulSoup(r.text, "html.parser").title
        return (m.group(1).strip() if m else None), (title.string.strip() if title and title.string else "")
    except Exception:
        return None, ""


def _parse_lp(s: str) -> datetime | None:
    try:
        return datetime.strptime(s[:33].replace(" GMT+0000", ""), "%a %b %d %Y %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def staging_candidates(con, comp: Entity) -> list[str]:
    c = list(comp.staging)
    for f in facts.active(con, comp.id, "subdomains", "subdomain"):
        v = f["value"] or {}
        if v.get("kind") == "environment" and v.get("resolves") and not v.get("private") and v.get("status") == 200:
            c.append(f"https://{f['key']}")
    if any(t["key"] == "webflow" for t in facts.active(con, comp.id, "stack", "tool")):
        root = comp.domain.removeprefix("www.").split(".")[0]
        for slug in {comp.id, root}:
            c += [f"https://{slug}-stg.webflow.io", f"https://{slug}-staging.webflow.io", f"https://{slug}-dev.webflow.io"]
    return list(dict.fromkeys(c))


def github_orgs(con, comp: Entity) -> list[str]:
    orgs = list(comp.github)
    if not orgs:
        try:
            r = guard.get(f"https://{comp.domain}/")
            orgs += sorted({m.lower() for m in re.findall(r"https?://(?:www\.)?github\.com/([A-Za-z0-9-]{2,39})/?[\"'#?]", r.text)
                            if m.lower() not in ("features", "topics", "orgs", "sponsors", "about", "login")})[:2]
        except Exception:
            pass
    return orgs


RULES = {
    "staging_site": Rule(severity="medium", title_add=lambda f: f"Public staging site found: {f.key}",
                         so_what=lambda f: "Staging mirrors upcoming site releases; pages here usually go live within days or weeks."),
    "staging_page": Rule(severity="high", title_add=lambda f: f"Pre-launch page on staging: {f.label}",
                         title_remove=lambda r: f"Staging page published or removed: {r['label']}",
                         so_what=lambda f: "This page exists on their staging site but not on production, an upcoming launch, campaign or pricing change."),
    "site_page": Rule(severity="low", on_remove=True, title_add=lambda f: f"New page live: {f.label}",
                      severity_fn=lambda f: "medium" if not NOISE_PATH.search(f.key) else "low"),
    "publish": Rule(severity="low", on_remove=False, title_add=lambda f: f"Site republished ({f.value.get('site')})"),
    "repo": Rule(severity="high", title_add=lambda f: f"New public GitHub repo: {f.label}",
                 so_what=lambda f: "New open-source repos often precede product or developer-facing launches."),
}


def run_one(con, cfg: Config, comp: Entity) -> dict:
    obs: list[Fact] = []
    domain = comp.domain
    if not domain:
        return {"skipped": "no domain"}
    prod_base = f"https://{domain}" if domain.startswith("www.") else f"https://www.{domain}"
    prod = _sitemap(prod_base) or _sitemap(f"https://{domain}")
    for p in sorted(prod):
        obs.append(Fact("site_page", p, p, {}, facts.CONFIRMED, [ev(prod_base + "/sitemap.xml", "production sitemap")]))
    lp, _ = _last_published(prod_base + "/")
    if lp:
        obs.append(Fact("publish", f"prod:{lp}", lp, {"site": "production", "at": lp}, facts.CONFIRMED,
                        [ev(prod_base + "/", "Webflow 'Last Published' stamp")]))
        t = _parse_lp(lp)
        if t:
            facts.metric(con, comp.id, MODULE, "publish", t.strftime("%Y-%m-%dT%H:%M"), 1)
    staging_found = 0
    for s in staging_candidates(con, comp):
        try:
            r = guard.get(s + "/")
        except guard.Blocked as b:
            if "robots" in b.reason and guard._robots.get(s.rstrip("/")) is not None:
                # The host exists (it serves robots.txt) but forbids crawling: record existence only.
                staging_found += 1
                obs.append(Fact("staging_site", urlparse(s).hostname, urlparse(s).hostname,
                                {"url": s, "crawl": "disallowed by robots.txt, existence recorded, content not collected"},
                                facts.CONFIRMED, [ev(s + "/robots.txt", "robots.txt (host exists; crawling disallowed)")]))
            continue
        except Exception:
            continue
        if r.status_code != 200 or "Page not found" in r.text[:3000]:
            continue
        staging_found += 1
        slp = (LP_RX.search(r.text) or [None, None])[1]
        obs.append(Fact("staging_site", urlparse(s).hostname, urlparse(s).hostname, {"url": s, "last_published": slp},
                        facts.CONFIRMED, [ev(s + "/", "public staging site (robots.txt allows)")]))
        if slp:
            obs.append(Fact("publish", f"staging:{slp}", slp, {"site": "staging", "at": slp}, facts.CONFIRMED, [ev(s + "/", "Webflow 'Last Published' stamp")]))
            t = _parse_lp(slp)
            if t:
                facts.metric(con, comp.id, MODULE, "publish_staging", t.strftime("%Y-%m-%dT%H:%M"), 1)
        spaths = _sitemap(s)
        only = sorted(p for p in spaths - prod if not NOISE_PATH.search(p))[:60]
        for p in only:
            obs.append(Fact("staging_page", f"{urlparse(s).hostname}{p}", p, {"staging_url": s + p, "staging": s},
                            facts.CONFIRMED, [ev(s + p, "staging sitemap vs production sitemap diff")]))
    # GitHub
    repos = 0
    for org in github_orgs(con, comp):
        for kind in ("orgs", "users"):
            try:
                data = guard.get_json(f"https://api.github.com/{kind}/{org}/repos?per_page=100&sort=pushed", respect_robots=False)
            except Exception as e:
                log.info("github %s/%s: %s", kind, org, e)
                continue
            for rp in data:
                if rp.get("fork"):
                    continue
                repos += 1
                obs.append(Fact("repo", rp["full_name"], rp["full_name"], {
                    "description": rp.get("description"), "stars": rp.get("stargazers_count"), "language": rp.get("language"),
                    "created_at": rp.get("created_at"), "pushed_at": rp.get("pushed_at"), "url": rp.get("html_url")},
                    facts.CONFIRMED, [ev(rp.get("html_url"), "GitHub public API")]))
                pushed = (rp.get("pushed_at") or "")[:7]
                if pushed:
                    facts.metric(con, comp.id, MODULE, f"repo_push:{rp['name']}", pushed, 1)
            break
    kinds = ["site_page", "publish", "staging_site", "staging_page", "repo"]
    stats = facts.sync(con, comp.id, MODULE, obs, kinds, RULES)
    stats.update(prod_pages=len(prod), staging_sites=staging_found, repos=repos)
    stats["launch"] = launch_score(con, comp)
    return stats


# ── Launch probability ────────────────────────────────────────────────────────
# Weight of each signal type (probability it indicates a launch on its own) and why.
SIGNALS = [
    ("radar", "staging_page_added", 0.35, "new page on staging"),
    ("subdomains", "subdomain_added", 0.25, "new campaign/product subdomain"),
    ("subdomains", "wildcard_added", 0.12, "new wildcard certificate"),
    ("radar", "repo_added", 0.18, "new public repo"),
    ("hiring", "job_added", 0.06, "new role"),
    ("hiring", "first_role", 0.12, "first-of-its-kind role"),
    ("dns", "verification_added", 0.10, "new tool verification"),
    ("stack", "tool_added", 0.06, "new marketing tool"),
    ("gtm", "conversion_added", 0.12, "new conversion event"),
    ("radar", "site_page_added", 0.05, "new production page"),
    ("pages", "page_change", 0.04, "homepage/product copy change"),
]
HALF_LIFE_DAYS = 21


def launch_score(con, comp: Entity, window_days: int = 45) -> dict:
    since = datetime.now(timezone.utc).timestamp() - window_days * 86400
    evts = db.rows(con.execute("SELECT module, kind, title, detected_at, severity, data FROM events WHERE competitor=? AND detected_at>=?",
                               (comp.id, datetime.fromtimestamp(since, timezone.utc).isoformat(timespec="seconds"))))
    p_none, contrib = 1.0, []
    for e in evts:
        for mod, kind, w, why in SIGNALS:
            if e["module"] == mod and e["kind"] == kind:
                if kind == "subdomain_added" and (e["data"] or {}).get("kind") not in ("campaign / product", "environment"):
                    continue
                if kind == "site_page_added" and NOISE_PATH.search((e["data"] or {}).get("key", "")):
                    continue
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(e["detected_at"])).days
                wt = w * math.pow(0.5, age / HALF_LIFE_DAYS)
                p_none *= (1 - wt)
                contrib.append({"signal": why, "title": e["title"], "at": e["detected_at"], "weight": round(wt, 3)})
    p = 1 - p_none
    contrib.sort(key=lambda c: -c["weight"])
    kinds = {c["signal"] for c in contrib}
    horizon = "2–4 weeks" if "new page on staging" in kinds else "4–8 weeks" if p >= 0.3 else "-"
    out = {"probability": round(p, 3), "horizon": horizon, "signals": contrib[:8], "n": len(contrib)}
    facts.metric(con, comp.id, MODULE, "launch_probability", datetime.now(timezone.utc).strftime("%Y-%m-%d"), out["probability"])
    db.set_meta(con, f"launch:{comp.id}", out)
    return out


def run(cfg: Config, only: str | None = None) -> dict:
    out = {}
    for comp in cfg.competitors:
        if only and comp.id != only:
            continue
        try:
            with db.connect() as con:
                out[comp.id] = run_one(con, cfg, comp)
        except Exception as e:
            log.exception("radar failed for %s", comp.id)
            out[comp.id] = {"error": str(e)[:200]}
        log.info("radar %-20s %s", comp.id, {k: v for k, v in out[comp.id].items() if k != "launch"})
    return out
