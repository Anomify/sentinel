"""AI-search visibility: ask answer engines your target questions and score who shows up."""
from __future__ import annotations

import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from .. import db
from ..config import Config, Question

log = logging.getLogger(__name__)
SYSTEM = "Answer as a helpful search assistant. Name specific vendors and products where relevant."


# ── engines ───────────────────────────────────────────────────────────────────
def ask_perplexity(model: str, q: str) -> tuple[str, list[dict]]:
    r = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}"},
        json={"model": model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]},
        timeout=120,
    )
    r.raise_for_status()
    j = r.json()
    cites = [{"url": s.get("url"), "title": s.get("title")} for s in j.get("search_results") or []] or \
            [{"url": u, "title": None} for u in j.get("citations") or []]
    return j["choices"][0]["message"]["content"], cites


def ask_openai(model: str, q: str) -> tuple[str, list[dict]]:
    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={"model": model, "instructions": SYSTEM, "input": q, "tools": [{"type": "web_search"}]},
        timeout=180,
    )
    r.raise_for_status()
    text, cites = [], []
    for item in r.json().get("output", []):
        if item.get("type") != "message":
            continue
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                text.append(c.get("text", ""))
                cites += [{"url": a.get("url"), "title": a.get("title")}
                          for a in c.get("annotations", []) if a.get("type") == "url_citation"]
    return "\n".join(text), cites


def ask_claude(model: str, q: str) -> tuple[str, list[dict]]:
    import anthropic
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": q}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    for _ in range(4):  # resume server-tool turns that pause
        resp = client.messages.create(model=model, max_tokens=8000, system=SYSTEM, tools=tools, messages=messages,
                                      output_config={"effort": "low"})
        if resp.stop_reason != "pause_turn":
            break
        messages = [*messages, {"role": "assistant", "content": resp.content}]
    text, cites = [], []
    for b in resp.content:
        if b.type == "text":
            text.append(b.text)
            cites += [{"url": c.url, "title": getattr(c, "title", None)} for c in (b.citations or [])
                      if getattr(c, "url", None)]
        elif b.type == "web_search_tool_result" and isinstance(b.content, list):
            cites += [{"url": r.url, "title": r.title} for r in b.content]
    return "".join(text), cites


def ask_gemini(model: str, q: str) -> tuple[str, list[dict]]:
    """Gemini with Google Search grounding; grounding chunks are the cited sources.

    If search grounding is over quota, falls back to an ungrounded answer (the model's own
    knowledge, no citations) so visibility is still measured; that answer is labelled.
    """
    import time
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    base = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": [{"role": "user", "parts": [{"text": q}]}]}
    grounded, r = True, None
    for attempt in range(6):
        body = {**base, "tools": [{"google_search": {}}]} if grounded else base
        r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=180)
        if r.status_code == 429 and grounded and "quota" in r.text.lower():
            grounded = False          # search quota exhausted → answer without search
            continue
        if r.status_code in (429, 500, 503):
            time.sleep(3 * (attempt + 1))
            continue
        break
    r.raise_for_status()
    cand = (r.json().get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
    cites = [{"url": c["web"].get("uri"), "title": c["web"].get("title")} for c in chunks if c.get("web")]
    for c in cites:  # grounding URIs are redirect links; the title carries the source domain
        t = c.get("title") or ""
        if re.fullmatch(r"[\w.-]+\.[a-z]{2,}", t):
            c["domain"] = t
    if not grounded:
        text = "[Gemini answered without Google Search — search-grounding quota unavailable]\n" + text
    return text, cites


def ask_google_aio(model: str, q: str) -> tuple[str, list[dict]]:
    """Google AI Overviews via SerpAPI (Google has no official AIO API)."""
    j = requests.get("https://serpapi.com/search.json", params={"engine": "google", "q": q, "hl": "en", "gl": "us",
                                                                 "api_key": os.environ["SERPAPI_API_KEY"]}, timeout=90).json()
    aio = j.get("ai_overview") or {}
    if aio.get("page_token") and not aio.get("text_blocks"):
        aio = requests.get("https://serpapi.com/search.json", params={"engine": "google_ai_overview", "page_token": aio["page_token"],
                                                                     "api_key": os.environ["SERPAPI_API_KEY"]}, timeout=90).json().get("ai_overview") or {}
    if not aio:
        return "[No AI Overview shown for this query]", []

    def flatten(blocks):
        out = []
        for b in blocks or []:
            if b.get("snippet"):
                out.append(b["snippet"])
            for li in b.get("list") or []:
                out.append("- " + (li.get("title", "") + " " + li.get("snippet", "")).strip())
            out += flatten(b.get("text_blocks"))
        return out
    text = "\n".join(flatten(aio.get("text_blocks")))
    cites = [{"url": r.get("link"), "title": r.get("title")} for r in aio.get("references") or []]
    return text, cites


ENGINES = {
    "perplexity": (ask_perplexity, "PERPLEXITY_API_KEY"),
    "openai": (ask_openai, "OPENAI_API_KEY"),
    "gemini": (ask_gemini, "GEMINI_API_KEY"),
    "google_aio": (ask_google_aio, "SERPAPI_API_KEY"),
    "claude": (ask_claude, "ANTHROPIC_API_KEY"),
}


def enabled_engines(cfg: Config) -> list[tuple[str, str]]:
    out = []
    for name, conf in cfg.engines.items():
        if conf.get("enabled") and name in ENGINES and os.environ.get(ENGINES[name][1]):
            out.append((name, conf.get("model")))
    return out


# ── scoring ───────────────────────────────────────────────────────────────────
def score(cfg: Config, answer: str, cites: list[dict]) -> dict:
    """Per entity: mentioned?, first position in answer, rank among entities, citation count."""
    found = []
    for e in cfg.entities:
        m = e.mention_regex().search(answer or "")
        doms = [c["url"] for c in cites if c.get("url") and
                any((c.get("domain") or urlparse(c["url"]).netloc).endswith(d) for d in e.domains)]
        found.append({"id": e.id, "pos": m.start() if m else None, "count": len(e.mention_regex().findall(answer or "")),
                      "cited": len(doms)})
    ranked = sorted((f for f in found if f["pos"] is not None), key=lambda f: f["pos"])
    for i, f in enumerate(ranked, 1):
        f["rank"] = i
    return {f["id"]: {"mentioned": f["pos"] is not None, "rank": f.get("rank"), "count": f["count"], "cited": f["cited"]}
            for f in found}


def _one(cfg, run_id, engine, model, q: Question) -> dict:
    fn = ENGINES[engine][0]
    try:
        answer, cites = fn(model, q.text)
        mentions = score(cfg, answer, cites)
        err = None
    except Exception as e:
        log.warning("%s failed on %s: %s", engine, q.id, e)
        answer, cites, mentions, err = "", [], {}, str(e)[:500]
    seen, uniq = set(), []
    for c in cites:
        if c["url"] and c["url"] not in seen:
            seen.add(c["url"])
            uniq.append(c)
    acc = None
    if not err and (mentions.get("__brand__") or {}).get("mentioned"):
        from .. import llm
        acc = llm.judge_accuracy(cfg, q.text, answer)
    return {"run_id": run_id, "run_at": db.now(), "engine": engine, "model": model, "question_id": q.id,
            "question": q.text, "answer": answer, "citations": uniq, "mentions": mentions,
            "brand_rank": (mentions.get("__brand__") or {}).get("rank"), "error": err, "accuracy": acc}


def run(cfg: Config, limit: int | None = None) -> dict:
    engines = enabled_engines(cfg)
    if not engines:
        return {"skipped": "no AI engines enabled with API keys (set PERPLEXITY_API_KEY / OPENAI_API_KEY)"}
    run_id = uuid.uuid4().hex[:10]
    qs = cfg.questions[:limit] if limit else cfg.questions
    jobs = [(e, m, q) for e, m in engines for q in qs]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda j: _one(cfg, run_id, *j), jobs))
    with db.connect() as con:
        for r in results:
            db.insert(con, "ai_results", r)
    return {"run_id": run_id, "answers": len(results), "errors": sum(bool(r["error"]) for r in results),
            "engines": [e for e, _ in engines]}
