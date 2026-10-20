"""Idempotent data repairs. Runs when the server starts and before every full refresh; safe to run any time.

Each repair removes data that today's collectors would no longer produce, so a database built by an older
version converges on what the current rules say. Nothing here contacts the network.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from . import config, db

log = logging.getLogger(__name__)
COMPANY_WIDE_MODULES = ("stack", "gtm", "gtm_links", "dns", "subdomains", "radar", "hiring", "money", "ads")


def _data(v):
    return v if isinstance(v, dict) else json.loads(v or "{}")


def scoped_noise(con, cfg) -> int:
    """AWS / Google / Azure: drop company-wide facts and anything off the product we track."""
    n = 0
    for c in cfg.competitors:
        if not c.scoped:
            continue
        ph = ",".join("?" * len(COMPANY_WIDE_MODULES))
        for t in ("facts", "events", "metrics"):
            n += con.execute(f"DELETE FROM {t} WHERE competitor=? AND module IN ({ph})", (c.id, *COMPANY_WIDE_MODULES)).rowcount
        n += con.execute("DELETE FROM meta WHERE key=?", (f"launch:{c.id}",)).rowcount
        for r in db.rows(con.execute("SELECT id, title, summary FROM posts WHERE competitor=?", (c.id,))):
            if not c.in_scope(f"{r['title']} {r['summary'] or ''}"):
                con.execute("DELETE FROM posts WHERE id=?", (r["id"],)); n += 1
        for r in db.rows(con.execute("SELECT id, title FROM events WHERE competitor=? AND module IN ('content','product','social')", (c.id,))):
            if not c.in_scope(r["title"]):
                con.execute("DELETE FROM events WHERE id=?", (r["id"],)); n += 1
        for r in db.rows(con.execute("SELECT id, key, label FROM facts WHERE competitor=? AND module IN ('product','social') AND kind != 'profile'", (c.id,))):
            if not c.in_scope(f"{r['key'].replace('-', ' ')} {r['label']}"):
                con.execute("DELETE FROM facts WHERE id=?", (r["id"],)); n += 1
    return n


def irrelevant_news(con, cfg) -> int:
    """Press, funding, launch and Hacker News items that fail today's relevance rules (namesakes, sports, politics)."""
    from .collectors import money
    n = 0
    for c in cfg.competitors:
        for t, col in (("facts", "label"), ("events", "title")):
            rows = db.rows(con.execute(
                f"SELECT id, {col} AS t, evidence FROM {t} WHERE competitor=? AND ((module='money' AND kind LIKE 'press%') OR "
                f"(module='money' AND kind LIKE 'funding%') OR (module='money' AND kind LIKE 'm_and_a%') OR "
                f"(module='money' AND kind LIKE 'arr%') OR (module='product' AND kind LIKE 'launch%') OR "
                f"(module='social' AND kind LIKE 'mention%'))", (c.id,)))
            for r in rows:
                # Judge the source headline: synthesized labels ("Series B $100M") don't name the company.
                ev = r["evidence"] if isinstance(r["evidence"], list) else json.loads(r["evidence"] or "[]")
                notes = " ".join(e.get("note") or "" for e in ev if isinstance(e, dict))
                text = re.sub(r"^(In the news|Launch announced|On Hacker News|New funding round|Funding):\s*", "", r["t"] or "")
                text = f"{text} {notes}".strip()
                if not (money.relevant(c, text) and c.in_scope(text)):
                    con.execute(f"DELETE FROM {t} WHERE id=?", (r["id"],)); n += 1
    return n


def redate_events(con) -> int:
    """Record when news-driven events happened (article date) beside when Sentinel saw them; old news is never Critical.

    Events from older versions had detected_at overwritten with the article date; their discovery date is lost,
    so they keep it and gain occurred_at.
    """
    n = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    for r in db.rows(con.execute("SELECT id, detected_at, occurred_at, severity, data FROM events")):
        d = _data(r["data"])
        happened = d.get("published") or d.get("date")
        if not happened or not re.match(r"\d{4}-\d{2}-\d{2}", str(happened)):
            continue
        happened = str(happened)[:25]
        upd = {}
        if not r["occurred_at"]:
            upd["occurred_at"] = happened if "T" in happened else happened + "T00:00:00+00:00"
        if happened < cutoff and r["severity"] in ("critical", "high"):
            upd["severity"] = "low"
        if upd:
            db.update(con, "events", r["id"], upd); n += 1
    return n


OFF_VOICE = re.compile(r"\b(sales (team|reps?|talk track|should)|SDRs?|reps\b|outbound|battlecard|renewals?|deals in flight|"
                       r"account executives?|CISOs?|regulated enterprises?|procurement)\b", re.I)


def off_voice_comments(con) -> int:
    """AI comments written before the brand facts existed assumed a sales-led enterprise vendor; clear them so they're rewritten."""
    n = 0
    for col in ("so_what",):
        for r in db.rows(con.execute(f"SELECT id, {col} AS t FROM events WHERE {col} IS NOT NULL")):
            if OFF_VOICE.search(r["t"] or ""):
                con.execute(f"UPDATE events SET {col}=NULL WHERE id=?", (r["id"],)); n += 1
    for r in db.rows(con.execute("SELECT id, so_what, action FROM changes WHERE so_what IS NOT NULL OR action IS NOT NULL")):
        if OFF_VOICE.search(f"{r['so_what'] or ''} {r['action'] or ''}"):
            con.execute("UPDATE changes SET so_what=NULL, action=NULL WHERE id=?", (r["id"],)); n += 1
    return n


def per_headline_deals(con) -> int:
    """M&A used to be stored once per news headline; it is now one fact per deal. Drop the per-headline copies."""
    n = con.execute("DELETE FROM facts WHERE module='money' AND kind='m_and_a' AND key NOT LIKE 'deal:%'").rowcount
    seen = set()
    for r in db.rows(con.execute("SELECT id, competitor, detected_at FROM events WHERE module='money' AND kind='m_and_a_added' ORDER BY detected_at")):
        k = (r["competitor"], str(r["detected_at"])[:7])
        if k in seen:
            con.execute("DELETE FROM events WHERE id=?", (r["id"],)); n += 1
        seen.add(k)
    return n


def removed_competitors(con, cfg) -> int:
    """Data for a company that is no longer on the watchlist is deleted."""
    # A missing, empty or unreadable watchlist must never look like "every company was removed".
    if not any(c.source == "config" and c.tier != "self" for c in cfg.competitors):
        log.warning("cleanup: watchlist has no competitors, skipping removed-company cleanup")
        return 0
    keep = {c.id for c in cfg.competitors} | {"__brand__"}
    n = 0
    for t in ("facts", "events", "metrics", "posts", "snapshots", "changes"):
        try:
            for (cid,) in con.execute(f"SELECT DISTINCT competitor FROM {t}").fetchall():
                if cid and cid not in keep:
                    n += con.execute(f"DELETE FROM {t} WHERE competitor=?", (cid,)).rowcount
        except Exception:
            continue
    return n


def duplicate_digests(con) -> int:
    """Keep the newest digest per period."""
    n = 0
    seen = set()
    for r in db.rows(con.execute("SELECT id, period_start, period_end FROM digests ORDER BY id DESC")):
        k = (str(r["period_start"])[:10], str(r["period_end"])[:10])
        if k in seen:
            con.execute("DELETE FROM digests WHERE id=?", (r["id"],)); n += 1
        seen.add(k)
    return n


def ai_text_dashes(con) -> int:
    """No em dashes in Sentinel's own AI-written text, including text stored before that rule. Source quotes are left alone."""
    from .llm import no_dashes
    n = 0
    for table, cols in (("events", ("so_what",)), ("changes", ("headline", "summary", "so_what", "action"))):
        for r in db.rows(con.execute(f"SELECT id, {', '.join(cols)} FROM {table} WHERE " +
                                     " OR ".join(f"{c} LIKE ?" for c in cols), ["%—%"] * len(cols))):
            con.execute(f"UPDATE {table} SET {', '.join(f'{c}=?' for c in cols)} WHERE id=?", [*(no_dashes(r[c]) for c in cols), r["id"]])
            n += 1
    return n


def story_keys(con) -> int:
    """Events stored before stories existed get their story key, so old reports group like new ones."""
    from .facts import story_key
    n = 0
    for r in db.rows(con.execute("SELECT id, kind, title, occurred_at, detected_at FROM events WHERE story IS NULL")):
        k = story_key(r["kind"], r["title"], r["occurred_at"] or r["detected_at"])
        if k:
            con.execute("UPDATE events SET story=? WHERE id=?", (k, r["id"])); n += 1
    return n


def run() -> dict:
    cfg = config.load()
    out = {}
    with db.connect() as con:
        for name, fn in (("scoped_noise", lambda: scoped_noise(con, cfg)), ("irrelevant_news", lambda: irrelevant_news(con, cfg)),
                         ("redated", lambda: redate_events(con)), ("off_voice_comments", lambda: off_voice_comments(con)),
                         ("per_headline_deals", lambda: per_headline_deals(con)),
                         ("removed_competitors", lambda: removed_competitors(con, cfg)), ("duplicate_digests", lambda: duplicate_digests(con)),
                         ("stories", lambda: story_keys(con)), ("ai_text_dashes", lambda: ai_text_dashes(con))):
            try:
                out[name] = fn()
            except Exception as e:  # a repair must never stop the app
                log.exception("cleanup %s failed", name)
                out[name] = f"error: {e}"[:200]
    log.info("cleanup %s", out)
    return out
