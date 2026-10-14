"""Illustrative demo data, written to data/demo.db (never the real database).

Used by `SENTINEL_DEMO=1 sentinel serve` so you can explore the UI before real data
has accumulated. Every change, post and AI answer here is SYNTHETIC: none of it is
an actual observation of the named companies, and the UI shows a demo banner.
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

from . import db
from .config import Config

CHANGES = [
    # (competitor, kind, severity, category, headline, summary, so_what, action, removed, added, signals)
    ("hiddenlayer", "homepage", "high", "messaging", "Hero pivots from “AI security” to “agentic AI security”",
     "Homepage H1 now leads with securing autonomous agents; model-scanning messaging pushed below the fold.",
     "They are racing to own the agent-security narrative right before our launch window.",
     "Add an ‘agents’ row to the battlecard comparing our runtime coverage to theirs.",
     ["Security for AI", "Protect your AI models from adversarial attacks"],
     ["Security for agentic AI", "Discover, test and protect every AI agent, model and MCP server"],
     {"h1": {"removed": ["Security for AI"], "added": ["Security for agentic AI"]},
      "terms": {"agentic": {"from": 1, "to": 7}, "MCP": {"from": 0, "to": 4}}}),
    ("alice", "product", "critical", "pricing", "WonderFence adds a free developer tier",
     "Product page now advertises a free tier for up to 10k guardrail calls per month with self-serve signup.",
     "Removes the friction we've been using in bottom-up deals; expect devs to trial it first.",
     "Update the pricing objection-handler and consider a matching free sandbox for launch.",
     ["Request a demo"], ["Start free: 10,000 calls / month", "No credit card required"],
     {"prices": {"removed": [], "added": ["$0 / month"]}, "ctas": {"removed": ["Request a demo"], "added": ["Start free"]}}),
    ("aws-bedrock", "pricing", "high", "pricing", "Bedrock Guardrails cuts text-filter price",
     "Content-filter pricing per 1,000 text units lowered; denied-topics unchanged.",
     "Hyperscaler price pressure makes ‘good enough’ guardrails cheaper for AWS-native buyers.",
     "Sharpen the TCO slide around multi-cloud coverage and accuracy, not unit price.",
     ["$0.75 per 1,000 text units"], ["$0.15 per 1,000 text units"],
     {"prices": {"removed": ["$0.75 per 1,000 text units"], "added": ["$0.15 per 1,000 text units"]}}),
    ("google-model-armor", "product", "medium", "product", "Model Armor adds MCP and agent screening",
     "New section describes screening tool calls and MCP traffic for agents built on Vertex.",
     "Google is bundling agent protections into the platform; buyers on GCP may see it as ‘included’.",
     "Add a ‘why not just Model Armor?’ objection to the battlecard.",
     [], ["Screen agent tool calls and MCP server responses", "Native integration with Agent Builder"],
     {"headings": {"removed": [], "added": ["Protect AI agents"]}, "terms": {"MCP": {"from": 0, "to": 3}}}),
    ("lakera", "homepage", "medium", "positioning", "Lakera reframes around Check Point platform",
     "Homepage meta description and footer now reference the Check Point AI security platform.",
     "Post-acquisition, they'll sell into Check Point's installed base with bundle pricing.",
     "Flag Check Point accounts in pipeline; prep an ‘independent vendor’ talk track.",
     ["The AI-native security platform"], ["AI security, now part of Check Point"],
     {"meta": {"from": "The AI-native security platform", "to": "AI security, now part of Check Point"}}),
    ("hiddenlayer", "product", "medium", "proof", "New customer logos on runtime security page",
     "Added two Fortune 500 financial-services logos and a 40% ‘time to detect’ stat.",
     "They are stacking FSI proof points — our strongest vertical.",
     "Ask CS for two FSI references to counter in late-stage deals.",
     [], ["Trusted by leading financial institutions", "40% faster time to detect"], {}),
    ("azure-content-safety", "product", "low", "product", "Prompt Shields copy refreshed",
     "Minor copy changes describing indirect prompt-injection detection.", None, None,
     ["Detect jailbreak attempts"], ["Detect direct and indirect prompt attacks"], {}),
    ("alice", "homepage", "high", "messaging", "Alice homepage leads with “trust & safety for GenAI”",
     "Hero and subhead now position WonderFence as the safety layer for consumer GenAI apps.",
     "Clear split: they own consumer trust & safety; we should own enterprise security buyers.",
     "Tighten our ICP language to CISO / AppSec, not T&S.",
     ["Protecting online platforms"], ["Trust and safety for every GenAI interaction"],
     {"h1": {"removed": ["Protecting online platforms"], "added": ["Trust and safety for every GenAI interaction"]}}),
    ("hiddenlayer", "product", "low", "product", "AI attack simulation page adds OWASP mapping",
     "Added a table mapping test coverage to OWASP LLM Top 10.", None, None, [], ["Mapped to OWASP Top 10 for LLMs"], {}),
    ("aws-bedrock", "product", "medium", "product", "Bedrock Guardrails announces automated reasoning checks GA",
     "Page now lists automated-reasoning hallucination checks as generally available.",
     "Hallucination detection becomes table stakes in AWS-native evaluations.",
     "Confirm our hallucination story and add proof to the comparison sheet.", [],
     ["Automated Reasoning checks — now generally available"], {}),
]

POSTS = [
    ("hiddenlayer", "Securing MCP servers: a field guide", ["MCP", "agentic"]),
    ("hiddenlayer", "2026 AI Threat Landscape Report", ["red teaming"]),
    ("hiddenlayer", "Novel indirect prompt injection in coding agents", ["prompt injection", "agentic"]),
    ("hiddenlayer", "What the EU AI Act means for model risk", ["EU AI Act", "governance"]),
    ("alice", "Introducing WonderFence for voice agents", ["guardrails", "agentic"]),
    ("alice", "Why GenAI safety needs adversarial data", ["red teaming"]),
    ("alice", "Guardrails latency benchmarks: 2026 edition", ["guardrails", "runtime"]),
    ("lakera", "Gandalf: what 50M attacks taught us", ["prompt injection"]),
    ("lakera", "Agent security after the Check Point acquisition", ["agentic"]),
    ("aws-bedrock", "Building safe agents with Bedrock Guardrails", ["guardrails", "agentic"]),
    ("aws-bedrock", "Detecting hallucinations with automated reasoning", ["guardrails"]),
    ("google-model-armor", "Model Armor now protects Agentspace", ["agentic", "runtime"]),
    ("google-model-armor", "Defending against prompt injection at Google scale", ["prompt injection"]),
    ("azure-content-safety", "Prompt Shields: indirect attack detection GA", ["prompt injection"]),
]

# baseline share of AI answers mentioning each entity, and drift per run
AI_BASE = {"__brand__": (0.12, 0.035), "hiddenlayer": (0.62, 0.01), "alice": (0.31, 0.01), "lakera": (0.55, -0.015),
           "aws-bedrock": (0.58, 0.0), "google-model-armor": (0.33, 0.02), "azure-content-safety": (0.44, 0.0)}


def seed(cfg: Config) -> dict:
    os.environ["SENTINEL_DEMO"] = "1"
    p = db.path()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(str(p) + suffix)
        except FileNotFoundError:
            pass
    rnd = random.Random(42)
    now = datetime.now(timezone.utc)
    ids = {c.id for c in cfg.competitors}
    with db.connect() as con:
        for i, (cid, kind, sev, cat, head, summ, sw, act, rem, add, sig) in enumerate(CHANGES):
            if cid not in ids:
                continue
            url = next((pg.url for c in cfg.competitors if c.id == cid for pg in c.pages if pg.kind == kind),
                       next(pg.url for c in cfg.competitors if c.id == cid for pg in c.pages))
            a = db.insert(con, "snapshots", {"competitor": cid, "url": url, "kind": kind, "status": 200,
                                             "fetched_at": "2000-01-01T00:00:00+00:00", "text": "\n".join(
                                                 ["Navigation", "Platform", *rem, "Customers", "Resources"])})
            b = db.insert(con, "snapshots", {"competitor": cid, "url": url, "kind": kind, "status": 200,
                                             "fetched_at": "2000-01-01T00:00:00+00:00", "text": "\n".join(
                                                 ["Navigation", "Platform", *add, "Customers", "Resources"])})
            when = now - timedelta(days=[0.3, 1.2, 2.5, 3.1, 4.8, 6.2, 8.5, 12, 16, 23][i % 10], hours=rnd.randint(0, 5))
            cid_ = db.insert(con, "changes", {
                "competitor": cid, "url": url, "kind": kind, "detected_at": when.isoformat(timespec="seconds"),
                "severity": sev, "category": cat, "headline": head, "summary": summ, "so_what": sw, "action": act,
                "added": add, "removed": rem, "signals": sig, "change_ratio": round(rnd.uniform(0.03, 0.3), 3),
                "prev_snapshot": a, "snapshot": b})
            db.insert(con, "events", {"competitor": cid, "module": "pages", "kind": "page_change", "severity": sev, "title": head,
                                      "detail": summ, "so_what": sw, "confidence": "confirmed", "evidence": [{"url": url, "observed_at": when.isoformat(), "method": "illustrative demo"}],
                                      "data": {"category": cat, "action": act}, "detected_at": when.isoformat(timespec="seconds"), "change_id": cid_})
        # current snapshots last, so each page's "latest" is a full one
        for c in cfg.competitors:
            for pg in c.pages:
                db.insert(con, "snapshots", {
                    "competitor": c.id, "url": pg.url, "kind": pg.kind, "status": 200,
                    "fetched_at": (now - timedelta(hours=rnd.randint(1, 6))).isoformat(timespec="seconds"),
                    "hash": f"demo{rnd.random()}", "title": f"{c.name}", "meta": f"{c.name} — illustrative demo snapshot",
                    "signals": {"h1": [f"{c.name} (demo hero headline)"], "headings": [], "ctas": ["Book a demo"],
                                "prices": [], "terms": {t: rnd.randint(0, 6) for t in cfg.watch_terms}, "words": 900},
                    "text": "Demo snapshot text."})
        for j, (cid, title, tops) in enumerate(POSTS):
            if cid not in ids:
                continue
            when = (now - timedelta(days=j * 2.3 + rnd.random())).isoformat(timespec="seconds")
            slug = title.lower().replace(" ", "-").replace(":", "")[:60]
            dom = next(c.domains[0] for c in cfg.competitors if c.id == cid)
            db.insert(con, "posts", {"competitor": cid, "guid": f"demo-{j}", "title": title,
                                     "url": f"https://{dom}/demo/{slug}", "published": when, "first_seen": when,
                                     "summary": "Illustrative demo post — not a real article.", "topics": tops})
        # 8 weekly AI runs
        engines = [("perplexity", "sonar"), ("openai", "gpt-5-mini")]
        for w in range(8):
            run_at = (now - timedelta(weeks=7 - w, hours=2)).isoformat(timespec="seconds")
            for eng, model in engines:
                for q in cfg.questions:
                    ments, order = {}, []
                    for eid, (base, drift) in AI_BASE.items():
                        if eid != "__brand__" and eid not in ids:
                            continue
                        pr = min(0.95, max(0.02, base + drift * w + (0.05 if eng == "perplexity" else -0.03)))
                        if q.category == "Compare" and eid in q.text.lower().replace(" ", "-"):
                            pr = 0.98
                        hit = rnd.random() < pr
                        ments[eid] = {"mentioned": hit, "rank": None, "count": rnd.randint(1, 3) if hit else 0,
                                      "cited": rnd.randint(0, 2) if hit else 0}
                        if hit:
                            order.append((rnd.random() / pr, eid))
                    for r, (_, eid) in enumerate(sorted(order), 1):
                        ments[eid]["rank"] = r
                    names = [e for _, e in sorted(order)]
                    cites = [{"url": f"https://{d}/", "title": d} for d in rnd.sample(
                        ["owasp.org", "hiddenlayer.com", "lakera.ai", "aws.amazon.com", "gartner.com", "reddit.com",
                         "alice.io", "cloud.google.com", "github.com", "learn.microsoft.com", "csoonline.com"], 4)]
                    db.insert(con, "ai_results", {
                        "run_id": f"demo{w:02d}", "run_at": run_at, "engine": eng, "model": model,
                        "question_id": q.id, "question": q.text,
                        "answer": "[Illustrative demo answer] Vendors commonly cited include " +
                                  ", ".join(cfg.brand.name if n == "__brand__" else cfg.competitor(n).name for n in names) + ".",
                        "citations": cites, "mentions": ments, "brand_rank": ments["__brand__"]["rank"]})
        for k, job in enumerate(["pages", "feeds", "ai", "digest"]):
            t = (now - timedelta(hours=k + 1)).isoformat(timespec="seconds")
            db.insert(con, "runs", {"job": job, "started_at": t, "finished_at": t, "status": "ok", "stats": {}})
    from . import digest
    digest.run(cfg, deliver=False)
    return {"demo_db": str(p), "hint": "SENTINEL_DEMO=1 sentinel serve"}


def clear() -> dict:
    os.environ["SENTINEL_DEMO"] = "1"
    p = db.path()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(str(p) + suffix)
        except FileNotFoundError:
            pass
    return {"removed": str(p)}
