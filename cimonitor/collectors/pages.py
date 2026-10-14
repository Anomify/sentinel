"""Snapshot competitor pages, extract structured signals, and detect meaningful changes."""
from __future__ import annotations

import difflib
import hashlib
import logging
import re

from bs4 import BeautifulSoup

from .. import db, llm
from ..config import Config, Entity, Page
from .fetch import Fetcher

log = logging.getLogger(__name__)

PRICE_RE = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM])?|\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR))"
    r"(?:\s?(?:/|per)\s?(?:mo(?:nth)?|yr|year|user|seat|request|call|1[,.]?000|million|M|K|GB|hour|text record|unit)[\w ]{0,20})?",
    re.I,
)
CTA_RE = re.compile(r"(?i)\b(book|request|get|start|try|schedule|talk|contact|see|watch|download|sign up|join)\b")
NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe", "template"]


def extract(html: str, cfg: Config, focus: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    meta = ""
    m = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if m and m.get("content"):
        meta = m["content"].strip()
    for t in soup(NOISE_TAGS):
        t.decompose()
    for sel in ["[class*=cookie]", "[id*=cookie]", "[class*=consent]", "[id*=onetrust]"]:
        for t in soup.select(sel):
            t.decompose()

    h1 = [_clean(h.get_text(" ")) for h in soup.find_all("h1")][:3]
    h2 = [_clean(h.get_text(" ")) for h in soup.find_all(["h2", "h3"])][:25]
    ctas = []
    for a in soup.find_all(["a", "button"]):
        t = _clean(a.get_text(" "))
        cls = " ".join(a.get("class") or [])
        if 2 <= len(t) <= 40 and (CTA_RE.search(t) and ("btn" in cls or "button" in cls or a.name == "button")):
            ctas.append(t)
    ctas = list(dict.fromkeys(ctas))[:10]

    # Visible text as block-level lines (keeps diffs readable).
    body = soup.body or soup
    lines = []
    for el in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "blockquote", "figcaption", "span", "a", "div"]):
        if el.find(["p", "li", "h1", "h2", "h3", "h4", "div", "td"]):
            continue  # only leaf-ish blocks
        t = _clean(el.get_text(" "))
        if len(t) >= 3:
            lines.append(t)
    lines = list(dict.fromkeys(lines))
    ignore = [re.compile(p) for p in cfg.ignore_patterns]
    lines = [l for l in lines if not any(p.search(l) for p in ignore)]
    if focus:
        fr = re.compile(focus)
        # keep matching lines plus a little context
        keep = set()
        for i, l in enumerate(lines):
            if fr.search(l):
                keep.update(range(max(0, i - 3), min(len(lines), i + 12)))
        lines = [lines[i] for i in sorted(keep)]
    text = "\n".join(lines)
    # "$100M raised" is funding, not pricing: drop bare amounts with a magnitude suffix.
    prices = sorted({_clean(p) for p in PRICE_RE.findall(text) if not re.search(r"\d\s?[kKmMbB]$", _clean(p))})[:40]
    low = text.lower()
    terms = {t: low.count(t.lower()) for t in cfg.watch_terms}
    return {
        "title": title, "meta": meta, "text": text,
        "signals": {"h1": h1, "headings": h2, "ctas": ctas, "prices": prices, "terms": terms,
                    "words": len(text.split())},
    }


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def signal_delta(old: dict, new: dict, old_meta: dict, new_meta: dict) -> dict:
    d = {}
    for k in ("h1", "headings", "ctas", "prices"):
        a, b = set(old.get(k, [])), set(new.get(k, []))
        if a != b:
            d[k] = {"removed": sorted(a - b), "added": sorted(b - a)}
    for k in ("title", "meta"):
        if (old_meta.get(k) or "") != (new_meta.get(k) or ""):
            d[k] = {"from": old_meta.get(k), "to": new_meta.get(k)}
    shifts = {}
    for t, n in (new.get("terms") or {}).items():
        o = (old.get("terms") or {}).get(t, 0)
        if n != o and (o == 0 or n == 0 or abs(n - o) >= 2):
            shifts[t] = {"from": o, "to": n}
    if shifts:
        d["terms"] = shifts
    return d


def heuristic(kind: str, delta: dict, ratio: float) -> tuple[str, str, str]:
    """(severity, category, headline) without an LLM."""
    if "prices" in delta:
        return "critical", "pricing", "Pricing changed"
    if kind == "pricing" and ratio > 0.02:
        return "high", "pricing", "Pricing page copy changed"
    if "h1" in delta:
        new = (delta["h1"]["added"] or ["(removed)"])[0]
        return "high", "messaging", f"New hero headline: “{new[:70]}”"
    if "title" in delta or "meta" in delta:
        return "medium", "positioning", "Page title / meta description rewritten"
    if "terms" in delta:
        new_terms = [t for t, v in delta["terms"].items() if v["from"] == 0]
        if new_terms:
            return "medium", "messaging", f"Started talking about {', '.join(new_terms[:3])}"
    if "ctas" in delta:
        return "medium", "messaging", "Calls-to-action changed"
    if "headings" in delta:
        return ("medium" if ratio > 0.1 else "low"), "product", "Section headings changed"
    return ("medium" if ratio > 0.25 else "low"), "product", "Page content updated"


def check_page(con, cfg: Config, fetcher: Fetcher, comp: Entity, page: Page) -> dict:
    f = fetcher.get(page.url)
    if f.error or not f.html:
        db.insert(con, "snapshots", {"competitor": comp.id, "url": page.url, "kind": page.kind, "fetched_at": db.now(),
                                     "status": f.status, "error": f.error or "empty"})
        return {"url": page.url, "status": "error", "error": f.error}

    ex = extract(f.html, cfg, page.focus)
    h = hashlib.sha256(ex["text"].encode()).hexdigest()
    prev = db.row(con.execute(
        "SELECT * FROM snapshots WHERE url=? AND error IS NULL ORDER BY id DESC LIMIT 1", (page.url,)).fetchone())
    if prev and prev["hash"] == h:
        con.execute("UPDATE snapshots SET fetched_at=? WHERE id=?", (db.now(), prev["id"]))  # touch
        return {"url": page.url, "status": "unchanged"}

    sid = db.insert(con, "snapshots", {
        "competitor": comp.id, "url": page.url, "kind": page.kind, "fetched_at": db.now(), "status": f.status,
        "hash": h, "title": ex["title"], "meta": ex["meta"], "signals": ex["signals"], "text": ex["text"],
    })
    if not prev:
        return {"url": page.url, "status": "baseline"}

    old_lines, new_lines = prev["text"].splitlines(), ex["text"].splitlines()
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    ratio = 1 - sm.ratio()
    removed, added = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("replace", "delete"):
            removed += old_lines[i1:i2]
        if op in ("replace", "insert"):
            added += new_lines[j1:j2]
    delta = signal_delta(prev["signals"] or {}, ex["signals"], prev, ex)
    if ratio < cfg.settings.get("fetch", {}).get("min_change_ratio", 0.01) and not delta:
        return {"url": page.url, "status": "minor", "ratio": ratio}

    severity, category, headline = heuristic(page.kind, delta, ratio)
    summary = f"{len(added)} lines added, {len(removed)} removed ({ratio:.0%} of page)."
    so_what = action = None
    ai = llm.analyze_change(cfg, comp.name, page.url, page.kind, removed, added, delta)
    if ai:
        severity, category, headline = ai["severity"], ai["category"], ai["headline"]
        summary, so_what, action = ai["summary"], ai["so_what"], ai["action"]
        if severity == "noise":
            return {"url": page.url, "status": "noise"}

    db.insert(con, "changes", {
        "competitor": comp.id, "url": page.url, "kind": page.kind, "detected_at": db.now(),
        "severity": severity, "category": category, "headline": headline, "summary": summary,
        "so_what": so_what, "action": action, "added": added[:200], "removed": removed[:200],
        "signals": delta, "change_ratio": round(ratio, 4), "prev_snapshot": prev["id"], "snapshot": sid,
    })
    return {"url": page.url, "status": "changed", "severity": severity}


def run(cfg: Config, only: str | None = None) -> dict:
    results = []
    with db.connect() as con, Fetcher(cfg.settings) as fetcher:
        for comp in cfg.competitors:
            if only and comp.id != only:
                continue
            for page in comp.pages:
                try:
                    r = check_page(con, cfg, fetcher, comp, page)
                except Exception as e:
                    log.exception("page check failed: %s", page.url)
                    r = {"url": page.url, "status": "error", "error": str(e)}
                log.info("%-10s %s", r["status"], page.url)
                results.append(r)
                con.commit()
    return {"pages": len(results), "changed": sum(r["status"] == "changed" for r in results),
            "errors": sum(r["status"] == "error" for r in results), "results": results}
