"""`sentinel` command line."""
from __future__ import annotations

import argparse
import json
import logging
import os
import threading

from . import config, jobs


def main(argv=None):
    p = argparse.ArgumentParser("sentinel", description="Competitive intelligence monitor")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in [("pages", "snapshot competitor pages & detect changes"), ("feeds", "pull blog/RSS feeds"),
                        ("ai", "run AI-search visibility questions"), ("digest", "build & deliver the weekly digest")]:
        s = sub.add_parser(name, help=help_)
        if name in ("pages", "feeds"):
            s.add_argument("--competitor")
        if name == "ai":
            s.add_argument("--limit", type=int, help="only the first N questions (cheap smoke test)")
        if name == "digest":
            s.add_argument("--no-send", action="store_true", help="build and store, but don't deliver")
    sub.add_parser("run", help="pages + feeds (+ ai if keys present), then exit")
    sv = sub.add_parser("serve", help="web dashboard + API")
    sv.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    sv.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    sv.add_argument("--no-scheduler", action="store_true", help="don't run scheduled jobs in-process")
    sub.add_parser("daemon", help="scheduler only (no web)")
    d = sub.add_parser("demo", help="load realistic demo data so you can explore the UI")
    d.add_argument("--clear", action="store_true", help="remove demo data")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")
    if a.cmd in ("pages", "feeds"):
        out = jobs.run_job(a.cmd, competitor=a.competitor)
    elif a.cmd == "ai":
        out = jobs.run_job("ai", limit=a.limit)
    elif a.cmd == "digest":
        out = jobs.run_job("digest", deliver=not a.no_send)
    elif a.cmd == "run":
        out = [jobs.run_job("pages"), jobs.run_job("feeds"), jobs.run_job("ai")]
    elif a.cmd == "daemon":
        return jobs.daemon()
    elif a.cmd == "demo":
        from . import demo
        out = demo.clear() if a.clear else demo.seed(config.load())
    elif a.cmd == "serve":
        import uvicorn
        if not a.no_scheduler:
            threading.Thread(target=jobs.daemon, daemon=True).start()
        uvicorn.run("cimonitor.api:app", host=a.host, port=a.port, log_level="info")
        return
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
