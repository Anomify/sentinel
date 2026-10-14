"""Weekly digest: build once, render for email (HTML) and Slack (Block Kit), deliver."""
from __future__ import annotations

import html
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

from . import db, insights, llm
from .config import Config

log = logging.getLogger(__name__)
SEV_COLOR = {"critical": "#E5484D", "high": "#F76B15", "medium": "#FFB224", "low": "#8B8D98"}


def build(cfg: Config, days: int | None = None) -> dict:
    days = days or cfg.settings.get("digest", {}).get("lookback_days", 7)
    names = {e.id: e.name for e in cfg.entities}
    colors = {e.id: e.color for e in cfg.entities}
    with db.connect() as con:
        ov = insights.overview(cfg, con, days)
        ch = [c for c in insights.changes(con, days) if c["severity"] != "noise"]
        ps = insights.posts(con, days)
        vis = insights.visibility(cfg, con)
    gaps = insights.gaps(cfg, vis)
    facts = {
        "changes": [{k: c[k] for k in ("competitor", "kind", "severity", "category", "headline", "summary", "so_what", "url")}
                    for c in ch[:40]],
        "posts": [{"competitor": p["competitor"], "title": p["title"], "topics": p["topics"]} for p in ps[:40]],
        "ai_share": [{"entity": names.get(s["id"]), "share": s["share"], "avg_rank": s["avg_rank"]} for s in vis["share"]],
        "ai_gaps": gaps[:10],
    }
    brief = llm.write_brief(cfg, facts) or _fallback_brief(cfg, ov, ch, ps, gaps, names)
    end = datetime.now(timezone.utc)
    return {
        "title": cfg.settings.get("digest", {}).get("title", "Weekly Competitive Brief"),
        "brand": cfg.brand.name, "period_start": insights.since(days), "period_end": end.isoformat(timespec="seconds"),
        "brief": brief, "kpis": ov["kpis"], "competitors": ov["competitors"],
        "changes": ch[:15], "posts": ps[:15], "share": vis["share"], "gaps": gaps[:8],
        "names": names, "colors": colors, "app_url": cfg.settings.get("digest", {}).get("app_url", ""),
    }


def _fallback_brief(cfg, ov, ch, ps, gaps, names) -> dict:
    tl = []
    for c in [c for c in ch if c["severity"] in ("critical", "high")][:3]:
        tl.append(f"{names.get(c['competitor'])}: {c['headline']}")
    busiest = [c for c in ov["competitors"] if c["posts"]]
    if busiest:
        b = max(busiest, key=lambda c: c["posts"])
        tl.append(f"{b['name']} was the most prolific publisher ({b['posts']} new posts).")
    if gaps:
        tl.append(f"{len(gaps)} target questions surface a competitor but not {cfg.brand.name}.")
    if not tl:
        tl.append("Quiet week — no high-severity competitor moves detected.")
    k = ov["kpis"]
    return {"headline": f"{k['changes']} changes, {k['critical']} high-impact, {k['posts']} new posts",
            "tldr": tl, "watch_next": []}


# ── renderers ─────────────────────────────────────────────────────────────────
def _e(s) -> str:
    return html.escape(str(s or ""))


def render_html(d: dict) -> str:
    k, b = d["kpis"], d["brief"]
    period = f"{d['period_start'][:10]} → {d['period_end'][:10]}"
    share = {s["id"]: s for s in d["share"]}
    brand_share = share.get("__brand__", {}).get("share")

    def kpi(label, val, sub=""):
        return (f'<td style="padding:16px 18px;background:#F7F7F8;border-radius:12px;width:25%">'
                f'<div style="font:500 11px/1 Inter,Arial;letter-spacing:.06em;text-transform:uppercase;color:#8B8D98">{label}</div>'
                f'<div style="font:600 26px/1.2 Inter,Arial;color:#111113;margin-top:8px">{val}</div>'
                f'<div style="font:12px Inter,Arial;color:#8B8D98;margin-top:2px">{sub}</div></td>')

    rows = "".join(
        f'<tr><td style="padding:14px 0;border-top:1px solid #EEE">'
        f'<span style="display:inline-block;width:8px;height:8px;border-radius:9px;background:{SEV_COLOR.get(c["severity"], "#999")};margin-right:8px"></span>'
        f'<span style="font:600 12px Inter,Arial;color:{d["colors"].get(c["competitor"], "#333")}">{_e(d["names"].get(c["competitor"]))}</span>'
        f'<span style="font:12px Inter,Arial;color:#8B8D98"> · {_e(c["category"])} · {_e(c["kind"])}</span>'
        f'<div style="font:600 15px/1.4 Inter,Arial;color:#111113;margin-top:4px"><a href="{_e(c["url"])}" style="color:#111113;text-decoration:none">{_e(c["headline"])}</a></div>'
        f'<div style="font:14px/1.5 Inter,Arial;color:#3A3A40;margin-top:2px">{_e(c["so_what"] or c["summary"])}</div>'
        + (f'<div style="font:13px/1.5 Inter,Arial;color:#6E56CF;margin-top:4px">→ {_e(c["action"])}</div>' if c.get("action") else "")
        + "</td></tr>" for c in d["changes"][:10]) or \
        '<tr><td style="font:14px Inter,Arial;color:#8B8D98;padding:12px 0">No material page changes this week.</td></tr>'

    posts = "".join(
        f'<li style="margin:0 0 8px"><span style="color:{d["colors"].get(p["competitor"])};font-weight:600">{_e(d["names"].get(p["competitor"]))}</span> — '
        f'<a href="{_e(p["url"])}" style="color:#111113">{_e(p["title"])}</a></li>' for p in d["posts"][:10]) or \
        '<li style="color:#8B8D98">No new posts.</li>'

    bars = ""
    for s in sorted(d["share"], key=lambda s: -s["share"]):
        pct = round(s["share"] * 100)
        bars += (f'<tr><td style="font:13px Inter,Arial;color:#3A3A40;padding:4px 12px 4px 0;white-space:nowrap">{_e(d["names"].get(s["id"]))}</td>'
                 f'<td style="width:100%;padding:4px 0"><div style="background:#EEE;border-radius:4px;height:8px">'
                 f'<div style="background:{d["colors"].get(s["id"])};width:{max(pct, 1)}%;height:8px;border-radius:4px"></div></div></td>'
                 f'<td style="font:600 13px Inter,Arial;padding:4px 0 4px 12px;text-align:right">{pct}%</td></tr>')
    gaps = "".join(f'<li style="margin:0 0 6px">{_e(g["text"])} <span style="color:#8B8D98">— {", ".join(_e(d["names"].get(c)) for c in g["competitors"])}</span></li>'
                   for g in d["gaps"])

    tldr = "".join(f'<li style="margin:0 0 8px">{_e(t)}</li>' for t in b.get("tldr", []))
    watch = "".join(f'<li style="margin:0 0 6px">{_e(t)}</li>' for t in b.get("watch_next", []))
    sec = lambda t: f'<h2 style="font:600 12px Inter,Arial;letter-spacing:.08em;text-transform:uppercase;color:#8B8D98;margin:36px 0 8px">{t}</h2>'

    return f"""<!doctype html><html><body style="margin:0;background:#EDEDF0;padding:32px 12px">
<table role="presentation" width="100%" style="max-width:680px;margin:0 auto;background:#fff;border-radius:20px;overflow:hidden">
<tr><td style="background:#0B0B0F;padding:28px 36px">
  <div style="font:600 12px Inter,Arial;letter-spacing:.14em;color:#A594F9;text-transform:uppercase">◆ Sentinel · {_e(d['title'])}</div>
  <div style="font:600 24px/1.3 Inter,Arial;color:#fff;margin-top:10px">{_e(b.get('headline'))}</div>
  <div style="font:13px Inter,Arial;color:#8B8D98;margin-top:6px">{period}</div>
</td></tr>
<tr><td style="padding:28px 36px 36px">
  <table role="presentation" width="100%" cellspacing="8" style="margin:0 -8px"><tr>
    {kpi('Changes', k['changes'], f"{k['critical']} high-impact")}
    {kpi('Pricing moves', k['pricing'], 'detected')}
    {kpi('New posts', k['posts'], 'across feeds')}
    {kpi('AI share', f"{round(brand_share * 100)}%" if brand_share is not None else '—', f"{k['ai_gaps']} gaps")}
  </tr></table>
  {sec('TL;DR')}<ul style="font:15px/1.55 Inter,Arial;color:#111113;padding-left:20px;margin:0">{tldr}</ul>
  {sec('What moved')}<table role="presentation" width="100%">{rows}</table>
  {sec('New content')}<ul style="font:14px/1.5 Inter,Arial;color:#3A3A40;padding-left:20px;margin:0">{posts}</ul>
  {sec('AI search share of voice') + '<table role="presentation" width="100%">' + bars + '</table>' if bars else ''}
  {sec(f"Where we're missing from AI answers") + '<ul style="font:14px/1.5 Inter,Arial;color:#3A3A40;padding-left:20px;margin:0">' + gaps + '</ul>' if gaps else ''}
  {sec('Watch next') + '<ul style="font:14px/1.5 Inter,Arial;color:#3A3A40;padding-left:20px;margin:0">' + watch + '</ul>' if watch else ''}
  <div style="margin-top:36px"><a href="{_e(d['app_url'])}" style="display:inline-block;background:#6E56CF;color:#fff;font:600 14px Inter,Arial;padding:12px 20px;border-radius:10px;text-decoration:none">Open dashboard →</a></div>
</td></tr></table>
<div style="text-align:center;font:12px Inter,Arial;color:#8B8D98;margin-top:16px">Sentinel competitive intelligence for {_e(d['brand'])}</div>
</body></html>"""


def render_slack(d: dict) -> dict:
    b, k = d["brief"], d["kpis"]
    emoji = {"critical": ":red_circle:", "high": ":large_orange_circle:", "medium": ":large_yellow_circle:", "low": ":white_circle:"}
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"◆ {d['title']}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{b.get('headline')}*\n" + "\n".join(f"• {t}" for t in b.get("tldr", []))}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            f"*{k['changes']}* changes · *{k['critical']}* high-impact · *{k['posts']}* new posts · "
            f"AI share *{round(k['ai_share'] * 100) if k['ai_share'] is not None else '—'}%*"}]},
        {"type": "divider"},
    ]
    for c in d["changes"][:6]:
        txt = f"{emoji.get(c['severity'], '')} *{d['names'].get(c['competitor'])}* · <{c['url']}|{c['headline']}>"
        if c.get("so_what"):
            txt += f"\n{c['so_what']}"
        if c.get("action"):
            txt += f"\n→ _{c['action']}_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": txt[:2900]}})
    if d["posts"]:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*New content*\n" + "\n".join(
            f"• {d['names'].get(p['competitor'])}: <{p['url']}|{p['title']}>" for p in d["posts"][:6])}})
    if d["gaps"]:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*AI-search gaps*\n" + "\n".join(
            f"• {g['text']}" for g in d["gaps"][:5])}})
    if d["app_url"]:
        blocks.append({"type": "actions", "elements": [{"type": "button", "style": "primary",
                       "text": {"type": "plain_text", "text": "Open dashboard"}, "url": d["app_url"]}]})
    return {"text": b.get("headline"), "blocks": blocks}


# ── delivery ──────────────────────────────────────────────────────────────────
def channels_configured() -> dict:
    return {"slack": bool(os.environ.get("SLACK_WEBHOOK_URL")),
            "email": bool(os.environ.get("SMTP_HOST") and os.environ.get("DIGEST_TO"))}


def send(cfg: Config, d: dict, html_body: str) -> dict:
    out = {}
    want = cfg.settings.get("digest", {}).get("channels", ["slack", "email"])
    ok = channels_configured()
    if "slack" in want and ok["slack"]:
        try:
            r = requests.post(os.environ["SLACK_WEBHOOK_URL"], json=render_slack(d), timeout=30)
            out["slack"] = "sent" if r.ok else f"error {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            out["slack"] = f"error: {e}"
    if "email" in want and ok["email"]:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"{d['title']}: {d['brief'].get('headline')}"
            msg["From"] = os.environ.get("DIGEST_FROM", os.environ.get("SMTP_USER", "sentinel@localhost"))
            msg["To"] = os.environ["DIGEST_TO"]
            msg.set_content("\n".join(["• " + t for t in d["brief"].get("tldr", [])]) + f"\n\n{d['app_url']}")
            msg.add_alternative(html_body, subtype="html")
            port = int(os.environ.get("SMTP_PORT", 587))
            with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=30) as s:
                if port != 25:
                    s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
                s.send_message(msg)
            out["email"] = "sent"
        except Exception as e:
            out["email"] = f"error: {e}"
    return out


def run(cfg: Config, deliver: bool = True, days: int | None = None) -> dict:
    d = build(cfg, days)
    body = render_html(d)
    delivered = send(cfg, d, body) if deliver else {}
    with db.connect() as con:
        did = db.insert(con, "digests", {"created_at": db.now(), "period_start": d["period_start"],
                                         "period_end": d["period_end"], "headline": d["brief"].get("headline"),
                                         "html": body, "payload": d, "delivered": delivered})
    return {"digest_id": did, "headline": d["brief"].get("headline"), "delivered": delivered}
