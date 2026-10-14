"""Workspaces (multi-tenancy) by isolation.

Each workspace has its own config directory and its own database (a SQLite file,
or a Postgres schema). The "default" workspace maps to ./config and ./data so a
single-tenant install needs no setup at all.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE_CONFIG = Path(os.environ.get("SENTINEL_CONFIG_DIR", ROOT / "config"))
BASE_DATA = Path(os.environ.get("SENTINEL_DATA_DIR", ROOT / "data"))
DEFAULT = "default"
_current: ContextVar[str] = ContextVar("workspace", default=DEFAULT)
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def current() -> str:
    return _current.get()


@contextmanager
def use(slug: str):
    tok = _current.set(slug)
    try:
        yield
    finally:
        _current.reset(tok)


def config_dir(slug: str | None = None) -> Path:
    slug = slug or current()
    return BASE_CONFIG if slug == DEFAULT else BASE_DATA / "workspaces" / slug / "config"


def data_dir(slug: str | None = None) -> Path:
    slug = slug or current()
    d = BASE_DATA if slug == DEFAULT else BASE_DATA / "workspaces" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── registry ──────────────────────────────────────────────────────────────────
def _registry_path() -> Path:
    BASE_DATA.mkdir(parents=True, exist_ok=True)
    return BASE_DATA / "workspaces.yaml"


def _load() -> dict:
    p = _registry_path()
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def _save(reg: dict) -> None:
    _registry_path().write_text(yaml.safe_dump(reg, sort_keys=False))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def list_workspaces() -> list[dict]:
    reg = _load()
    out = [{"slug": DEFAULT, "name": reg.get(DEFAULT, {}).get("name", "Default workspace")}]
    out += [{"slug": s, "name": w.get("name", s)} for s, w in reg.items() if s != DEFAULT]
    return out


def create(slug: str, name: str, brand: dict | None = None) -> str:
    """Create a workspace seeded from the default config; returns its access token (shown once)."""
    if not SLUG.match(slug) or slug == DEFAULT:
        raise ValueError("slug must be lowercase letters, digits and dashes")
    reg = _load()
    if slug in reg:
        raise ValueError("workspace exists")
    cdir = config_dir(slug)
    cdir.mkdir(parents=True, exist_ok=True)
    for f in ("settings.yaml", "questions.yaml"):
        if (BASE_CONFIG / f).exists():
            shutil.copy(BASE_CONFIG / f, cdir / f)
    wl = {"brand": brand or {"name": name, "domains": []}, "watch_terms": [], "ignore_patterns": [], "competitors": []}
    if (BASE_CONFIG / "watchlist.yaml").exists():
        base = yaml.safe_load((BASE_CONFIG / "watchlist.yaml").read_text()) or {}
        wl["watch_terms"], wl["ignore_patterns"] = base.get("watch_terms", []), base.get("ignore_patterns", [])
    (cdir / "watchlist.yaml").write_text(yaml.safe_dump(wl, sort_keys=False))
    token = "sk_ws_" + secrets.token_urlsafe(24)
    reg[slug] = {"name": name, "token_sha256": _hash(token)}
    _save(reg)
    return token


def authorize(slug: str, token: str, admin_token: str | None) -> bool:
    """Admin token opens every workspace; a workspace token opens only its own."""
    if admin_token and secrets.compare_digest(token, admin_token):
        return True
    w = _load().get(slug)
    return bool(w and token and secrets.compare_digest(_hash(token), w.get("token_sha256", "")))


def exists(slug: str) -> bool:
    return slug == DEFAULT or slug in _load()
