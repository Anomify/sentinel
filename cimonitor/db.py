"""SQLite storage. One file, zero ops."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY, competitor TEXT, url TEXT, kind TEXT, fetched_at TEXT,
  status INTEGER, hash TEXT, title TEXT, meta TEXT, signals TEXT, text TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap_url ON snapshots(url, fetched_at);

CREATE TABLE IF NOT EXISTS changes (
  id INTEGER PRIMARY KEY, competitor TEXT, url TEXT, kind TEXT, detected_at TEXT,
  severity TEXT, category TEXT, headline TEXT, summary TEXT, so_what TEXT, action TEXT,
  added TEXT, removed TEXT, signals TEXT, change_ratio REAL,
  prev_snapshot INTEGER, snapshot INTEGER, acknowledged INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_changes_time ON changes(detected_at);

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY, competitor TEXT, guid TEXT UNIQUE, title TEXT, url TEXT,
  published TEXT, summary TEXT, first_seen TEXT, topics TEXT
);
CREATE INDEX IF NOT EXISTS ix_posts_seen ON posts(first_seen);

CREATE TABLE IF NOT EXISTS ai_results (
  id INTEGER PRIMARY KEY, run_id TEXT, run_at TEXT, engine TEXT, model TEXT,
  question_id TEXT, question TEXT, answer TEXT, citations TEXT, mentions TEXT,
  brand_rank INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_ai_run ON ai_results(run_at);

CREATE TABLE IF NOT EXISTS digests (
  id INTEGER PRIMARY KEY, created_at TEXT, period_start TEXT, period_end TEXT,
  headline TEXT, html TEXT, payload TEXT, delivered TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, job TEXT, started_at TEXT, finished_at TEXT, status TEXT, stats TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

JSON_COLS = {"signals", "added", "removed", "citations", "mentions", "topics", "payload", "stats", "delivered"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_demo() -> bool:
    return os.environ.get("SENTINEL_DEMO", "").lower() in ("1", "true", "yes")


def path():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / ("demo.db" if is_demo() else "sentinel.db")


@contextmanager
def connect():
    con = sqlite3.connect(path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str) and d[k][:1] in "[{":
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]


def insert(con, table: str, data: dict) -> int:
    data = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in data.items()}
    cols = ",".join(data)
    q = ",".join("?" * len(data))
    return con.execute(f"INSERT INTO {table} ({cols}) VALUES ({q})", list(data.values())).lastrowid


def set_meta(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))


def get_meta(con, key, default=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default
