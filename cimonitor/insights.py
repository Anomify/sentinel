"""Read models shared by the API, the deep dive and the digest."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from . import db, facts
from .config import Config
from .signatures import CATEGORIES

SEV_WEIGHT = {"critical": 10, "high": 5, "medium": 2, "low": 1, "noise": 0, "info": 0}
MODULE_LABEL = {"pages": "Positioning", "stack": "GTM stack", "gtm": "Tracking", "gtm_links": "Tracking", "dns": "DNS & email",
                "subdomains": "Subdomains", "radar": "Pre-launch", "hiring": "Hiring", "money": "Money & partners",
                "ads": "Ads", "content": "Content", "ai": "AI search", "product": "Product"}


def since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def entities(cfg: Config) -> list[dict]:
    return [{"id": e.id, "name": e.name, "color": e.color, "tier": e.tier, "domains": e.domains, "aliases": e.aliases,
             "is_brand": e.is_brand, "source": e.source, "pages": [p.__dict__ for p in e.pages], "feeds": [f.__dict__ for f in e.feeds]}
            for e in [cfg.brand, *cfg.competitors]]


def events(con, days=30, competitor=None, module=None, severity=None, limit=300) -> list[dict]:
    q, a = "SELECT * FROM events WHERE detected_at >= ? AND severity != 'noise'", [since(days)]
    if competitor:
        q += " AND competitor=?"; a.append(competitor)
    if module:
        mods = [module] + (["gtm_links"] if module == "gtm" else [])
        q += f" AND module IN ({','.join('?' * len(mods))})"; a += mods
    if severity:
        q += f" AND severity IN ({','.join('?' * len(severity))})"; a += severity
    return db.rows(con.execute(q + " ORDER BY detected_at DESC, id DESC LIMIT ?", [*a, limit]))


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
        "FROM ai_results GROUP BY run_id ORDER BY MIN(run_at)"))


def _dom(c: dict) -> str:
    return (c.get("domain") or urlparse(c.get("url") or "").netloc).removeprefix("www.")


def visibility(cfg: Config, con, run_id: str | None = None) -> dict:
    runs = ai_runs(con)
    empty = {"runs": [], "latest": None, "share": [], "matrix": [], "trend": [], "citations": [], "engines": [], "per_engine": {},
             "source_gaps": [], "accuracy": None}
    if not runs:
        return empty
    run_id = run_id or runs[-1]["run_id"]
    res = db.rows(con.execute("SELECT * FROM ai_results WHERE run_id=? AND error IS NULL", (run_id,)))
    ids = [e.id for e in cfg.entities]

    def share(rows):
        n = len(rows) or 1
        out = []
        for i in ids:
            ms = [(r["mentions"] or {}).get(i) or {} for r in rows]
            hit = [m for m in ms if m.get("mentioned")]
            ranks = [m["rank"] for m in hit if m.get("rank")]
            out.append({"id": i, "share": round(len(hit) / n, 3), "mentions": len(hit),
                        "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
                        "top3": sum(r <= 3 for r in ranks), "cited": sum(m.get("cited", 0) for m in ms)})
        return out

    by_q = defaultdict(list)
    for r in res:
        by_q[r["question_id"]].append(r)
    matrix = []
    for q in cfg.questions:
        rows = by_q.get(q.id, [])
        cell = {i: {r["engine"]: ((r["mentions"] or {}).get(i) or {}).get("rank") if ((r["mentions"] or {}).get(i) or {}).get("mentioned") else None
                    for r in rows} for i in ids}
        matrix.append({"id": q.id, "text": q.text, "category": q.category, "cells": cell})

    trend = []
    for rn in runs[-30:]:
        rr = db.rows(con.execute("SELECT mentions FROM ai_results WHERE run_id=? AND error IS NULL", (rn["run_id"],)))
        trend.append({"run_id": rn["run_id"], "date": rn["run_at"][:10], **{s["id"]: s["share"] for s in share(rr)}})

    domains = Counter(_dom(c) for r in res for c in (r["citations"] or []) if _dom(c))
    # Source gaps: domains cited in answers that name a competitor but not us.
    gap = Counter()
    brand_domains = tuple(cfg.brand.domains)
    for r in res:
        m = r["mentions"] or {}
        if not (m.get("__brand__") or {}).get("mentioned") and any((v or {}).get("mentioned") for k, v in m.items() if k != "__brand__"):
            for c in r["citations"] or []:
                d = _dom(c)
                if d and not d.endswith(brand_domains or ("__none__",)):
                    gap[d] += 1
    acc = [r["accuracy"] for r in res if isinstance(r.get("accuracy"), dict)]
    accuracy = None
    if acc:
        accuracy = {"score": round(sum(a.get("score", 0) for a in acc) / len(acc), 2), "n": len(acc),
                    "verdicts": dict(Counter(a.get("verdict") for a in acc)),
                    "issues": [i for a in acc for i in a.get("issues", [])][:20]}
    engines = sorted({r["engine"] for r in res})
    return {"runs": runs, "latest": next(r for r in runs if r["run_id"] == run_id), "engines": engines,
            "share": share(res), "per_engine": {e: share([r for r in res if r["engine"] == e]) for e in engines},
            "matrix": matrix, "trend": trend,
            "citations": [{"domain": d, "count": n} for d, n in domains.most_common(15)],
            "source_gaps": [{"domain": d, "count": n} for d, n in gap.most_common(12)], "accuracy": accuracy}


def gaps(cfg: Config, vis: dict) -> list[dict]:
    """Questions where a competitor shows up and we don't, the AI-search to-do list."""
    out = []
    for row in vis.get("matrix", []):
        ours = [r for r in (row["cells"].get("__brand__") or {}).values() if r]
        present = [cid for cid, v in row["cells"].items() if cid != "__brand__" and any(v.values())]
        if not ours and present:
            out.append({"id": row["id"], "text": row["text"], "category": row["category"], "competitors": present})
    return out


def launch_scores(cfg: Config, con) -> dict:
    return {c.id: db.get_meta(con, f"launch:{c.id}") or {"probability": 0, "signals": [], "horizon": "-", "n": 0} for c in cfg.competitors}


def overview(cfg: Config, con, days=7) -> dict:
    ev = events(con, days, limit=2000)
    prev = db.rows(con.execute("SELECT severity, competitor, module FROM events WHERE detected_at >= ? AND detected_at < ?",
                               (since(days * 2), since(days))))
    ps = posts(con, days)
    vis = visibility(cfg, con)
    launch = launch_scores(cfg, con)
    comp = []
    for c in cfg.competitors:
        mine = [x for x in ev if x["competitor"] == c.id]
        heat = sum(SEV_WEIGHT.get(x["severity"], 1) for x in mine) + 1.5 * sum(p["competitor"] == c.id for p in ps)
        prev_heat = sum(SEV_WEIGHT.get(x["severity"], 1) for x in prev if x["competitor"] == c.id)
        sov = next((s for s in vis["share"] if s["id"] == c.id), None)
        comp.append({"id": c.id, "name": c.name, "color": c.color, "tier": c.tier, "changes": len(mine),
                     "critical": sum(x["severity"] in ("critical", "high") for x in mine),
                     "posts": sum(p["competitor"] == c.id for p in ps), "heat": round(heat, 1),
                     "heat_delta": round(heat - prev_heat, 1), "ai_share": sov["share"] if sov else None,
                     "launch": launch[c.id].get("probability", 0), "latest": mine[0] if mine else None,
                     "modules": dict(Counter(MODULE_LABEL.get(x["module"], x["module"]) for x in mine))})
    comp.sort(key=lambda x: -x["heat"])
    span = max(days * 2, 28)
    start = datetime.now(timezone.utc).date() - timedelta(days=span - 1)
    buckets = {(start + timedelta(d)).isoformat(): defaultdict(float) for d in range(span)}
    for x in db.rows(con.execute("SELECT competitor, detected_at, severity FROM events WHERE detected_at >= ?", (start.isoformat(),))):
        b = buckets.get(x["detected_at"][:10])
        if b is not None:
            b[x["competitor"]] += SEV_WEIGHT.get(x["severity"], 1)
    for p in db.rows(con.execute("SELECT competitor, first_seen FROM posts WHERE first_seen >= ?", (start.isoformat(),))):
        b = buckets.get(p["first_seen"][:10])
        if b is not None:
            b[p["competitor"]] += 1.5
    brand = next((s for s in vis["share"] if s["id"] == "__brand__"), None)
    last_run = db.row(con.execute("SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone())
    n_facts = con.execute("SELECT COUNT(*) FROM facts WHERE removed_at IS NULL").fetchone()[0]
    by_module = Counter(MODULE_LABEL.get(x["module"], x["module"]) for x in ev)
    ranked = sorted(ev, key=lambda x: (-SEV_WEIGHT.get(x["severity"], 0), x["detected_at"]), reverse=False)
    return {
        "days": days,
        "kpis": {
            "changes": len(ev), "critical": sum(x["severity"] in ("critical", "high") for x in ev),
            "pricing": sum((x.get("data") or {}).get("category") == "pricing" for x in ev), "posts": len(ps),
            "changes_prev": len(prev), "ai_share": brand["share"] if brand else None,
            "ai_share_prev": (vis["trend"][-2].get("__brand__") if len(vis["trend"]) > 1 else None),
            "ai_gaps": len(gaps(cfg, vis)), "pages": sum(len(c.pages) for c in cfg.competitors),
            "feeds": sum(len(c.feeds) for c in cfg.competitors), "questions": len(cfg.questions),
            "launch_max": max((v.get("probability", 0) for v in launch.values()), default=0),
            "facts": n_facts,
        },
        "competitors": comp, "timeline": [{"date": d, **v} for d, v in buckets.items()],
        "top_events": ranked[:10], "by_module": dict(by_module), "recent_posts": ps[:8],
        "share": vis["share"], "last_run": last_run, "launch": launch,
    }


# ── module views ─────────────────────────────────────────────────────────────
def stack_matrix(cfg: Config, con) -> dict:
    rows, cats = [], defaultdict(set)
    for c in cfg.competitors:
        tools = facts.active(con, c.id, "stack", "tool")
        motion = facts.active(con, c.id, "stack", "motion")
        for t in tools:
            cats[t["value"]["category"]].add(t["key"])
        rows.append({"id": c.id, "tools": {t["key"]: {"label": t["label"], "category": t["value"]["category"], "first_seen": t["first_seen"],
                                                      "confidence": t["confidence"], "phases": t["value"].get("phases"),
                                                      "pre_consent": t["value"].get("fires_before_consent", False)} for t in tools},
                     "motion": motion[0] if motion else None,
                     "conversions": [f["key"] for f in facts.active(con, c.id, "gtm", "conversion")],
                     "conversion_paths": [f["label"] for f in facts.active(con, c.id, "stack", "conversion_path")],
                     "sgtm": [f["key"] for f in facts.active(con, c.id, "gtm", "sgtm")],
                     "ids": [f["label"] for f in facts.active(con, c.id, "gtm", "tracking_id")],
                     "third_party": len(facts.active(con, c.id, "stack", "third_party"))})
    order = [k for k in CATEGORIES if k in cats]
    return {"categories": [{"id": k, "label": CATEGORIES[k], "tools": sorted(cats[k])} for k in order], "rows": rows}


def hiring_view(cfg: Config, con) -> dict:
    out = []
    for c in cfg.competitors:
        jobs = facts.active(con, c.id, "hiring", "job")
        series = facts.series(con, c.id, "hiring", "posted:")
        by_month = defaultdict(dict)
        for s in series:
            by_month[s["period"]][s["metric"].split(":", 1)[1]] = s["value"]
        out.append({"id": c.id, "open": len(jobs), "functions": dict(Counter(j["value"]["function"] for j in jobs)),
                    "regions": dict(Counter(j["value"]["region"] for j in jobs)),
                    "seniority": dict(Counter(j["value"]["seniority"] for j in jobs)),
                    "tech": Counter(t for j in jobs for t in j["value"].get("tech", [])).most_common(10),
                    "posted": [{"month": m, **v} for m, v in sorted(by_month.items())][-18:],
                    "jobs": [{"title": j["label"], **{k: j["value"].get(k) for k in ("function", "seniority", "region", "location", "url", "posted", "tech")},
                              "first_seen": j["first_seen"]} for j in sorted(jobs, key=lambda j: j["value"].get("posted") or "", reverse=True)],
                    "boards": [f["label"] for f in facts.active(con, c.id, "hiring", "board")]})
    firsts = db.rows(con.execute("SELECT * FROM events WHERE kind='first_role' ORDER BY detected_at DESC LIMIT 30"))
    return {"competitors": out, "firsts": firsts}


def radar_view(cfg: Config, con) -> dict:
    out = []
    for c in cfg.competitors:
        lp = db.get_meta(con, f"launch:{c.id}") or {"probability": 0, "signals": [], "horizon": "-"}
        hist = [{"date": s["period"], "p": s["value"]} for s in facts.series(con, c.id, "radar", "launch_probability")]
        pubs = sorted({s["period"] for s in facts.series(con, c.id, "radar", "publish") if s["metric"] == "publish"})
        out.append({"id": c.id, "launch": lp, "history": hist[-60:], "publishes": pubs[-40:],
                    "staging": [{"host": f["key"], **f["value"]} for f in facts.active(con, c.id, "radar", "staging_site")],
                    "staging_pages": [{"path": f["label"], "first_seen": f["first_seen"], **f["value"]} for f in facts.active(con, c.id, "radar", "staging_page")],
                    "new_pages": [{"path": f["label"], "first_seen": f["first_seen"]} for f in
                                  sorted(facts.active(con, c.id, "radar", "site_page"), key=lambda f: f["first_seen"], reverse=True)[:15]],
                    "repos": [{"name": f["label"], **f["value"], "first_seen": f["first_seen"]} for f in
                              sorted(facts.active(con, c.id, "radar", "repo"), key=lambda f: f["value"].get("pushed_at") or "", reverse=True)[:12]],
                    "campaign_subdomains": [{"host": f["key"], "first_seen": f["first_seen"], **{k: f["value"].get(k) for k in ("hosting", "title", "screenshot", "first_cert")}}
                                            for f in facts.active(con, c.id, "subdomains", "subdomain") if f["value"].get("kind") == "campaign / product"
                                            and not (f["value"].get("private") or f["value"].get("internal") or "not contacted" in (f["value"].get("note") or ""))]})
    out.sort(key=lambda r: -r["launch"].get("probability", 0))
    return {"competitors": out}


def positioning_view(cfg: Config, con) -> dict:
    out = []
    for c in cfg.competitors:
        snaps = db.rows(con.execute("SELECT fetched_at, signals, kind FROM snapshots WHERE competitor=? AND error IS NULL AND signals IS NOT NULL ORDER BY id", (c.id,)))
        latest: dict = {}
        hist = []
        for s in snaps:
            sig = s["signals"] or {}
            if sig.get("personas") is not None:
                latest[s["kind"]] = sig
                hist.append({"date": s["fetched_at"][:10], **{k: v for k, v in (sig.get("personas") or {}).items()}})
        agg = lambda key: dict(sum((Counter(v.get(key) or {}) for v in latest.values()), Counter()).most_common(8))  # noqa: E731
        posts_ = db.rows(con.execute("SELECT ctype, published, first_seen FROM posts WHERE competitor=?", (c.id,)))
        cad = defaultdict(Counter)
        for p in posts_:
            m = (p["published"] or p["first_seen"] or "")[:7]
            if m >= (datetime.now(timezone.utc) - timedelta(days=370)).strftime("%Y-%m"):
                cad[m][p["ctype"] or "Blog"] += 1
        out.append({"id": c.id, "personas": agg("personas"), "industries": agg("industries"), "use_cases": agg("use_cases"),
                    "persona_history": hist[-40:], "cadence": [{"month": m, **dict(v)} for m, v in sorted(cad.items())],
                    "hero": next((v.get("h1", [None])[0] for k, v in latest.items() if k == "homepage"), None)})
    return {"competitors": out}
