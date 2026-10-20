"""Job runner + a tiny built-in scheduler (no Celery, no Redis). Workspace-aware."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import traceback
from datetime import datetime, timedelta

from . import config, db, digest, guard, tenancy

log = logging.getLogger(__name__)


def _c():
    from .collectors import ads, ai_search, dns_infra, feeds, hiring, money, pages, products, radar, social, stack, subdomains
    return locals()


def _deepdive(cfg, **kw):
    from .intel import deepdive
    return deepdive.run(cfg, kw.get("competitor"))


# Modules that describe a whole company; meaningless for a product inside AWS / Google / Azure.
COMPANY_WIDE = {"stack", "dns", "subdomains", "radar", "hiring", "money", "ads"}


def _unscoped(cfg):
    import dataclasses
    return dataclasses.replace(cfg, competitors=[c for c in cfg.competitors if not c.scoped])


JOBS = {
    "pages": lambda cfg, **kw: _c()["pages"].run(cfg, kw.get("competitor")),
    "feeds": lambda cfg, **kw: _c()["feeds"].run(cfg, kw.get("competitor")),
    "stack": lambda cfg, **kw: _c()["stack"].run(_unscoped(cfg), kw.get("competitor")),
    "dns": lambda cfg, **kw: _c()["dns_infra"].run(_unscoped(cfg), kw.get("competitor")),
    "subdomains": lambda cfg, **kw: _c()["subdomains"].run(_unscoped(cfg), kw.get("competitor")),
    "radar": lambda cfg, **kw: _c()["radar"].run(_unscoped(cfg), kw.get("competitor")),
    "hiring": lambda cfg, **kw: _c()["hiring"].run(_unscoped(cfg), kw.get("competitor")),
    "money": lambda cfg, **kw: _c()["money"].run(_unscoped(cfg), kw.get("competitor")),
    "ads": lambda cfg, **kw: _c()["ads"].run(_unscoped(cfg), kw.get("competitor")),
    "social": lambda cfg, **kw: _c()["social"].run(cfg, kw.get("competitor")),
    "product": lambda cfg, **kw: _c()["products"].run(cfg, kw.get("competitor")),
    "ai": lambda cfg, **kw: _c()["ai_search"].run(cfg, kw.get("limit")),
    "deepdive": _deepdive,
    "digest": lambda cfg, **kw: digest.run(cfg, deliver=kw.get("deliver", True)),
    "cleanup": lambda cfg, **kw: __import__("cimonitor.cleanup", fromlist=["run"]).run(),
}
def _all(cfg, **kw):
    """Refresh every section for every company (AI visibility is left to its schedule: it spends API quota)."""
    out = {"cleanup": JOBS["cleanup"](cfg)}
    for step in ["dns", "subdomains", "stack", "pages", "feeds", "radar", "product", "social", "hiring", "money", "ads", "deepdive"]:
        try:
            out[step] = JOBS[step](config.load())
        except Exception as e:
            log.exception("all: %s failed", step)
            out[step] = {"error": str(e)[:200]}
    return out


JOBS["all"] = _all
# Order for a full scan of one competitor (deep dive): dependencies first.
FULL_SCAN = ["dns", "subdomains", "stack", "pages", "feeds", "radar", "product", "social", "hiring", "money", "ads", "deepdive"]
LABELS = {"pages": "Pages & pricing", "feeds": "Content", "stack": "GTM stack + tag manager", "dns": "DNS & email",
          "subdomains": "Subdomains & certificates", "radar": "Pre-launch radar", "hiring": "Hiring", "money": "Partners & money",
          "ads": "Ads", "product": "Product launches", "social": "Social media", "ai": "AI visibility", "deepdive": "Deep dive", "digest": "Digest", "scan": "Full scan", "all": "Everything"}

_lock = threading.Lock()
_running: dict[tuple[str, str], str] = {}


def running(ws: str | None = None) -> dict[str, str]:
    ws = ws or tenancy.current()
    return {j: t for (w, j), t in _running.items() if w == ws}


def run_job(name: str, **kw) -> dict:
    ws = tenancy.current()
    tag = f"{name}:{kw['competitor']}" if kw.get("competitor") and name == "scan" else name
    with _lock:
        if (ws, tag) in _running:
            return {"status": "already_running"}
        _running[(ws, tag)] = db.now()
    try:
        guard.reset_caches()  # the server is long-lived: every run must see today's DNS and robots.txt
        cfg = config.load()
        with db.connect() as con:
            rid = db.insert(con, "runs", {"job": tag, "started_at": db.now(), "status": "running"})
        try:
            stats = full_scan(cfg, kw["competitor"]) if name == "scan" else JOBS[name](cfg, **kw)
            status, err = "ok", None
        except Exception as e:
            log.exception("job %s failed", name)
            stats, status, err = {}, "error", "".join(traceback.format_exception_only(e)).strip()
        slim = stats if isinstance(stats, dict) else {"result": stats}
        slim = {k: v for k, v in slim.items() if k != "results"}
        with db.connect() as con:
            con.execute("UPDATE runs SET finished_at=?, status=?, stats=?, error=? WHERE id=?",
                        (db.now(), status, json.dumps(slim, default=str)[:20000], err, rid))
        return {"job": tag, "status": status, "error": err, **slim}
    finally:
        with _lock:
            _running.pop((ws, tag), None)


def full_scan(cfg, competitor: str) -> dict:
    """Every module for one competitor, with step progress (drives the deep-dive UI)."""
    out = {}
    for i, step in enumerate(FULL_SCAN):
        with db.connect() as con:
            db.set_meta(con, f"scan:{competitor}", {"step": step, "label": LABELS[step], "index": i, "total": len(FULL_SCAN),
                                                     "started": out.get("_started") or db.now(), "done": False})
        out.setdefault("_started", db.now())
        try:
            r = JOBS[step](config.load(), competitor=competitor)
            out[step] = r.get(competitor, r) if isinstance(r, dict) else r
        except Exception as e:
            log.exception("scan step %s failed", step)
            out[step] = {"error": str(e)[:200]}
    with db.connect() as con:
        db.set_meta(con, f"scan:{competitor}", {"step": "done", "label": "Complete", "index": len(FULL_SCAN),
                                                 "total": len(FULL_SCAN), "done": True, "finished": db.now()})
    return {k: (v if isinstance(v, (str, int)) else {kk: vv for kk, vv in v.items() if not isinstance(vv, (list, dict))})
            for k, v in out.items() if not k.startswith("_")}


def run_async(name: str, **kw) -> None:
    ws = tenancy.current()

    def go():
        with tenancy.use(ws):
            run_job(name, **kw)
    threading.Thread(target=go, daemon=True).start()


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


def tick() -> None:
    """One scheduler pass over every workspace."""
    for w in tenancy.list_workspaces():
        with tenancy.use(w["slug"]):
            cfg = config.load()
            now = datetime.now()
            with db.connect() as con:
                last_runs = db.get_meta(con, "last_scheduled", {})
            for job, spec in (cfg.settings.get("schedule") or {}).items():
                if job not in JOBS:
                    continue
                last = datetime.fromisoformat(last_runs[job]) if job in last_runs else None
                try:
                    if next_due(spec, last, now) <= now:
                        log.info("[%s] scheduler → %s", w["slug"], job)
                        last_runs[job] = now.isoformat()
                        with db.connect() as con:
                            db.set_meta(con, "last_scheduled", last_runs)
                        run_job(job)
                except ValueError as e:
                    log.error("%s", e)


def daemon(poll_s: int = 60) -> None:
    log.info("scheduler started")
    while True:
        try:
            tick()
        except Exception:
            log.exception("scheduler tick failed")
        time.sleep(poll_s)


def schedule_status(cfg) -> list[dict]:
    now = datetime.now()
    with db.connect() as con:
        last_runs = db.get_meta(con, "last_scheduled", {})
        manual = {r["job"]: r["t"] for r in db.rows(con.execute(
            "SELECT job, MAX(finished_at) t FROM runs WHERE status='ok' GROUP BY job"))}
    out = []
    r = running()
    for job, spec in (cfg.settings.get("schedule") or {}).items():
        last = datetime.fromisoformat(last_runs[job]) if job in last_runs else None
        try:
            nxt = next_due(spec, last, now)
        except ValueError:
            nxt = None
        ran = max(filter(None, [last.isoformat() if last else None, manual.get(job)]), default=None)
        out.append({"job": job, "label": LABELS.get(job, job), "spec": spec, "last": ran,
                    "next": nxt.isoformat() if nxt else None, "running": job in r})
    return out
