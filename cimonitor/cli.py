"""`sentinel` command line."""
from __future__ import annotations

import argparse
import json
import logging
import os
import threading

from . import config, jobs, tenancy

MODULE_HELP = {
    "pages": "Module 9 · snapshot pages & pricing, detect positioning changes",
    "feeds": "Content engine · pull blog/RSS feeds",
    "stack": "Modules 1+2 · stack fingerprint (pre/post consent) + GTM container forensics",
    "dns": "Module 3 · TXT/SPF/MX/DMARC/DKIM",
    "subdomains": "Module 4 · certificate transparency + hosting + screenshots",
    "radar": "Module 5 · staging, sitemaps, publishes, GitHub, launch probability",
    "social": "Social media · YouTube, Bluesky, Medium, X (with API key), Hacker News, LinkedIn links",
    "product": "Product intelligence · new products, release notes, launch announcements",
    "hiring": "Module 6 · Greenhouse/Lever/Ashby",
    "money": "Module 7 · partners, marketplaces, funding, press",
    "ads": "Module 8 · ad libraries + pixel cross-check",
    "ai": "Module 10 · AI-search visibility",
    "deepdive": "Intelligence layer · regenerate deep dives",
    "digest": "Build & deliver the weekly digest",
    "cleanup": "Repair stored data so it matches today's rules (runs automatically on serve)",
}


def main(argv=None):
    p = argparse.ArgumentParser("sentinel", description="Competitive & GTM-stack intelligence")
    p.add_argument("--workspace", "-w", default=os.environ.get("SENTINEL_WORKSPACE", tenancy.DEFAULT))
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in MODULE_HELP.items():
        s = sub.add_parser(name, help=help_)
        if name not in ("ai", "digest", "cleanup"):
            s.add_argument("--competitor")
        if name == "ai":
            s.add_argument("--limit", type=int, help="only the first N questions (cheap smoke test)")
        if name == "digest":
            s.add_argument("--no-send", action="store_true", help="build and store, but don't deliver")
    sc = sub.add_parser("scan", help="every module for one competitor (id or domain), then its deep dive")
    sc.add_argument("target")
    sub.add_parser("run", help="every module for every competitor, then exit (for cron / CI)")
    sv = sub.add_parser("serve", help="web dashboard + API (+ scheduler)")
    sv.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    sv.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    sv.add_argument("--no-scheduler", action="store_true")
    sub.add_parser("daemon", help="scheduler only (no web)")
    ws = sub.add_parser("workspace", help="create a workspace (multi-tenant)")
    ws.add_argument("slug")
    ws.add_argument("name")
    d = sub.add_parser("demo", help="load illustrative demo data (separate demo.db)")
    d.add_argument("--clear", action="store_true")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    with tenancy.use(a.workspace):
        if a.cmd in MODULE_HELP:
            kw = {"competitor": getattr(a, "competitor", None), "limit": getattr(a, "limit", None)}
            if a.cmd == "digest":
                kw = {"deliver": not a.no_send}
            out = jobs.run_job(a.cmd, **{k: v for k, v in kw.items() if v is not None})
            if out.get("status") == "error":  # cron / CI must see a failed module
                print(json.dumps(out, indent=2, default=str))
                raise SystemExit(1)
        elif a.cmd == "scan":
            cfg = config.load()
            comp = cfg.competitor(a.target) or next((c for c in cfg.competitors if a.target.removeprefix("www.") in
                                                     [d.removeprefix("www.") for d in c.domains]), None)
            if not comp:
                from .api import TargetIn, add_target
                comp_id = add_target(TargetIn(domain=a.target))["id"]
            else:
                comp_id = comp.id
            out = jobs.run_job("scan", competitor=comp_id)
        elif a.cmd == "run":
            order = ["dns", "subdomains", "stack", "pages", "feeds", "radar", "product", "social", "hiring", "money", "ads", "ai", "deepdive"]
            out = [jobs.run_job(j) for j in order]
        elif a.cmd == "daemon":
            return jobs.daemon()
        elif a.cmd == "workspace":
            out = {"slug": a.slug, "token": tenancy.create(a.slug, a.name), "note": "store this token; it is shown once"}
        elif a.cmd == "demo":
            from . import demo
            out = demo.clear() if a.clear else demo.seed(config.load())
        elif a.cmd == "serve":
            import uvicorn
            from . import cleanup
            for w in [x["slug"] for x in tenancy.list_workspaces()] or [tenancy.current()]:
                with tenancy.use(w):
                    cleanup.run()
            if not os.environ.get("SENTINEL_TOKEN") and a.host not in ("127.0.0.1", "localhost", "::1"):
                logging.warning("SENTINEL_TOKEN is not set and Sentinel listens on %s: anyone who can reach port %s can "
                                "read the dashboard and start paid AI runs. Set SENTINEL_TOKEN in .env.", a.host, a.port)
            if not a.no_scheduler:
                threading.Thread(target=jobs.daemon, daemon=True).start()
            uvicorn.run("cimonitor.api:app", host=a.host, port=a.port, log_level="info")
            return
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
