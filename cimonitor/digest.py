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
        evs = insights.events(con, days, limit=500)
        ps = insights.posts(con, days)
        vis = insights.visibility(cfg, con)
        launch = insights.launch_scores(cfg, con)
    ch = [{"id": e["id"], "competitor": e["competitor"], "kind": insights.MODULE_LABEL.get(e["module"], e["module"]),
           "severity": e["severity"], "category": (e.get("data") or {}).get("category") or e["module"],
           "headline": e["title"], "summary": e.get("detail") or "", "so_what": e.get("so_what"),
           "action": (e.get("data") or {}).get("action"), "confidence": e.get("confidence"),
           "url": next((x.get("url") for x in (e.get("evidence") or []) if x.get("url")), cfg.settings.get("digest", {}).get("app_url", ""))}
          for e in sorted(evs, key=lambda e: -insights.SEV_WEIGHT.get(e["severity"], 0))]
    gaps = insights.gaps(cfg, vis)
    facts = {
        "changes": [{k: c[k] for k in ("competitor", "kind", "severity", "category", "headline", "summary", "so_what", "url")}
                    for c in ch[:40]],
        "launch": {names.get(k): v.get("probability") for k, v in launch.items()},
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
        "launch": sorted(({"id": k, **v} for k, v in launch.items() if v.get("probability", 0) >= 0.2), key=lambda x: -x["probability"]),
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
    return {"headline": f"{k['changes']} signals, {k['critical']} high-impact, {k['posts']} new posts",
            "tldr": tl, "watch_next": []}


# ── renderers ─────────────────────────────────────────────────────────────────
def _e(s) -> str:
    return html.escape(str(s or ""))


FONT = "'Alpha Lyrae','Helvetica Neue',Helvetica,Arial,sans-serif"


def render_html(d: dict) -> str:
    """Light, minimal email. One weight throughout; hierarchy comes from size and tone."""
    k, b = d["kpis"], d["brief"]
    period = f"{d['period_start'][:10]} – {d['period_end'][:10]}"
    share = {s["id"]: s for s in d["share"]}
    brand_share = share.get("__brand__", {}).get("share")
    t = lambda size, color="#16161a", extra="": f"font:400 {size}px/1.5 {FONT};color:{color};{extra}"  # noqa: E731

    def kpi(label, val, sub=""):
        return (f'<td style="padding:0 20px 0 0;width:25%;vertical-align:top">'
                f'<div style="{t(11, "#8a8a93", "letter-spacing:.08em;text-transform:uppercase")}">{label}</div>'
                f'<div style="{t(30, "#16161a", "letter-spacing:-.02em;margin-top:6px;line-height:1")}">{val}</div>'
                f'<div style="{t(12, "#8a8a93", "margin-top:6px")}">{sub}</div></td>')

    rows = "".join(
        f'<tr><td style="padding:18px 0;border-top:1px solid #ececef">'
        f'<div style="{t(12, "#8a8a93")}"><span style="display:inline-block;width:6px;height:6px;border-radius:6px;background:{SEV_COLOR.get(c["severity"], "#999")};margin-right:8px;vertical-align:middle"></span>'
        f'{_e(d["names"].get(c["competitor"]))} · {_e(c["kind"])}{(" · " + _e(c.get("confidence"))) if c.get("confidence") else ""}</div>'
        f'<div style="{t(16, "#16161a", "margin-top:4px;line-height:1.4")}"><a href="{_e(c["url"])}" style="color:#16161a;text-decoration:none">{_e(c["headline"])}</a></div>'
        + (f'<div style="{t(14, "#4a4a52", "margin-top:4px")}">{_e(c["so_what"] or c["summary"])}</div>' if (c.get("so_what") or c.get("summary")) else "")
        + (f'<div style="{t(13, "#5b45b8", "margin-top:6px")}">→ {_e(c["action"])}</div>' if c.get("action") else "")
        + "</td></tr>" for c in d["changes"][:12]) or \
        f'<tr><td style="{t(14, "#8a8a93", "padding:12px 0")}">No material moves this period.</td></tr>'

    posts = "".join(f'<li style="margin:0 0 8px">{_e(d["names"].get(p["competitor"]))} — <a href="{_e(p["url"])}" style="color:#16161a">{_e(p["title"])}</a></li>'
                    for p in d["posts"][:8]) or '<li style="color:#8a8a93">No new posts.</li>'
    bars = ""
    for s in sorted(d["share"], key=lambda s: -s["share"]):
        pct = round(s["share"] * 100)
        bars += (f'<tr><td style="{t(13, "#4a4a52", "padding:5px 14px 5px 0;white-space:nowrap")}">{_e(d["names"].get(s["id"]))}</td>'
                 f'<td style="width:100%;padding:5px 0"><div style="background:#f0f0f2;border-radius:3px;height:4px">'
                 f'<div style="background:{d["colors"].get(s["id"])};width:{max(pct, 1)}%;height:4px;border-radius:3px"></div></div></td>'
                 f'<td style="{t(13, "#16161a", "padding:5px 0 5px 14px;text-align:right")}">{pct}%</td></tr>')
    launch = "".join(f'<li style="margin:0 0 6px">{_e(d["names"].get(l["id"]))}: {round(l["probability"] * 100)}% · likely within {_e(l.get("horizon"))}</li>'
                     for l in d.get("launch", [])[:4])
    gaps = "".join(f'<li style="margin:0 0 6px">{_e(g["text"])}</li>' for g in d["gaps"])
    tldr = "".join(f'<li style="margin:0 0 10px">{_e(x)}</li>' for x in b.get("tldr", []))
    watch = "".join(f'<li style="margin:0 0 6px">{_e(x)}</li>' for x in b.get("watch_next", []))
    sec = lambda title: f'<div style="{t(11, "#8a8a93", "letter-spacing:.1em;text-transform:uppercase;margin:40px 0 10px")}">{title}</div>'  # noqa: E731
    ul = lambda inner, size=14: f'<ul style="{t(size, "#2a2a30", "padding-left:18px;margin:0")}">{inner}</ul>'  # noqa: E731

    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>@font-face{{font-family:'Alpha Lyrae';src:url('{_e(d['app_url'])}/fonts/AlphaLyrae-Medium.woff2') format('woff2');font-weight:100 900}}</style></head>
<body style="margin:0;background:#f6f6f4;padding:40px 14px">
<table role="presentation" width="100%" style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid #ececef;border-radius:16px">
<tr><td style="padding:40px 44px 8px">
  <div style="{t(12, "#8a8a93", "letter-spacing:.12em;text-transform:uppercase")}">Sentinel · {_e(d['title'])}</div>
  <div style="{t(26, "#16161a", "letter-spacing:-.02em;line-height:1.25;margin-top:14px")}">{_e(b.get('headline'))}</div>
  <div style="{t(13, "#8a8a93", "margin-top:8px")}">{period}</div>
</td></tr>
<tr><td style="padding:28px 44px 44px">
  <table role="presentation" width="100%"><tr>
    {kpi('Signals', k['changes'], f"{k['critical']} high-impact")}
    {kpi('Launch risk', f"{round((k.get('launch_max') or 0) * 100)}%", 'highest competitor')}
    {kpi('New content', k['posts'], 'pieces')}
    {kpi('AI share', f"{round(brand_share * 100)}%" if brand_share is not None else '—', f"{k['ai_gaps']} gaps")}
  </tr></table>
  {sec('In brief')}{ul(tldr, 15)}
  {sec('What moved')}<table role="presentation" width="100%">{rows}</table>
  {(sec('Launch radar') + ul(launch)) if launch else ''}
  {sec('New content')}{ul(posts)}
  {(sec('AI search share of voice') + '<table role="presentation" width="100%">' + bars + '</table>') if bars else ''}
  {(sec("Where we're missing from AI answers") + ul(gaps)) if gaps else ''}
  {(sec('Watch next') + ul(watch)) if watch else ''}
  <div style="margin-top:40px"><a href="{_e(d['app_url'])}" style="{t(14, "#ffffff", "display:inline-block;background:#16161a;padding:12px 22px;border-radius:999px;text-decoration:none")}">Open Sentinel</a></div>
</td></tr></table>
<div style="{t(12, "#8a8a93", "text-align:center;margin-top:18px")}">Passive, public-source intelligence for {_e(d['brand'])}</div>
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
