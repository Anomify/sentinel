"""Load YAML config (per workspace) into typed objects, merged with UI-added targets."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

from . import tenancy
from .tenancy import ROOT  # noqa: F401  (re-exported)


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
    # extended intelligence sources (all optional; most are auto-discovered)
    staging: list[str] = field(default_factory=list)       # public staging sites, e.g. https://acme-stg.webflow.io
    github: list[str] = field(default_factory=list)        # GitHub orgs
    ats: dict = field(default_factory=dict)                # {"greenhouse": "token"} / lever / ashby
    partner_pages: list[str] = field(default_factory=list)
    marketplaces: list[str] = field(default_factory=list)  # marketplace listing URLs
    ads: dict = field(default_factory=dict)                # {"linkedin_company_id": "...", "google_advertiser": "..."}
    news_query: str | None = None
    social: dict = field(default_factory=dict)             # {"linkedin": url, "youtube": url, ...}; auto-discovered when blank
    profile: dict = field(default_factory=dict)            # brand only: positioning, strengths, facts
    source: str = "config"                                 # config | ui

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    @property
    def domain(self) -> str:
        return self.domains[0] if self.domains else ""

    def mention_regex(self) -> re.Pattern:
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
        # AI share-of-voice counts the brand once, so the self-monitoring copy is left out here.
        return [self.brand, *(c for c in self.competitors if c.tier != "self")]

    def competitor(self, cid: str) -> Entity | None:
        return next((c for c in self.competitors if c.id == cid), None)


def _read(name: str) -> dict:
    p = tenancy.config_dir() / name
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


EXT = ("staging", "github", "ats", "partner_pages", "marketplaces", "ads", "news_query", "social")
# Palette slots (validated categorical order) for competitors added without a colour
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#c2410c", "#0e7490"]


def clean_domain(d: str) -> str:
    """'https://www.acme.com/path' → 'www.acme.com' (domains are compared as bare hostnames)."""
    return re.sub(r"^[a-z]+://", "", str(d).strip().lower()).split("/")[0]


def entity_from(c: dict, source="config") -> Entity:
    return Entity(
        id=c["id"], name=c["name"], color=c.get("color", "#888"), tier=c.get("tier", "primary"),
        aliases=c.get("aliases") or [], domains=[clean_domain(d) for d in c.get("domains") or []],
        pages=[Page(**p) for p in c.get("pages") or []], feeds=[Feed(**f) for f in c.get("feeds") or []],
        source=source, **{k: c[k] for k in EXT if c.get(k) is not None},
    )


def _ui_targets() -> list[dict]:
    from . import db  # local import: db depends on tenancy only
    try:
        with db.connect() as con:
            return [json.loads(r["config"]) for r in con.execute("SELECT config FROM targets ORDER BY id")]
    except Exception:
        return []


def load() -> Config:
    wl, qs, st = _read("watchlist.yaml"), _read("questions.yaml"), _read("settings.yaml")
    b = wl.get("brand") or {}
    brand = Entity(id="__brand__", name=b.get("name", "Your Company"), color=b.get("color", "#6250d6"),
                   aliases=b.get("aliases") or [], domains=[clean_domain(d) for d in b.get("domains") or []], is_brand=True, tier="brand",
                   profile={k: b[k] for k in ("positioning", "strengths", "products", "facts", "icp") if k in b})
    comps = [entity_from(c) for c in wl.get("competitors") or []]
    if b.get("monitor", True) and brand.domains:
        # Track ourselves with every module, exactly as if we were a competitor.
        dom = brand.domains[0]
        self_ = {"id": re.sub(r"[^a-z0-9]+", "-", brand.name.lower()).strip("-") or "us", "name": brand.name,
                 "color": brand.color, "tier": "self", "aliases": brand.aliases, "domains": brand.domains,
                 "pages": b.get("pages") or [{"kind": "homepage", "url": f"https://{dom}/"}], "feeds": b.get("feeds") or [],
                 **{k: b[k] for k in EXT if b.get(k) is not None}}
        if self_["id"] not in {c.id for c in comps}:
            comps.insert(0, entity_from(self_))
    have = {c.id for c in comps}
    for i, t in enumerate(_ui_targets()):
        if t["id"] not in have:
            t.setdefault("color", PALETTE[(len(comps) + i) % len(PALETTE)])
            comps.append(entity_from(t, "ui"))
    return Config(
        brand=brand, competitors=comps,
        watch_terms=wl.get("watch_terms") or [], ignore_patterns=wl.get("ignore_patterns") or [],
        questions=[Question(**q) for q in qs.get("questions") or []],
        engines=qs.get("engines") or {}, settings=st or {},
    )
