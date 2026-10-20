"""Storage: SQLite (zero-ops default) or Postgres (DATABASE_URL), one schema per workspace.

Code is written against SQLite-flavoured SQL; the Postgres adapter translates the
handful of dialect differences we use (placeholders, upserts, GROUP_CONCAT, DDL).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import tenancy

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY, competitor TEXT, url TEXT, kind TEXT, fetched_at TEXT,
  status INTEGER, hash TEXT, title TEXT, meta TEXT, signals TEXT, text TEXT, error TEXT, screenshot TEXT
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
  published TEXT, summary TEXT, first_seen TEXT, topics TEXT, ctype TEXT
);
CREATE INDEX IF NOT EXISTS ix_posts_seen ON posts(first_seen);

CREATE TABLE IF NOT EXISTS ai_results (
  id INTEGER PRIMARY KEY, run_id TEXT, run_at TEXT, engine TEXT, model TEXT,
  question_id TEXT, question TEXT, answer TEXT, citations TEXT, mentions TEXT,
  brand_rank INTEGER, error TEXT, accuracy TEXT
);
CREATE INDEX IF NOT EXISTS ix_ai_run ON ai_results(run_at);

CREATE TABLE IF NOT EXISTS digests (
  id INTEGER PRIMARY KEY, created_at TEXT, period_start TEXT, period_end TEXT,
  headline TEXT, html TEXT, payload TEXT, delivered TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, job TEXT, started_at TEXT, finished_at TEXT, status TEXT, stats TEXT, error TEXT
);

-- Generic observation store: every module writes facts; adds/removals become events.
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY, competitor TEXT, module TEXT, kind TEXT, key TEXT, label TEXT,
  value TEXT, confidence TEXT, evidence TEXT, first_seen TEXT, last_seen TEXT, removed_at TEXT,
  missing INTEGER DEFAULT 0,  -- consecutive complete reads without this fact
  UNIQUE (competitor, module, kind, key)
);
CREATE INDEX IF NOT EXISTS ix_facts_comp ON facts(competitor, module);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, competitor TEXT, module TEXT, kind TEXT, severity TEXT, title TEXT,
  detail TEXT, so_what TEXT, confidence TEXT, evidence TEXT, data TEXT, detected_at TEXT,
  acknowledged INTEGER DEFAULT 0, change_id INTEGER,
  occurred_at TEXT  -- when it happened (article / release date), if known; detected_at is when Sentinel found it
);
CREATE INDEX IF NOT EXISTS ix_events_time ON events(detected_at);

-- Time series (headcount by function, partner counts, launch probability…)
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY, competitor TEXT, module TEXT, metric TEXT, period TEXT, value REAL, recorded_at TEXT,
  UNIQUE (competitor, module, metric, period)
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, competitor TEXT, created_at TEXT, payload TEXT, markdown TEXT
);

-- Competitors added from the UI ("enter a domain"), merged with watchlist.yaml
CREATE TABLE IF NOT EXISTS targets (
  id INTEGER PRIMARY KEY, competitor TEXT UNIQUE, name TEXT, domain TEXT, created_at TEXT, config TEXT
);

-- Guardrail audit: every outbound decision (allowed / blocked / skipped)
CREATE TABLE IF NOT EXISTS guard_log (
  id INTEGER PRIMARY KEY, ts TEXT, host TEXT, url TEXT, action TEXT, reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_guard_ts ON guard_log(ts);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

MIGRATIONS = [  # additive columns for databases created by earlier versions
    ("snapshots", "screenshot", "TEXT"), ("posts", "ctype", "TEXT"), ("ai_results", "accuracy", "TEXT"),
    ("facts", "missing", "INTEGER DEFAULT 0"), ("events", "occurred_at", "TEXT"),
]

JSON_COLS = {"signals", "added", "removed", "citations", "mentions", "topics", "payload", "stats", "delivered",
             "value", "evidence", "data", "config", "accuracy"}

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_demo() -> bool:
    return os.environ.get("SENTINEL_DEMO", "").lower() in ("1", "true", "yes")


def path():
    return tenancy.data_dir() / ("demo.db" if is_demo() else "sentinel.db")


# ── Postgres adapter ──────────────────────────────────────────────────────────
class _Row(dict):
    """dict that also supports positional access, like sqlite3.Row."""

    def __getitem__(self, k):
        if isinstance(k, int):
            return list(self.values())[k]
        return super().__getitem__(k)


class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._c, self.lastrowid = cur, lastrowid

    @property
    def rowcount(self):
        return self._c.rowcount

    def fetchone(self):
        return self._c.fetchone() if self._c.description else None

    def fetchall(self):
        return self._c.fetchall() if self._c.description else []

    def __iter__(self):
        return iter(self.fetchall())


def _pg_sql(sql: str) -> str:
    s = sql.replace("?", "%s")
    s = re.sub(r"GROUP_CONCAT\(DISTINCT (\w+)\)", r"string_agg(DISTINCT \1, ',')", s)
    if re.match(r"\s*INSERT OR IGNORE", s, re.I):
        s = re.sub(r"INSERT OR IGNORE", "INSERT", s, flags=re.I).rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    if re.match(r"\s*INSERT OR REPLACE INTO meta", s, re.I):
        s = re.sub(r"INSERT OR REPLACE", "INSERT", s, flags=re.I) + " ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"
    return s


def _pg_ddl(sql: str) -> list[str]:
    s = sql.replace("INTEGER PRIMARY KEY", "BIGSERIAL PRIMARY KEY").replace(" REAL", " DOUBLE PRECISION")
    s = re.sub(r"--[^\n]*", "", s)
    return [x.strip() for x in s.split(";") if x.strip()]


class _PgConn:
    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, params=()):
        cur = self._c.cursor()
        cur.execute(_pg_sql(sql), tuple(params))
        return _PgCursor(cur)

    def insert_returning(self, sql, params):
        cur = self._c.cursor()
        cur.execute(_pg_sql(sql) + " RETURNING id", tuple(params))
        return cur.fetchone()["id"]

    def commit(self):
        self._c.commit()

    def close(self):
        self._c.close()


_pg_ready: set[str] = set()


def _pg_connect():
    import psycopg

    def factory(cursor):
        names = [d.name for d in cursor.description] if cursor.description else []
        return lambda values: _Row(zip(names, values))

    conn = psycopg.connect(DATABASE_URL, row_factory=factory)
    schema = "ws_" + re.sub(r"[^a-z0-9_]", "_", tenancy.current()) + ("_demo" if is_demo() else "")
    with conn.cursor() as c:
        if schema not in _pg_ready:
            c.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            c.execute(f'SET search_path TO "{schema}"')
            for stmt in _pg_ddl(SCHEMA):
                c.execute(stmt)
            for t, col, typ in MIGRATIONS:
                c.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} {typ}")
            conn.commit()
            _pg_ready.add(schema)
        c.execute(f'SET search_path TO "{schema}"')
    return _PgConn(conn)


# ── SQLite ────────────────────────────────────────────────────────────────────
_sqlite_ready: set[str] = set()


def _sqlite_connect():
    p = str(path())
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    if p not in _sqlite_ready:
        con.executescript(SCHEMA)
        for t, col, typ in MIGRATIONS:
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            if col not in cols:
                con.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
        _sqlite_ready.add(p)
    return con


@contextmanager
def connect():
    con = _pg_connect() if IS_PG else _sqlite_connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def reset_cache():
    _sqlite_ready.clear()
    _pg_ready.clear()


# ── helpers ───────────────────────────────────────────────────────────────────
def row(r) -> dict | None:
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


def _enc(v):
    return json.dumps(v, default=str) if isinstance(v, (dict, list)) else v


def insert(con, table: str, data: dict) -> int:
    data = {k: _enc(v) for k, v in data.items()}
    cols, q = ",".join(data), ",".join("?" * len(data))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({q})"
    if isinstance(con, _PgConn):
        return con.insert_returning(sql, list(data.values()))
    return con.execute(sql, list(data.values())).lastrowid


def update(con, table: str, id_: int, data: dict) -> None:
    data = {k: _enc(v) for k, v in data.items()}
    con.execute(f"UPDATE {table} SET {', '.join(f'{k}=?' for k in data)} WHERE id=?", [*data.values(), id_])


def set_meta(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))


def get_meta(con, key, default=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def backend() -> str:
    return "postgres" if IS_PG else "sqlite"
