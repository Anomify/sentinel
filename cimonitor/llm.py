"""Claude-powered analysis: turns raw diffs into "what changed / so what / do this"."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "≤ 12 words, what changed, written like a news headline"},
        "category": {"type": "string", "enum": ["pricing", "messaging", "product", "positioning", "proof", "hiring", "cosmetic"]},
        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "noise"]},
        "summary": {"type": "string", "description": "2 sentences: the concrete change"},
        "so_what": {"type": "string", "description": "1-2 sentences: why it matters to us competitively"},
        "action": {"type": "string", "description": "One concrete next step for battlecard/messaging/launch"},
    },
    "required": ["headline", "category", "severity", "summary", "so_what", "action"],
    "additionalProperties": False,
}

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "tldr": {"type": "array", "items": {"type": "string"}},
        "watch_next": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "tldr", "watch_next"],
    "additionalProperties": False,
}


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _client():
    import anthropic
    return anthropic.Anthropic()


def _json_call(model: str, system: str, prompt: str, schema: dict, effort: str = "low") -> dict | None:
    import anthropic
    client = _client()
    kwargs = dict(
        model=model, max_tokens=4000, system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        # Server-side refusal fallback: security-vendor copy can trip cyber classifiers.
        resp = client.beta.messages.create(
            **kwargs, betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"})
    except anthropic.BadRequestError:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        log.warning("analysis refused for model %s", model)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    return json.loads(text) if text else None


def analyze_change(cfg, competitor: str, url: str, kind: str, removed: list[str], added: list[str],
                   signals: dict) -> dict | None:
    if not available():
        return None
    a = cfg.settings.get("analysis", {})
    system = (
        f"You are a competitive-intelligence analyst for {cfg.brand.name}, an AI security company. "
        "You read diffs of competitor web pages and explain them crisply to a product marketing lead "
        "who is about to launch. Be specific, quote numbers, never pad. If the change is boilerplate, "
        "nav reshuffles or date bumps, mark severity 'noise' and category 'cosmetic'."
    )
    prompt = (
        f"Competitor: {competitor}\nPage ({kind}): {url}\n\n"
        f"Structured signal changes:\n{json.dumps(signals, indent=1)[:4000]}\n\n"
        "REMOVED lines:\n" + "\n".join(f"- {l}" for l in removed[:80])[:6000] +
        "\n\nADDED lines:\n" + "\n".join(f"+ {l}" for l in added[:80])[:6000]
    )
    try:
        return _json_call(a.get("model", "claude-opus-5-5"), system, prompt, CHANGE_SCHEMA, a.get("effort", "low"))
    except Exception as e:  # analysis is best-effort; heuristics still apply
        log.warning("change analysis failed: %s", e)
        return None


def write_brief(cfg, facts: dict) -> dict | None:
    if not available():
        return None
    a = cfg.settings.get("analysis", {})
    system = (
        f"You write the weekly competitive brief for {cfg.brand.name}'s product marketing lead. "
        "Lead with what changes decisions. 3-5 TL;DR bullets max, each ≤ 25 words, each naming a competitor. "
        "watch_next: 2-3 things to keep an eye on. No filler, no hedging."
    )
    try:
        return _json_call(a.get("model", "claude-opus-5-5"), system,
                          "This week's raw intelligence (JSON):\n" + json.dumps(facts, default=str)[:60000],
                          BRIEF_SCHEMA, a.get("effort", "low"))
    except Exception as e:
        log.warning("brief failed: %s", e)
        return None
