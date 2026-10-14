"""Load YAML config into typed objects."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("SENTINEL_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("SENTINEL_DATA_DIR", ROOT / "data"))


@dataclass
class Page:
    kind: str
    url: str
    focus: str | None = None  # regex: only keep text blocks matching this (e.g. one row of a big pricing page)


@dataclass
class Feed:
    type: str  # rss | listing
    url: str
    filter: str | None = None
    link_pattern: str | None = None


@dataclass
class Entity:
    id: str
    name: str
    color: str = "#888888"
    tier: str = "primary"
    aliases: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    feeds: list[Feed] = field(default_factory=list)
    is_brand: bool = False

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def mention_regex(self) -> re.Pattern:
        # "Alice (WonderFence)" → also match "Alice"; strip parentheticals.
        terms = {re.sub(r"\s*\(.*?\)", "", n).strip() for n in self.names} | set(self.aliases)
        terms = sorted((t for t in terms if t), key=len, reverse=True)
        return re.compile(r"(?<![\w-])(" + "|".join(re.escape(t) for t in terms) + r")(?![\w-])", re.I)


@dataclass
class Question:
    id: str
    text: str
    category: str = "General"


@dataclass
class Config:
    brand: Entity
    competitors: list[Entity]
    watch_terms: list[str]
    ignore_patterns: list[str]
    questions: list[Question]
    engines: dict
    settings: dict

    @property
    def entities(self) -> list[Entity]:
        return [self.brand, *self.competitors]

    def competitor(self, cid: str) -> Entity | None:
        return next((c for c in self.competitors if c.id == cid), None)


def _read(name: str) -> dict:
    p = CONFIG_DIR / name
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def load() -> Config:
    wl, qs, st = _read("watchlist.yaml"), _read("questions.yaml"), _read("settings.yaml")
    b = wl.get("brand") or {}
    brand = Entity(id="__brand__", name=b.get("name", "Your Company"), color=b.get("color", "#7C5CFF"),
                   aliases=b.get("aliases") or [], domains=b.get("domains") or [], is_brand=True, tier="brand")
    comps = []
    for c in wl.get("competitors") or []:
        comps.append(Entity(
            id=c["id"], name=c["name"], color=c.get("color", "#888"), tier=c.get("tier", "primary"),
            aliases=c.get("aliases") or [], domains=c.get("domains") or [],
            pages=[Page(**p) for p in c.get("pages") or []],
            feeds=[Feed(**f) for f in c.get("feeds") or []],
        ))
    return Config(
        brand=brand, competitors=comps,
        watch_terms=wl.get("watch_terms") or [], ignore_patterns=wl.get("ignore_patterns") or [],
        questions=[Question(**q) for q in qs.get("questions") or []],
        engines=qs.get("engines") or {}, settings=st or {},
    )
