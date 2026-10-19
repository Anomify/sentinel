"""Social media: what competitors post, from official public feeds and APIs only.

  • Profiles: social links found on their own homepage (or set under `social:` in the watchlist).
  • YouTube: the channel's public RSS feed (official).
  • Bluesky: the public AppView API (official, no login).
  • Medium: the profile/publication RSS feed (official).
  • X / Twitter: the official API when X_BEARER_TOKEN is set (X's API is paid; there is no free public feed).
  • Hacker News: posts that name the company, via the official Algolia HN API.
  • LinkedIn: LinkedIn prohibits automated access (robots.txt and terms) and its API only serves pages you
    administer, so Sentinel records the company page and gives a one-click link to its latest posts.
"""
from __future__ import annotations

import logging
import os
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


def x_posts(url: str) -> list[dict]:
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        return []
    user = url.rstrip("/").split("/")[-1]
    h = {"Authorization": f"Bearer {token}"}
    u = guard.get_json(f"https://api.x.com/2/users/by/username/{user}", respect_robots=False, headers=h).get("data") or {}
    if not u.get("id"):
        return []
    j = guard.get_json(f"https://api.x.com/2/users/{u['id']}/tweets?max_results=20&exclude=replies,retweets&tweet.fields=created_at,public_metrics",
                       respect_robots=False, headers=h)
    return [{"platform": "x", "url": f"https://x.com/{user}/status/{t['id']}", "text": t.get("text", "")[:280],
             "published": t.get("created_at"), "engagement": t.get("public_metrics", {})} for t in j.get("data") or []]


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


def _search(query: str) -> list[dict]:
    """Recent web results from an official search API: Brave (free tier) or SerpAPI. [] when neither key is set."""
    if os.environ.get("BRAVE_SEARCH_API_KEY"):
        j = guard.get_json(f"https://api.search.brave.com/res/v1/web/search?q={quote(query)}&count=20&freshness=pm",
                           respect_robots=False, headers={"X-Subscription-Token": os.environ["BRAVE_SEARCH_API_KEY"], "Accept": "application/json"})
        return [{"url": r.get("url", ""), "title": r.get("title", ""), "snippet": r.get("description", ""),
                 "date": r.get("page_age") or r.get("age")} for r in (j.get("web") or {}).get("results", [])]
    if os.environ.get("SERPAPI_API_KEY"):
        j = guard.get_json(f"https://serpapi.com/search.json?engine=google&q={quote(query)}&num=20&tbs=qdr:m&api_key={os.environ['SERPAPI_API_KEY']}",
                           respect_robots=False)
        return [{"url": r.get("link", ""), "title": r.get("title", ""), "snippet": r.get("snippet", ""), "date": r.get("date")}
                for r in j.get("organic_results", [])]
    return []


def search_key() -> bool:
    return bool(os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get("SERPAPI_API_KEY"))


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s*(\| LinkedIn|on LinkedIn|/ X|on X|\.\.\.)\s*$", "", text.strip())
    return re.sub(r"\s+", " ", text).strip()


def _when(d: str | None) -> str | None:
    if not d:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", d)
    if m:
        return m.group(1)
    m = re.match(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", d, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30}[unit] * n
        return (date.today() - timedelta(days=days)).isoformat()
    from .products import parse_date
    return parse_date(d)


def linkedin_posts(url: str) -> list[dict]:
    """LinkedIn company posts as indexed by search engines (we never contact LinkedIn itself)."""
    slug = url.rstrip("/").split("/")[-1]
    out = []
    for r in _search(f'site:linkedin.com/posts "{slug}"'):
        if f"/posts/{slug}_".lower() in r["url"].lower() or f"/posts/{slug}-".lower() in r["url"].lower():
            text = _clean(r["snippet"]) or _clean(r["title"])
            out.append({"platform": "linkedin", "url": r["url"].split("?")[0], "text": text[:300], "published": _when(r["date"]), "via": "search"})
    return out


def x_search(url: str) -> list[dict]:
    """X posts as indexed by search engines, used when there is no X API key."""
    handle = url.rstrip("/").split("/")[-1]
    out = []
    for r in _search(f"site:x.com/{handle}/status"):
        if re.search(rf"(x|twitter)\.com/{re.escape(handle)}/status/\d+", r["url"], re.I):
            text = _clean(r["snippet"]) or _clean(r["title"])
            out.append({"platform": "x", "url": re.sub(r"twitter\.com", "x.com", r["url"].split("?")[0]), "text": text[:300],
                        "published": _when(r["date"]), "via": "search"})
    return out


def x_any(url: str) -> list[dict]:
    return x_posts(url) if os.environ.get("X_BEARER_TOKEN") else x_search(url)


READERS = {"youtube": youtube, "bluesky": bluesky, "medium": medium, "x": x_any, "linkedin": linkedin_posts}


def how(pid: str) -> str:
    """How a platform is read, for the UI."""
    if pid == "x" and os.environ.get("X_BEARER_TOKEN"):
        return "official API"
    if pid in ("linkedin", "x"):
        return "web search" if search_key() else "needs search key"
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
