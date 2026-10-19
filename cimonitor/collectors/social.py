"""Social media: what competitors post, from official public feeds and APIs only.

  • Profiles: social links found on their own homepage (or set under `social:` in the watchlist).
  • YouTube: the channel's public RSS feed (official).
  • Bluesky: the public AppView API (official, no login).
  • Medium: the profile/publication RSS feed (official).
  • X / Twitter and LinkedIn: no free, permitted way to read posts (X's API is paid; LinkedIn forbids automated
    access), so Sentinel records the accounts and gives a one-click link to their latest posts.
  • Hacker News: posts that name the company, via the official Algolia HN API.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

from .. import db, facts, guard
from ..config import Config, Entity
from ..facts import Fact, Rule, ev
from . import money

log = logging.getLogger(__name__)
MODULE = "social"

PLATFORMS = [  # id, label, host pattern, path that marks a profile (not a share/intent link)
    ("linkedin", "LinkedIn", r"(^|\.)linkedin\.com$", r"^/(company|showcase|school)/[^/]+"),
    ("x", "X (Twitter)", r"(^|\.)(twitter|x)\.com$", r"^/(?!intent|share|home|search|i/)[A-Za-z0-9_]{1,15}/?$"),
    ("youtube", "YouTube", r"(^|\.)youtube\.com$", r"^/(@[^/]+|channel/UC[\w-]+|c/[^/]+|user/[^/]+)"),
    ("bluesky", "Bluesky", r"^bsky\.app$", r"^/profile/[^/]+"),
    ("medium", "Medium", r"(^|\.)medium\.com$", r"^/@?[^/]+/?$"),
    ("github", "GitHub", r"^github\.com$", r"^/[^/]+/?$"),
    ("instagram", "Instagram", r"(^|\.)instagram\.com$", r"^/[^/]+/?$"),
    ("facebook", "Facebook", r"(^|\.)facebook\.com$", r"^/(?!sharer|share|dialog)[^/]+/?$"),
    ("reddit", "Reddit", r"(^|\.)reddit\.com$", r"^/(r|user|u)/[^/]+"),
    ("discord", "Discord", r"^(discord\.gg|discord\.com)$", r"^/(invite/)?[^/]+"),
]
LABEL = {p[0]: p[1] for p in PLATFORMS}


TWITTER_META = re.compile(r'name="twitter:(?:site|creator)"[^>]*content="@?([A-Za-z0-9_]{1,15})"|content="@?([A-Za-z0-9_]{1,15})"[^>]*name="twitter:(?:site|creator)"')


def profiles(comp: Entity, links: list[str], html: str = "") -> dict[str, str]:
    """{platform: profile url}, configured ones first, then the first matching link on their homepage."""
    out = {k: v for k, v in (getattr(comp, "social", None) or {}).items() if v and not k.startswith("filter")}
    for u in links:
        p = urlparse(u)
        host, path = (p.hostname or "").lower(), p.path or "/"
        for pid, _, hrx, prx in PLATFORMS:
            if pid not in out and re.search(hrx, host) and re.search(prx, path):
                out[pid] = f"https://{host.removeprefix('www.') if pid != 'youtube' else 'www.youtube.com'}{path.rstrip('/')}"
    if "x" not in out and (m := TWITTER_META.search(html or "")):
        out["x"] = f"https://x.com/{m.group(1) or m.group(2)}"
    out = {k: (v.replace("twitter.com", "x.com") if k == "x" else v) for k, v in out.items()}
    return out


def _rss(url: str, platform: str, respect_robots: bool = False) -> list[dict]:
    r = guard.get(url, respect_robots=respect_robots)
    if not r.ok:
        return []
    root = ET.fromstring(r.content)
    out = []
    for it in list(root.iter("item")) + list(root.iter("{http://www.w3.org/2005/Atom}entry")):
        g = lambda *n: next((x.text or "" for t in n if (x := it.find(t)) is not None), "")  # noqa: E731
        link = g("link") or next((l.get("href") for l in it.findall("{http://www.w3.org/2005/Atom}link")), "")
        pub = g("pubDate", "{http://www.w3.org/2005/Atom}published")
        try:
            pub = parsedate_to_datetime(pub).isoformat() if "," in pub else pub
        except (TypeError, ValueError):
            pass
        title = (g("title", "{http://www.w3.org/2005/Atom}title") or "").strip()
        if link and title:
            out.append({"platform": platform, "url": link.strip(), "text": title, "published": pub or None})
    return out


def youtube(url: str) -> list[dict]:
    m = re.search(r"/channel/(UC[\w-]+)", url)
    cid = m.group(1) if m else None
    if not cid:
        r = guard.get(url)
        m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{20,})"', r.text) or re.search(r"channel/(UC[\w-]{20,})", r.text)
        cid = m.group(1) if m else None
    return _rss(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", "youtube") if cid else []


def bluesky(url: str) -> list[dict]:
    handle = url.rstrip("/").split("/profile/")[-1]
    j = guard.get_json(f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor={quote(handle)}&limit=30&filter=posts_no_replies",
                       respect_robots=False)
    out = []
    for f in j.get("feed", []):
        p = f.get("post", {})
        rec, rkey = p.get("record", {}), (p.get("uri") or "").split("/")[-1]
        if f.get("reason") or not rkey:  # skip reposts
            continue
        out.append({"platform": "bluesky", "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                    "text": (rec.get("text") or "").strip()[:280], "published": rec.get("createdAt"),
                    "engagement": {"likes": p.get("likeCount", 0), "reposts": p.get("repostCount", 0), "replies": p.get("replyCount", 0)}})
    return out


def medium(url: str) -> list[dict]:
    path = urlparse(url).path.strip("/")
    return _rss(f"https://medium.com/feed/{path}", "medium")


def hacker_news(comp: Entity) -> list[dict]:
    distinct, plain = money.news_terms(comp)
    q = (distinct or plain or [comp.name])[0]
    j = guard.get_json(f"https://hn.algolia.com/api/v1/search_by_date?query={quote(q)}&tags=story&hitsPerPage=20", respect_robots=False)
    out = []
    for h in j.get("hits", []):
        title = h.get("title") or ""
        if title and money.relevant(comp, title + " " + (h.get("url") or "")):
            out.append({"platform": "hackernews", "url": f"https://news.ycombinator.com/item?id={h['objectID']}", "text": title,
                        "published": h.get("created_at"), "engagement": {"points": h.get("points", 0), "comments": h.get("num_comments", 0)}})
    return out


READERS = {"youtube": youtube, "bluesky": bluesky, "medium": medium}


def how(pid: str) -> str:
    """How a platform is read, for the UI. LinkedIn and X have no free, permitted way to read posts: link only."""
    return "official feed" if pid in READERS else "link only"
MANUAL = {  # where to look by hand (always offered for LinkedIn and X, alongside automated tracking)
    "linkedin": lambda u: u.rstrip("/") + "/posts/?feedView=all",
    "x": lambda u: u,
    "instagram": lambda u: u, "facebook": lambda u: u,
}
PLATFORM_LABEL = {**LABEL, "hackernews": "Hacker News"}


def _recent(f: Fact, days: int = 30) -> bool:
    d = str(f.value.get("published") or "")[:10]
    return not d or d >= (date.today() - timedelta(days=days)).isoformat()


RULES = {
    "profile": Rule(severity="low", on_remove=False, title_add=lambda f: f"New {f.label} account linked from their site"),
    "post": Rule(severity="low", on_remove=False, alert_if=_recent,
                 title_add=lambda f: f"New {PLATFORM_LABEL.get(f.value.get('platform'), 'social')} post: {f.label[:120]}",
                 severity_fn=lambda f: "medium" if re.search(r"launch|introduc|announc|now available|new feature|webinar|report|research",
                                                             f.label, re.I) else "low"),
    "mention": Rule(severity="low", on_remove=False, alert_if=_recent,
                    title_add=lambda f: f"On Hacker News: {f.label[:120]}",
                    severity_fn=lambda f: "medium" if (f.value.get("engagement") or {}).get("points", 0) >= 50 else "low"),
}


def run_one(con, comp: Entity) -> dict:
    if not comp.domain:
        return {"skipped": "no domain"}
    links, home = money._home_links(comp)
    profs = profiles(comp, links, home)
    obs: list[Fact] = []
    for pid, url in profs.items():
        manual = MANUAL.get(pid, lambda u: None)(url)
        mode = how(pid)
        obs.append(Fact("profile", pid, LABEL.get(pid, pid), {"platform": pid, "url": url, "manual": manual, "how": mode,
                                                            "automated": mode in ("official API", "official feed", "web search")},
                        facts.CONFIRMED, [ev(url, "linked from their homepage" if pid not in (getattr(comp, "social", None) or {}) else "watchlist")]))
    n_posts, errors = 0, {}
    for pid, url in profs.items():
        if pid not in READERS:
            continue
        try:
            items = READERS[pid](url)
        except Exception as e:
            errors[pid] = str(e)[:120]
            continue
        # Big vendors link company-wide channels; keep only posts on the product we track (same filter as their blog feeds).
        flt = (comp.social or {}).get(f"filter_{pid}") or (comp.social or {}).get("filter")  # per-platform filter wins
        rx = re.compile(flt) if flt else None
        for it in items:
            if rx and not rx.search(it["text"]):
                continue
            n_posts += 1
            via = "search index" if it.get("via") == "search" else "official feed"
            obs.append(Fact("post", it["url"][:300], it["text"][:300] or "(no text)", {k: v for k, v in it.items() if k != "text"},
                            facts.LIKELY if via == "search index" else facts.CONFIRMED, [ev(it["url"], f"{PLATFORM_LABEL.get(pid, pid)} {via}")]))
    try:
        for it in hacker_news(comp):
            obs.append(Fact("mention", it["url"], it["text"][:300], {k: v for k, v in it.items() if k != "text"},
                            facts.LIKELY, [ev(it["url"], "Hacker News (Algolia API)")]))
    except Exception as e:
        errors["hackernews"] = str(e)[:120]
    # Only reconcile what we managed to read, so an outage never looks like deleted posts.
    kinds = [k for k in ("profile", "post", "mention") if any(f.kind == k for f in obs)]
    stats = facts.sync(con, comp.id, MODULE, obs, kinds, RULES) if kinds else {"facts": 0, "added": 0}
    stats.update(profiles=sorted(profs), posts=n_posts, errors=errors)
    return stats


def run(cfg: Config, only: str | None = None) -> dict:
    out = {}
    for comp in cfg.competitors:
        if only and comp.id != only:
            continue
        try:
            with db.connect() as con:
                out[comp.id] = run_one(con, comp)
        except Exception as e:
            log.exception("social failed for %s", comp.id)
            out[comp.id] = {"error": str(e)[:200]}
        log.info("social %-20s %s", comp.id, out[comp.id])
    return out
