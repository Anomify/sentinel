"""HTTP API + static SPA."""
from __future__ import annotations

import difflib
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, digest, insights, jobs, llm
from .collectors import ai_search

app = FastAPI(title="Sentinel CI", docs_url="/api/docs", openapi_url="/api/openapi.json")
DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
TOKEN = os.environ.get("SENTINEL_TOKEN")


@app.middleware("http")
async def auth(request: Request, call_next):
    p = request.url.path
    if TOKEN and p.startswith("/api") and p not in ("/api/health",):
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("token", "")
        if not secrets.compare_digest(given, TOKEN):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


def cfg():
    return config.load()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    c = cfg()
    with db.connect() as con:
        demo = db.is_demo()
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("snapshots", "changes", "posts", "ai_results", "digests")}
    return {
        "brand": {"name": c.brand.name, "color": c.brand.color, "domains": c.brand.domains},
        "entities": insights.entities(c), "watch_terms": c.watch_terms,
        "questions": [q.__dict__ for q in c.questions],
        "engines": [{"id": k, "model": v.get("model"), "enabled": bool(v.get("enabled")),
                     "has_key": bool(os.environ.get(ai_search.ENGINES[k][1])) if k in ai_search.ENGINES else False}
                    for k, v in c.engines.items()],
        "channels": digest.channels_configured(), "analysis": llm.available(),
        "schedule": jobs.schedule_status(c), "demo": demo, "counts": counts,
        "auth": bool(TOKEN),
    }


@app.get("/api/overview")
def overview(days: int = 7):
    c = cfg()
    with db.connect() as con:
        return insights.overview(c, con, days)


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
        a = db.row(con.execute("SELECT id, fetched_at, text, title, meta, signals FROM snapshots WHERE id=?", (ch["prev_snapshot"],)).fetchone())
        b = db.row(con.execute("SELECT id, fetched_at, text, title, meta, signals FROM snapshots WHERE id=?", (ch["snapshot"],)).fetchone())
    diff = []
    if a and b:
        ol, nl = (a["text"] or "").splitlines(), (b["text"] or "").splitlines()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ol, nl, autojunk=False).get_opcodes():
            if op == "equal":
                ctx = ol[i1:i2]
                if len(ctx) > 4:
                    diff += [{"t": "eq", "s": ctx[0]}, {"t": "gap", "s": f"{len(ctx) - 2} unchanged lines"}, {"t": "eq", "s": ctx[-1]}]
                else:
                    diff += [{"t": "eq", "s": s} for s in ctx]
            else:
                diff += [{"t": "del", "s": s} for s in ol[i1:i2]] + [{"t": "add", "s": s} for s in nl[j1:j2]]
    return {**ch, "before": a and {k: a[k] for k in ("id", "fetched_at", "title", "meta", "signals")},
            "after": b and {k: b[k] for k in ("id", "fetched_at", "title", "meta", "signals")}, "diff": diff}


@app.post("/api/changes/{cid}/ack")
def ack(cid: int, value: bool = True):
    with db.connect() as con:
        con.execute("UPDATE changes SET acknowledged=? WHERE id=?", (int(value), cid))
    return {"ok": True}


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
        return db.rows(con.execute("SELECT * FROM ai_results WHERE run_id=? AND question_id=? ORDER BY engine",
                                   (run_id, question_id)))


@app.get("/api/competitors/{cid}")
def competitor(cid: str):
    c = cfg()
    e = c.competitor(cid)
    if not e:
        raise HTTPException(404)
    with db.connect() as con:
        pages = []
        for p in e.pages:
            s = db.row(con.execute("SELECT id, fetched_at, status, title, meta, signals, error FROM snapshots "
                                   "WHERE url=? ORDER BY id DESC LIMIT 1", (p.url,)).fetchone())
            n = con.execute("SELECT COUNT(*) FROM changes WHERE url=?", (p.url,)).fetchone()[0]
            pages.append({**p.__dict__, "latest": s, "changes": n})
        ch = insights.changes(con, 365, cid, limit=100)
        ps = insights.posts(con, 3650, cid, limit=100)
        vis = insights.visibility(c, con)
    share = next((s for s in vis["share"] if s["id"] == cid), None)
    trend = [{"date": t["date"], "share": t.get(cid)} for t in vis["trend"]]
    return {**next(x for x in insights.entities(c) if x["id"] == cid), "pages_status": pages,
            "changes": ch, "posts": ps, "ai": share, "ai_trend": trend}


@app.get("/api/battlecard/{cid}", response_class=PlainTextResponse)
def battlecard(cid: str):
    """Always-fresh battlecard facts as Markdown — paste into your battlecard doc."""
    d = competitor(cid)
    lines = [f"# {d['name']} — live battlecard facts", ""]
    for p in d["pages_status"]:
        s = p.get("latest") or {}
        sig = s.get("signals") or {}
        lines += [f"## {p['kind'].title()}: {p['url']}", f"_Checked {s.get('fetched_at', 'never')}_", ""]
        if sig.get("h1"):
            lines.append(f"- **Hero:** {' / '.join(sig['h1'])}")
        if s.get("meta"):
            lines.append(f"- **Positioning (meta):** {s['meta']}")
        if sig.get("ctas"):
            lines.append(f"- **CTAs:** {', '.join(sig['ctas'])}")
        if sig.get("prices"):
            lines.append(f"- **Prices seen:** {', '.join(sig['prices'])}")
        terms = {k: v for k, v in (sig.get("terms") or {}).items() if v}
        if terms:
            lines.append("- **Message emphasis:** " + ", ".join(f"{k} ×{v}" for k, v in sorted(terms.items(), key=lambda x: -x[1])))
        lines.append("")
    if d["changes"]:
        lines += ["## Recent moves", *[f"- {c['detected_at'][:10]} · **{c['headline']}** — {c['so_what'] or c['summary']}" for c in d["changes"][:10]], ""]
    if d["posts"]:
        lines += ["## Recent content", *[f"- [{p['title']}]({p['url']})" for p in d["posts"][:10]], ""]
    if d["ai"]:
        lines += ["## AI-search presence", f"- Mentioned in {round(d['ai']['share'] * 100)}% of answers; avg rank {d['ai']['avg_rank'] or '—'}", ""]
    return "\n".join(lines)


@app.get("/api/digests")
def digests():
    with db.connect() as con:
        return db.rows(con.execute("SELECT id, created_at, period_start, period_end, headline, delivered FROM digests ORDER BY id DESC LIMIT 50"))


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


@app.post("/api/jobs/{name}")
def trigger(name: str, deliver: bool = True):
    if name not in jobs.JOBS:
        raise HTTPException(404)
    if name in jobs.running:
        return {"status": "already_running"}
    jobs.run_async(name, deliver=deliver)
    return {"status": "started", "job": name}


@app.get("/api/runs")
def runs(limit: int = 30):
    with db.connect() as con:
        r = db.rows(con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)))
    return {"runs": r, "running": jobs.running}


# ── SPA ───────────────────────────────────────────────────────────────────────
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
