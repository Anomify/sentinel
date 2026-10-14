"""Read models shared by the API and the digest."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import db
from .config import Config

SEV_WEIGHT = {"critical": 10, "high": 5, "medium": 2, "low": 1, "noise": 0}


def since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def entities(cfg: Config) -> list[dict]:
    return [{"id": e.id, "name": e.name, "color": e.color, "tier": e.tier, "domains": e.domains,
             "is_brand": e.is_brand, "aliases": e.aliases, "pages": [p.__dict__ for p in e.pages], "feeds": [f.__dict__ for f in e.feeds]}
            for e in cfg.entities]


def changes(con, days=30, competitor=None, severity=None, limit=200) -> list[dict]:
    q, a = "SELECT * FROM changes WHERE detected_at >= ?", [since(days)]
    if competitor:
        q += " AND competitor=?"; a.append(competitor)
    if severity:
        q += f" AND severity IN ({','.join('?' * len(severity))})"; a += severity
    return db.rows(con.execute(q + " ORDER BY detected_at DESC LIMIT ?", [*a, limit]))


def posts(con, days=30, competitor=None, limit=200) -> list[dict]:
    q, a = "SELECT * FROM posts WHERE first_seen >= ?", [since(days)]
    if competitor:
        q += " AND competitor=?"; a.append(competitor)
    return db.rows(con.execute(q + " ORDER BY COALESCE(published, first_seen) DESC LIMIT ?", [*a, limit]))


def ai_runs(con) -> list[dict]:
    return db.rows(con.execute(
        "SELECT run_id, MIN(run_at) run_at, COUNT(*) answers, GROUP_CONCAT(DISTINCT engine) engines "
        "FROM ai_results GROUP BY run_id ORDER BY run_at"))


def visibility(cfg: Config, con, run_id: str | None = None) -> dict:
    runs = ai_runs(con)
    if not runs:
        return {"runs": [], "latest": None, "share": [], "matrix": [], "trend": [], "citations": []}
    run_id = run_id or runs[-1]["run_id"]
    res = db.rows(con.execute("SELECT * FROM ai_results WHERE run_id=? AND error IS NULL", (run_id,)))
    ids = [e.id for e in cfg.entities]

    def share(rows):
        n = len(rows) or 1
        out = []
        for i in ids:
            ms = [r["mentions"].get(i) or {} for r in rows]
            hit = [m for m in ms if m.get("mentioned")]
            ranks = [m["rank"] for m in hit if m.get("rank")]
            out.append({"id": i, "share": round(len(hit) / n, 3), "mentions": len(hit),
                        "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
                        "top3": sum(r <= 3 for r in ranks), "cited": sum(m.get("cited", 0) for m in ms)})
        return out

    matrix = []
    by_q = defaultdict(list)
    for r in res:
        by_q[r["question_id"]].append(r)
    for q in cfg.questions:
        rows = by_q.get(q.id, [])
        cell = {}
        for i in ids:
            ms = [(r["engine"], r["mentions"].get(i) or {}) for r in rows]
            cell[i] = {e: m.get("rank") if m.get("mentioned") else None for e, m in ms}
        matrix.append({"id": q.id, "text": q.text, "category": q.category, "cells": cell,
                       "answers": [{"engine": r["engine"], "id": r["id"]} for r in rows]})

    trend = []
    for rn in runs[-12:]:
        rr = db.rows(con.execute("SELECT mentions FROM ai_results WHERE run_id=? AND error IS NULL", (rn["run_id"],)))
        trend.append({"run_id": rn["run_id"], "date": rn["run_at"][:10],
                      **{s["id"]: s["share"] for s in share(rr)}})

    domains = defaultdict(int)
    for r in res:
        for c in r["citations"] or []:
            from urllib.parse import urlparse
            domains[urlparse(c["url"]).netloc.removeprefix("www.")] += 1
    top_domains = sorted(domains.items(), key=lambda x: -x[1])[:15]

    engines = sorted({r["engine"] for r in res})
    per_engine = {e: share([r for r in res if r["engine"] == e]) for e in engines}
    return {"runs": runs, "latest": next(r for r in runs if r["run_id"] == run_id), "engines": engines,
            "share": share(res), "per_engine": per_engine, "matrix": matrix, "trend": trend,
            "citations": [{"domain": d, "count": n} for d, n in top_domains]}


def gaps(cfg: Config, vis: dict) -> list[dict]:
    """Questions where a competitor shows up and we don't — the AI-search to-do list."""
    out = []
    for row in vis.get("matrix", []):
        ours = [r for r in (row["cells"].get("__brand__") or {}).values() if r]
        theirs = {cid: [r for r in v.values() if r] for cid, v in row["cells"].items() if cid != "__brand__"}
        present = [cid for cid, v in theirs.items() if v]
        if not ours and present:
            out.append({"id": row["id"], "text": row["text"], "category": row["category"], "competitors": present})
    return out


def overview(cfg: Config, con, days=7) -> dict:
    ch = changes(con, days)
    ps = posts(con, days)
    vis = visibility(cfg, con)
    prev_ch = db.rows(con.execute("SELECT severity, competitor FROM changes WHERE detected_at >= ? AND detected_at < ?",
                                  (since(days * 2), since(days))))

    comp = []
    for c in cfg.competitors:
        mine = [x for x in ch if x["competitor"] == c.id]
        heat = sum(SEV_WEIGHT.get(x["severity"], 1) for x in mine) + 1.5 * sum(p["competitor"] == c.id for p in ps)
        prev_heat = sum(SEV_WEIGHT.get(x["severity"], 1) for x in prev_ch if x["competitor"] == c.id)
        last = con.execute("SELECT MAX(fetched_at) FROM snapshots WHERE competitor=?", (c.id,)).fetchone()[0]
        sov = next((s for s in vis["share"] if s["id"] == c.id), None)
        comp.append({"id": c.id, "name": c.name, "color": c.color, "tier": c.tier, "changes": len(mine),
                     "critical": sum(x["severity"] in ("critical", "high") for x in mine),
                     "posts": sum(p["competitor"] == c.id for p in ps), "heat": round(heat, 1),
                     "heat_delta": round(heat - prev_heat, 1), "last_checked": last,
                     "ai_share": sov["share"] if sov else None, "latest": mine[0] if mine else None})
    comp.sort(key=lambda x: -x["heat"])

    # daily activity for the timeline (last N*2 days, min 28)
    span = max(days * 2, 28)
    start = datetime.now(timezone.utc).date() - timedelta(days=span - 1)
    buckets = {(start + timedelta(d)).isoformat(): defaultdict(int) for d in range(span)}
    for x in db.rows(con.execute("SELECT competitor, detected_at, severity FROM changes WHERE detected_at >= ?",
                                 (start.isoformat(),))):
        b = buckets.get(x["detected_at"][:10])
        if b is not None:
            b[x["competitor"]] += SEV_WEIGHT.get(x["severity"], 1)
    for p in db.rows(con.execute("SELECT competitor, first_seen FROM posts WHERE first_seen >= ?", (start.isoformat(),))):
        b = buckets.get(p["first_seen"][:10])
        if b is not None:
            b[p["competitor"]] += 1.5
    timeline = [{"date": d, **v} for d, v in buckets.items()]

    brand = next((s for s in vis["share"] if s["id"] == "__brand__"), None)
    last_run = db.row(con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone())
    return {
        "days": days,
        "kpis": {
            "changes": len(ch), "critical": sum(x["severity"] in ("critical", "high") for x in ch),
            "pricing": sum(x["category"] == "pricing" for x in ch), "posts": len(ps),
            "changes_prev": len(prev_ch),
            "ai_share": brand["share"] if brand else None,
            "ai_share_prev": (vis["trend"][-2].get("__brand__") if len(vis["trend"]) > 1 else None),
            "ai_gaps": len(gaps(cfg, vis)),
            "pages": sum(len(c.pages) for c in cfg.competitors), "feeds": sum(len(c.feeds) for c in cfg.competitors),
            "questions": len(cfg.questions),
        },
        "competitors": comp, "timeline": timeline, "top_changes": ch[:8], "recent_posts": ps[:8],
        "share": vis["share"], "last_run": last_run,
    }
