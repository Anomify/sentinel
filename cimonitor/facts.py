"""The fact store: one mechanism for change detection across every module.

A collector reports the *complete* set of facts it observed for (competitor, module, kinds).
sync() compares with what's active in the database:
  • new key        → fact inserted, "added" event
  • missing key    → fact marked removed, "removed" event
  • changed value  → fact updated, "changed" event (only for kinds that opt in)
Every fact carries a confidence label (confirmed / likely / inferred) and an evidence
trail (source URL, timestamp, method, optional screenshot) so every claim is auditable.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Callable

from . import db

CONFIRMED, LIKELY, INFERRED = "confirmed", "likely", "inferred"


@dataclass
class Fact:
    kind: str
    key: str
    label: str
    value: dict = field(default_factory=dict)
    confidence: str = CONFIRMED
    evidence: list[dict] = field(default_factory=list)


def ev(url: str | None, method: str, note: str | None = None, screenshot: str | None = None) -> dict:
    e = {"url": url, "observed_at": db.now(), "method": method}
    if note:
        e["note"] = note
    if screenshot:
        e["screenshot"] = screenshot
    return e


@dataclass
class Rule:
    """How a fact change becomes an event."""
    severity: str = "medium"
    on_add: bool = True
    on_remove: bool = True
    on_change: bool = False
    title_add: Callable[[Fact], str] | None = None
    title_remove: Callable[[dict], str] | None = None
    so_what: Callable[[Fact], str | None] | None = None
    severity_fn: Callable[[Fact], str] | None = None
    alert_if: Callable[[Fact], bool] | None = None   # extra gate on "added" alerts (fact is still recorded)
    # History-like sources (news, release notes, posts): an item dropping out of a feed or search is not a removal.
    append_only: bool = False
    remove_after: int = 2   # consecutive complete reads a fact must be missing from before it counts as removed


# A fact that comes back this soon after being marked removed was a collection gap, not news: restore it quietly.
REAPPEAR_QUIET_DAYS = 30


KIND_TITLE = {"mx": "Mail routing", "dmarc": "DMARC policy", "ns": "Nameservers", "motion": "GTM motion", "funnel": "Funnel",
              "container": "GTM container", "ad_channel": "Ad channel"}


def active(con, competitor: str, module: str | None = None, kind: str | None = None) -> list[dict]:
    q, a = "SELECT * FROM facts WHERE competitor=? AND removed_at IS NULL", [competitor]
    if module:
        q += " AND module=?"; a.append(module)
    if kind:
        q += " AND kind=?"; a.append(kind)
    return db.rows(con.execute(q + " ORDER BY first_seen", a))


def history(con, competitor: str, module: str | None = None, kind: str | None = None) -> list[dict]:
    q, a = "SELECT * FROM facts WHERE competitor=?", [competitor]
    if module:
        q += " AND module=?"; a.append(module)
    if kind:
        q += " AND kind=?"; a.append(kind)
    return db.rows(con.execute(q + " ORDER BY first_seen", a))


def emit(con, competitor: str, module: str, kind: str, severity: str, title: str, detail: str = "",
         confidence: str = CONFIRMED, evidence: list | None = None, data: dict | None = None,
         so_what: str | None = None, change_id: int | None = None) -> int:
    # Date the event by when it happened (article / post / release date) when we know it, not when we saw it.
    # Anything that happened more than 30 days ago is history, not news: never Critical or High.
    happened = _happened(data or {})
    if happened and happened < (datetime.now(timezone.utc) - timedelta(days=30)).isoformat() and severity in ("critical", "high"):
        severity = "low"
    return db.insert(con, "events", {
        "competitor": competitor, "module": module, "kind": kind, "severity": severity, "title": title,
        "detail": detail, "so_what": so_what, "confidence": confidence, "evidence": evidence or [],
        "data": data or {}, "detected_at": happened or db.now(), "change_id": change_id,
    })


def _happened(data: dict) -> str | None:
    d = str(data.get("published") or data.get("date") or "")
    if not re.match(r"\d{4}-\d{2}-\d{2}", d):
        return None
    d = d[:25]
    return d if "T" in d else d + "T00:00:00+00:00"


def sync(con, competitor: str, module: str, observed: list[Fact], kinds: list[str],
         rules: dict[str, Rule] | None = None, baseline_quiet: bool = True, unread=()) -> dict:
    """Reconcile observed facts for the given kinds. Returns counts.

    baseline_quiet: the first time a module runs for a competitor we record facts
    without alerting (otherwise day one is 300 "new subdomain" alerts).
    unread: kinds the collector could not read completely this run (a page, feed or API failed):
    new facts are still added, but nothing of these kinds is counted as missing.
    """
    rules = rules or {}
    now = db.now()
    existing = {(f["kind"], f["key"]): f for f in active(con, competitor, module) if f["kind"] in kinds}
    first_run = baseline_quiet and not con.execute(
        "SELECT 1 FROM facts WHERE competitor=? AND module=? LIMIT 1", (competitor, module)).fetchone()
    seen, added, removed, changed, restored, pending = set(), 0, 0, 0, 0, 0
    obs_by_key = {}
    for f in observed:
        obs_by_key[(f.kind, f.key)] = f  # last one wins on duplicates
    for (kind, key), f in obs_by_key.items():
        seen.add((kind, key))
        rule = rules.get(kind, Rule())
        cur = existing.get((kind, key))
        if cur is None:
            prev = db.row(con.execute("SELECT * FROM facts WHERE competitor=? AND module=? AND kind=? AND key=?",
                                      (competitor, module, kind, key)).fetchone())
            if prev:  # re-appeared after removal
                db.update(con, "facts", prev["id"], {"removed_at": None, "missing": 0, "last_seen": now, "value": f.value,
                                                     "label": f.label, "confidence": f.confidence, "evidence": f.evidence})
                gone = str(prev.get("removed_at") or "")
                if gone and gone >= (datetime.now(timezone.utc) - timedelta(days=REAPPEAR_QUIET_DAYS)).isoformat():
                    restored += 1
                    continue
            else:
                db.insert(con, "facts", {"competitor": competitor, "module": module, "kind": kind, "key": key,
                                         "label": f.label, "value": f.value, "confidence": f.confidence,
                                         "evidence": f.evidence, "first_seen": now, "last_seen": now})
            added += 1
            if rule.on_add and not first_run and (rule.alert_if is None or rule.alert_if(f)):
                sev = rule.severity_fn(f) if rule.severity_fn else rule.severity
                emit(con, competitor, module, f"{kind}_added", sev,
                     rule.title_add(f) if rule.title_add else f"New {kind.replace('_', ' ')}: {f.label}",
                     confidence=f.confidence, evidence=f.evidence, data={"kind": kind, "key": key, **_slim(f.value)},
                     so_what=rule.so_what(f) if rule.so_what else None)
        else:
            upd = {"last_seen": now, "label": f.label, "confidence": f.confidence, "missing": 0}
            if json.dumps(cur["value"], sort_keys=True, default=str) != json.dumps(f.value, sort_keys=True, default=str):
                upd["value"] = f.value
                upd["evidence"] = f.evidence
                if rule.on_change and not first_run:
                    changed += 1
                    emit(con, competitor, module, f"{kind}_changed", rule.severity, f"{KIND_TITLE.get(kind, kind.replace('_', ' ').capitalize())} changed: {f.label}",
                         confidence=f.confidence, evidence=f.evidence, data={"kind": kind, "key": key, "from": _slim(cur["value"]), "to": _slim(f.value)})
            db.update(con, "facts", cur["id"], upd)
    for (kind, key), cur in existing.items():
        if (kind, key) in seen:
            continue
        rule = rules.get(kind, Rule())
        if kind in unread or rule.append_only:
            continue
        missing = (cur.get("missing") or 0) + 1
        if missing < rule.remove_after:
            db.update(con, "facts", cur["id"], {"missing": missing})
            pending += 1
            continue
        db.update(con, "facts", cur["id"], {"removed_at": now, "missing": missing})
        removed += 1
        if rule.on_remove:
            emit(con, competitor, module, f"{kind}_removed", "low" if rule.severity in ("low", "info") else "medium",
                 rule.title_remove(cur) if rule.title_remove else f"{kind.replace('_', ' ').capitalize()} removed: {cur['label']}",
                 confidence=cur["confidence"], evidence=cur["evidence"] or [], data={"kind": kind, "key": key})
    return {"facts": len(obs_by_key), "added": added, "removed": removed, "changed": changed, "baseline": first_run,
            "restored": restored, "pending_removal": pending}


def _slim(v: dict) -> dict:
    return {k: x for k, x in (v or {}).items() if not isinstance(x, (list, dict)) or len(json.dumps(x, default=str)) < 400}


def metric(con, competitor: str, module: str, metric_: str, period: str, value: float) -> None:
    r = con.execute("SELECT id FROM metrics WHERE competitor=? AND module=? AND metric=? AND period=?",
                    (competitor, module, metric_, period)).fetchone()
    if r:
        db.update(con, "metrics", r[0], {"value": value, "recorded_at": db.now()})
    else:
        db.insert(con, "metrics", {"competitor": competitor, "module": module, "metric": metric_, "period": period,
                                   "value": value, "recorded_at": db.now()})


def series(con, competitor: str | None, module: str, metric_prefix: str = "") -> list[dict]:
    q, a = "SELECT competitor, metric, period, value FROM metrics WHERE module=?", [module]
    if competitor:
        q += " AND competitor=?"; a.append(competitor)
    if metric_prefix:
        q += " AND metric LIKE ?"; a.append(metric_prefix + "%")
    return db.rows(con.execute(q + " ORDER BY period", a))
