"""HTTP API + static SPA. Every /api route is scoped to a workspace (X-Workspace header)."""
from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, digest, facts, guard, insights, jobs, llm, tenancy
from .collectors import ai_search
from .collectors.fetch import evidence_dir
from .intel import coverage, deepdive

app = FastAPI(title="Sentinel CI", docs_url="/api/docs", openapi_url="/api/openapi.json")
ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
FONTS = DIST / "fonts" if (DIST / "fonts").exists() else ROOT / "web" / "public" / "fonts"
TOKEN = os.environ.get("SENTINEL_TOKEN")
OPEN = {"/api/health"}


@app.middleware("http")
async def scope(request: Request, call_next):
    p = request.url.path
    if not p.startswith("/api") or p in OPEN:
        return await call_next(request)
    ws = request.headers.get("x-workspace") or request.query_params.get("ws") or tenancy.DEFAULT
    if not tenancy.exists(ws):
        return JSONResponse({"detail": "unknown workspace"}, status_code=404)
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("token", "")
    needs_auth = bool(TOKEN) or ws != tenancy.DEFAULT
    if needs_auth and not tenancy.authorize(ws, given, TOKEN):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    with tenancy.use(ws):
        resp = await call_next(request)
    return await _strip_dashes(resp)


async def _strip_dashes(resp):
    """No em dashes anywhere in the app, including stored data and AI text written before this rule."""
    ctype = resp.headers.get("content-type", "")
    if not (ctype.startswith("application/json") or ctype.startswith("text/html")):
        return resp
    body = b"".join([c async for c in resp.body_iterator])
    text = body.decode("utf-8")
    if "\u2014" not in text and "\\u2014" not in text:
        return Response(body, status_code=resp.status_code, headers=dict(resp.headers))
    text = re.sub(r"\s*(\u2014|\\u2014)\s*", ", ", text)
    headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
    return Response(text.encode("utf-8"), status_code=resp.status_code, headers=headers)


def cfg():
    return config.load()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    c = cfg()
    with db.connect() as con:
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("snapshots", "changes", "posts", "ai_results", "digests", "facts", "events")}
    return {
        "workspace": tenancy.current(), "workspaces": tenancy.list_workspaces(),
        "brand": {"name": c.brand.name, "color": c.brand.color, "domains": c.brand.domains, "profile": c.brand.profile},
        "entities": insights.entities(c), "watch_terms": c.watch_terms,
        "questions": [q.__dict__ for q in c.questions],
        "engines": [{"id": k, "model": v.get("model"), "enabled": bool(v.get("enabled")),
                     "has_key": bool(os.environ.get(ai_search.ENGINES[k][1])) if k in ai_search.ENGINES else False}
                    for k, v in c.engines.items()],
        "channels": digest.channels_configured(c), "digest_to": digest.recipients(c), "analysis": llm.available(c), "analysis_provider": llm.provider(c),
        "schedule": jobs.schedule_status(c), "demo": db.is_demo(), "counts": counts,
        "auth": bool(TOKEN), "backend": db.backend(), "policy": [{"title": t, "detail": d} for t, d in guard.POLICY],
        "modules": insights.MODULE_LABEL,
    }


@app.get("/api/overview")
def overview(days: int = 7):
    c = cfg()
    with db.connect() as con:
        return insights.overview(c, con, days)


# ── signals (unified events) ─────────────────────────────────────────────────
@app.get("/api/events")
def list_events(days: int = 30, competitor: str | None = None, module: str | None = None, severity: list[str] | None = Query(None)):
    with db.connect() as con:
        return insights.events(con, days, competitor, module, severity, limit=800)


@app.get("/api/events/{eid}")
def event_detail(eid: int):
    with db.connect() as con:
        e = db.row(con.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone())
    if not e:
        raise HTTPException(404)
    if e.get("change_id"):
        e["change"] = change_detail(e["change_id"])
    return e


@app.post("/api/events/{eid}/ack")
def ack_event(eid: int, value: bool = True):
    with db.connect() as con:
        con.execute("UPDATE events SET acknowledged=? WHERE id=?", (int(value), eid))
        r = con.execute("SELECT change_id FROM events WHERE id=?", (eid,)).fetchone()
        if r and r[0]:
            con.execute("UPDATE changes SET acknowledged=? WHERE id=?", (int(value), r[0]))
    return {"ok": True}


@app.get("/api/changes")
def list_changes(days: int = 30, competitor: str | None = None, severity: list[str] | None = Query(None)):
    with db.connect() as con:
        return insights.changes(con, days, competitor, severity, limit=500)


@app.get("/api/changes/{cid}")
def change_detail(cid: int):
    with db.connect() as con:
        ch = db.row(con.execute("SELECT * FROM changes WHERE id=?", (cid,)).fetchone())
        if not ch:
            raise HTTPException(404)
        a = db.row(con.execute("SELECT id, fetched_at, text, title, meta, signals, screenshot FROM snapshots WHERE id=?", (ch["prev_snapshot"],)).fetchone())
        b = db.row(con.execute("SELECT id, fetched_at, text, title, meta, signals, screenshot FROM snapshots WHERE id=?", (ch["snapshot"],)).fetchone())
    diff = []
    if a and b:
        ol, nl = (a["text"] or "").splitlines(), (b["text"] or "").splitlines()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ol, nl, autojunk=False).get_opcodes():
            if op == "equal":
                ctx = ol[i1:i2]
                diff += ([{"t": "eq", "s": ctx[0]}, {"t": "gap", "s": f"{len(ctx) - 2} unchanged lines"}, {"t": "eq", "s": ctx[-1]}]
                         if len(ctx) > 4 else [{"t": "eq", "s": s} for s in ctx])
            else:
                diff += [{"t": "del", "s": s} for s in ol[i1:i2]] + [{"t": "add", "s": s} for s in nl[j1:j2]]
    keep = ("id", "fetched_at", "title", "meta", "signals", "screenshot")
    return {**ch, "before": a and {k: a[k] for k in keep}, "after": b and {k: b[k] for k in keep}, "diff": diff}


@app.post("/api/changes/{cid}/ack")
def ack(cid: int, value: bool = True):
    with db.connect() as con:
        con.execute("UPDATE changes SET acknowledged=? WHERE id=?", (int(value), cid))
    return {"ok": True}


# ── facts & module views ─────────────────────────────────────────────────────
@app.get("/api/facts")
def list_facts(competitor: str, module: str | None = None, kind: str | None = None, history: bool = False):
    with db.connect() as con:
        return (facts.history if history else facts.active)(con, competitor, module, kind)


@app.get("/api/stack")
def stack():
    c = cfg()
    with db.connect() as con:
        return insights.stack_matrix(c, con)


@app.get("/api/hiring")
def hiring():
    c = cfg()
    with db.connect() as con:
        return insights.hiring_view(c, con)


@app.get("/api/radar")
def radar():
    c = cfg()
    with db.connect() as con:
        return insights.radar_view(c, con)


@app.get("/api/positioning")
def positioning():
    c = cfg()
    with db.connect() as con:
        return insights.positioning_view(c, con)


@app.get("/api/posts")
def list_posts(days: int = 90, competitor: str | None = None):
    with db.connect() as con:
        return insights.posts(con, days, competitor, limit=500)


@app.get("/api/visibility")
def visibility(run_id: str | None = None):
    c = cfg()
    with db.connect() as con:
        v = insights.visibility(c, con, run_id)
    v["gaps"] = insights.gaps(c, v)
    return v


@app.get("/api/ai/answers")
def answers(question_id: str, run_id: str | None = None):
    with db.connect() as con:
        if not run_id:
            r = con.execute("SELECT run_id FROM ai_results ORDER BY run_at DESC LIMIT 1").fetchone()
            run_id = r[0] if r else None
        return db.rows(con.execute("SELECT * FROM ai_results WHERE run_id=? AND question_id=? ORDER BY engine", (run_id, question_id)))


@app.get("/api/competitors/{cid}")
def competitor(cid: str):
    c = cfg()
    e = c.competitor(cid)
    if not e:
        raise HTTPException(404)
    with db.connect() as con:
        pages = []
        for p in e.pages:
            s = db.row(con.execute("SELECT id, fetched_at, status, title, meta, signals, error, screenshot FROM snapshots "
                                   "WHERE url=? ORDER BY id DESC LIMIT 1", (p.url,)).fetchone())
            n = con.execute("SELECT COUNT(*) FROM changes WHERE url=?", (p.url,)).fetchone()[0]
            pages.append({**p.__dict__, "latest": s, "changes": n})
        ev = insights.events(con, 365, cid, limit=300)
        ps = insights.posts(con, 3650, cid, limit=100)
        vis = insights.visibility(c, con)
        mods = {r["module"]: r["n"] for r in db.rows(con.execute(
            "SELECT module, COUNT(*) n FROM facts WHERE competitor=? AND removed_at IS NULL "
            "AND kind NOT IN ('site_page','txt','page_id','third_party','spf','gtm_tag','cookies','publish') GROUP BY module", (cid,)))}
        scan = db.get_meta(con, f"scan:{cid}")
        launch = db.get_meta(con, f"launch:{cid}")
        rep = con.execute("SELECT created_at FROM reports WHERE competitor=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    share = next((s for s in vis["share"] if s["id"] == cid), None)
    return {**next(x for x in insights.entities(c) if x["id"] == cid), "pages_status": pages, "events": ev, "posts": ps,
            "ai": share, "ai_trend": [{"date": t["date"], "share": t.get(cid)} for t in vis["trend"]],
            "modules": mods, "scan": scan, "launch": launch, "report_at": rep[0] if rep else None}


@app.get("/api/battlecard/{cid}", response_class=PlainTextResponse)
def battlecard(cid: str):
    """Deep dive as Markdown (kept for compatibility with earlier battlecard links)."""
    return deepdive_md(cid)


# ── intelligence layer ───────────────────────────────────────────────────────
@app.get("/api/deepdive/{cid}")
def deepdive_get(cid: str, regenerate: bool = False):
    c = cfg()
    e = c.competitor(cid)
    if not e:
        raise HTTPException(404)
    if not regenerate:
        with db.connect() as con:
            r = con.execute("SELECT payload FROM reports WHERE competitor=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
        if r:
            return json.loads(r[0]) if isinstance(r[0], str) else r[0]
    deepdive.run(c, cid)
    with db.connect() as con:
        r = con.execute("SELECT payload FROM reports WHERE competitor=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    return json.loads(r[0]) if r and isinstance(r[0], str) else (r[0] if r else {})


@app.get("/api/deepdive/{cid}/markdown", response_class=PlainTextResponse)
def deepdive_md(cid: str):
    with db.connect() as con:
        r = con.execute("SELECT markdown FROM reports WHERE competitor=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    if r:
        return r[0]
    deepdive_get(cid, regenerate=True)
    with db.connect() as con:
        r = con.execute("SELECT markdown FROM reports WHERE competitor=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    return r[0] if r else ""


class TargetIn(BaseModel):
    domain: str
    name: str | None = None


DOMAIN_RX = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)/?.*$", re.I)


@app.post("/api/targets")
def add_target(t: TargetIn):
    """Enter a domain → it joins the watchlist and a full scan + deep dive starts immediately."""
    m = DOMAIN_RX.match(t.domain.strip())
    if not m:
        raise HTTPException(400, "Enter a domain like acme.com")
    domain = m.group(1).lower()
    c = cfg()
    existing = next((x for x in c.competitors if domain in [d.removeprefix("www.") for d in x.domains]), None)
    if existing:
        jobs.run_async("scan", competitor=existing.id)
        return {"id": existing.id, "status": "rescanning"}
    cid = re.sub(r"[^a-z0-9]+", "-", domain.split(".")[0])[:30].strip("-") or "target"
    if c.competitor(cid):
        cid = f"{cid}-{len(c.competitors)}"
    name = t.name or domain.split(".")[0].replace("-", " ").title()
    conf = {"id": cid, "name": name, "domains": [domain], "tier": "primary",
            "pages": [{"kind": "homepage", "url": f"https://{domain}/"}], "feeds": []}
    with db.connect() as con:
        db.insert(con, "targets", {"competitor": cid, "name": name, "domain": domain, "created_at": db.now(), "config": conf})
    jobs.run_async("scan", competitor=cid)
    return {"id": cid, "status": "scanning"}


@app.delete("/api/targets/{cid}")
def remove_target(cid: str):
    with db.connect() as con:
        con.execute("DELETE FROM targets WHERE competitor=?", (cid,))
    return {"ok": True}


@app.post("/api/scan/{cid}")
def scan(cid: str):
    if not cfg().competitor(cid):
        raise HTTPException(404)
    jobs.run_async("scan", competitor=cid)
    return {"status": "started"}


@app.get("/api/scan/{cid}")
def scan_status(cid: str):
    with db.connect() as con:
        return db.get_meta(con, f"scan:{cid}") or {"step": None}


@app.get("/api/coverage")
def coverage_get():
    return coverage.matrix(cfg())


@app.get("/api/guard")
def guard_log(limit: int = 200):
    with db.connect() as con:
        rows = db.rows(con.execute("SELECT * FROM guard_log ORDER BY id DESC LIMIT ?", (limit,)))
        stats = {r["action"]: r["n"] for r in db.rows(con.execute("SELECT action, COUNT(*) n FROM guard_log GROUP BY action"))}
    return {"policy": [{"title": t, "detail": d} for t, d in guard.POLICY], "log": rows, "stats": stats}


@app.get("/api/evidence/{name}")
def evidence(name: str):
    if not re.fullmatch(r"[\w.-]+\.png", name):
        raise HTTPException(400)
    p = evidence_dir() / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ── digest ───────────────────────────────────────────────────────────────────
@app.get("/api/digests")
def digests():
    with db.connect() as con:
        return db.rows(con.execute("SELECT id, created_at, period_start, period_end, headline, delivered FROM digests ORDER BY id DESC LIMIT 50"))


@app.post("/api/digests")
def digest_create(deliver: bool = False):
    """Build (and optionally send) a digest now, and say exactly what happened."""
    c = cfg()
    if deliver and not any(digest.channels_configured(c).values()):
        raise HTTPException(400, "Email isn't set up yet. Add SMTP_USER and SMTP_PASS (a Google app password) to .env, then restart Sentinel.")
    r = digest.run(c, deliver=deliver)
    failed = {k: v for k, v in r["delivered"].items() if v != "sent"}
    if failed:
        raise HTTPException(502, "; ".join(f"{k}: {v}" for k, v in failed.items()) + f" (saved as digest #{r['digest_id']})")
    return {**r, "to": digest.recipients(c)}


@app.get("/api/digests/preview", response_class=HTMLResponse)
def digest_preview(days: int = 7):
    return digest.render_html(digest.build(cfg(), days))


@app.get("/api/digests/{did}/html", response_class=HTMLResponse)
def digest_html(did: int):
    with db.connect() as con:
        r = con.execute("SELECT html FROM digests WHERE id=?", (did,)).fetchone()
    if not r:
        raise HTTPException(404)
    return r[0]


# ── jobs ─────────────────────────────────────────────────────────────────────
@app.post("/api/jobs/{name}")
def trigger(name: str, deliver: bool = True):
    if name not in jobs.JOBS:
        raise HTTPException(404)
    if name in jobs.running():
        return {"status": "already_running"}
    jobs.run_async(name, deliver=deliver)
    return {"status": "started", "job": name}


@app.get("/api/runs")
def runs(limit: int = 30):
    with db.connect() as con:
        r = db.rows(con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)))
    return {"runs": r, "running": jobs.running()}


# ── workspaces ───────────────────────────────────────────────────────────────
class WorkspaceIn(BaseModel):
    slug: str
    name: str
    brand_name: str | None = None
    brand_domain: str | None = None


@app.get("/api/workspaces")
def workspaces():
    return tenancy.list_workspaces()


@app.post("/api/workspaces")
def create_workspace(w: WorkspaceIn, request: Request):
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if TOKEN and given != TOKEN:
        raise HTTPException(403, "admin token required")
    try:
        token = tenancy.create(w.slug, w.name, {"name": w.brand_name or w.name, "domains": [w.brand_domain] if w.brand_domain else []})
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"slug": w.slug, "token": token, "note": "Store this token now; it is shown once."}


# ── static ───────────────────────────────────────────────────────────────────
if FONTS.exists():
    app.mount("/fonts", StaticFiles(directory=FONTS), name="fonts")
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
