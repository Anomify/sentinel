"""Job runner + a tiny built-in scheduler (no Celery, no Redis)."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import traceback
from datetime import datetime, timedelta

from . import config, db, digest
from .collectors import ai_search, feeds, pages

log = logging.getLogger(__name__)
JOBS = {
    "pages": lambda cfg, **kw: pages.run(cfg, kw.get("competitor")),
    "feeds": lambda cfg, **kw: feeds.run(cfg, kw.get("competitor")),
    "ai": lambda cfg, **kw: ai_search.run(cfg, kw.get("limit")),
    "digest": lambda cfg, **kw: digest.run(cfg, deliver=kw.get("deliver", True)),
}
_lock = threading.Lock()
running: dict[str, str] = {}


def run_job(name: str, **kw) -> dict:
    cfg = config.load()
    with _lock:
        if name in running:
            return {"status": "already_running"}
        running[name] = db.now()
    with db.connect() as con:
        rid = db.insert(con, "runs", {"job": name, "started_at": db.now(), "status": "running"})
    try:
        stats = JOBS[name](cfg, **kw)
        status, err = "ok", None
    except Exception as e:
        log.exception("job %s failed", name)
        stats, status, err = {}, "error", "".join(traceback.format_exception_only(e)).strip()
    finally:
        with _lock:
            running.pop(name, None)
    slim = {k: v for k, v in stats.items() if k != "results"}
    with db.connect() as con:
        con.execute("UPDATE runs SET finished_at=?, status=?, stats=?, error=? WHERE id=?",
                    (db.now(), status, json.dumps(slim), err, rid))
    return {"job": name, "status": status, "error": err, **slim}


def run_async(name: str, **kw) -> None:
    threading.Thread(target=run_job, args=(name,), kwargs=kw, daemon=True).start()


# ── schedule parsing: "every 6h" | "every 30m" | "daily 07:00" | "weekly mon 08:00" ──
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def next_due(spec: str, last: datetime | None, now: datetime) -> datetime:
    spec = spec.strip().lower()
    if m := re.fullmatch(r"every (\d+)\s*([mhd])", spec):
        delta = timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[m[2]]: int(m[1])})
        return (last + delta) if last else now
    if m := re.fullmatch(r"(daily|weekly (\w{3})) (\d\d):(\d\d)", spec):
        t = now.replace(hour=int(m[3]), minute=int(m[4]), second=0, microsecond=0)
        if m[2]:
            t -= timedelta(days=(t.weekday() - DAYS.index(m[2])) % 7)
        # t is the most recent slot ≤ now (or later today); due if we haven't run since it
        if t > now:
            t -= timedelta(days=7 if m[2] else 1)
        return t if not last or last < t else t + timedelta(days=7 if m[2] else 1)
    raise ValueError(f"bad schedule: {spec}")


def daemon(poll_s: int = 60) -> None:
    log.info("scheduler started")
    while True:
        cfg = config.load()
        now = datetime.now()
        with db.connect() as con:
            last_runs = db.get_meta(con, "last_scheduled", {})
        for job, spec in (cfg.settings.get("schedule") or {}).items():
            last = datetime.fromisoformat(last_runs[job]) if job in last_runs else None
            try:
                if next_due(spec, last, now) <= now:
                    log.info("scheduler → %s", job)
                    last_runs[job] = now.isoformat()
                    with db.connect() as con:
                        db.set_meta(con, "last_scheduled", last_runs)
                    run_job(job)
            except ValueError as e:
                log.error("%s", e)
        time.sleep(poll_s)


def schedule_status(cfg) -> list[dict]:
    now = datetime.now()
    with db.connect() as con:
        last_runs = db.get_meta(con, "last_scheduled", {})
    out = []
    for job, spec in (cfg.settings.get("schedule") or {}).items():
        last = datetime.fromisoformat(last_runs[job]) if job in last_runs else None
        try:
            nxt = next_due(spec, last, now)
        except ValueError:
            nxt = None
        out.append({"job": job, "spec": spec, "last": last.isoformat() if last else None,
                    "next": nxt.isoformat() if nxt else None, "running": job in running})
    return out
