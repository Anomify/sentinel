"""Method tracker: which intelligence method has produced what, for each competitor."""
from __future__ import annotations

import os

from .. import db
from ..config import Config

METHODS = [
    # id, module(s), label, replaces, source, requirement-check
    ("stack", ["stack"], "GTM stack fingerprint", "Wappalyzer / BuiltWith / DevTools", "Headless browser network capture", None),
    ("gtm", ["gtm", "gtm_links"], "Tag manager & conversions", "Manual GTM inspection", "Public GTM container (gtm.js)", None),
    ("dns", ["dns"], "DNS & email infrastructure", "MXToolbox", "DNS-over-HTTPS", None),
    ("subdomains", ["subdomains"], "Subdomains & certificates", "Subdomain finders", "crt.sh + Cert Spotter (CT logs)", None),
    ("radar", ["radar"], "Pre-launch radar", "Manual staging checks", "Sitemaps, Webflow publish stamps, GitHub API", None),
    ("hiring", ["hiring"], "Hiring intelligence", "LinkedIn Jobs browsing", "Greenhouse / Lever / Ashby APIs", None),
    ("money", ["money"], "Partners, channel & money", "Crunchbase / press trawling", "Partner pages, marketplaces, Google News RSS", None),
    ("ads", ["ads"], "Ads intelligence", "Ad library browsing", "Google Ads BigQuery dataset, Meta Ad Library API",
     lambda: bool(os.environ.get("META_ADS_TOKEN") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))),
    ("pages", ["pages"], "Positioning & pricing diffs", "Crayon / Klue", "Page snapshots", None),
    ("content", ["content"], "Content engine", "Feedly", "RSS / blog listings", None),
    ("ai", ["ai"], "AI search visibility", "Manual prompting", "Perplexity, ChatGPT, Gemini, AI Overviews APIs",
     lambda: any(os.environ.get(k) for k in ("PERPLEXITY_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "SERPAPI_API_KEY"))),
]


def matrix(cfg: Config) -> dict:
    with db.connect() as con:
        fact_rows = db.rows(con.execute(
            "SELECT competitor, module, COUNT(*) n, MAX(last_seen) last FROM facts WHERE removed_at IS NULL GROUP BY competitor, module"))
        snaps = db.rows(con.execute("SELECT competitor, COUNT(*) n, MAX(fetched_at) last FROM snapshots WHERE error IS NULL GROUP BY competitor"))
        posts = db.rows(con.execute("SELECT competitor, COUNT(*) n, MAX(first_seen) last FROM posts GROUP BY competitor"))
        ai_any = con.execute("SELECT MAX(run_at) FROM ai_results").fetchone()[0]
        blocked = db.rows(con.execute("SELECT host, COUNT(*) n, MAX(reason) reason FROM guard_log WHERE action='blocked' GROUP BY host ORDER BY n DESC LIMIT 50"))
        runs = {r["job"]: r for r in db.rows(con.execute("SELECT job, MAX(finished_at) finished_at, status FROM runs GROUP BY job"))}
    idx = {(r["competitor"], r["module"]): r for r in fact_rows}
    out = []
    for comp in cfg.competitors:
        row = {"competitor": comp.id, "name": comp.name, "cells": {}}
        own_hosts = tuple(comp.domains)
        for mid, mods, label, _, _, req in METHODS:
            if mid == "pages":
                r = next((x for x in snaps if x["competitor"] == comp.id), None)
                n, last = (r["n"], r["last"]) if r else (0, None)
            elif mid == "content":
                r = next((x for x in posts if x["competitor"] == comp.id), None)
                n, last = (r["n"], r["last"]) if r else (0, None)
            elif mid == "ai":
                n, last = (1, ai_any) if ai_any else (0, None)
            else:
                rs = [idx[(comp.id, m)] for m in mods if (comp.id, m) in idx]
                n, last = sum(r["n"] for r in rs), max((r["last"] for r in rs), default=None)
            ran = mid in runs or (mid == "gtm" and "stack" in runs) or (mid == "content" and "feeds" in runs)
            if n:
                status = "covered"
            elif req and not req():
                status = "needs setup"
            elif ran:
                status = "no data"
            else:
                status = "not run"
            if mid == "ads" and n and not (req and req()):
                status = "partial"  # pixels only, no library confirmation
            blk = [b for b in blocked if any((b["host"] or "").endswith(h) for h in own_hosts)] if mid in ("radar", "subdomains") else []
            row["cells"][mid] = {"status": status, "facts": n, "last": last, "blocked": sum(b["n"] for b in blk)}
        out.append(row)
    return {"methods": [{"id": m[0], "label": m[2], "replaces": m[3], "source": m[4]} for m in METHODS],
            "rows": out, "blocked": blocked}
