"""Blog/news intake: RSS & Atom feeds, plus listing-page scraping for sites with no feed."""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .. import db, facts, guard
from ..config import Config, Entity, Feed
from .fetch import Fetcher

log = logging.getLogger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"


def _text(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None:
            if x.text and x.text.strip():
                return x.text.strip()
            if x.get("href"):
                return x.get("href")
    return ""


def _date(s: str) -> str | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).isoformat()
    except (TypeError, ValueError):
        return s[:25]


def _strip(html: str, n=320) -> str:
    t = re.sub(r"\s+", " ", BeautifulSoup(html or "", "html.parser").get_text(" ")).strip()
    return t[:n] + ("…" if len(t) > n else "")


def parse_xml(xml: str) -> list[dict]:
    root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    items = []
    for it in root.iter("item"):
        items.append({"guid": _text(it, "guid", "link"), "title": _text(it, "title"), "url": _text(it, "link"),
                      "published": _date(_text(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date")),
                      "summary": _strip(_text(it, "description"))})
    for e in root.iter(f"{ATOM}entry"):
        link = next((l.get("href") for l in e.findall(f"{ATOM}link") if l.get("rel", "alternate") == "alternate"), "")
        items.append({"guid": _text(e, f"{ATOM}id") or link, "title": _text(e, f"{ATOM}title"), "url": link,
                      "published": _text(e, f"{ATOM}published", f"{ATOM}updated"),
                      "summary": _strip(_text(e, f"{ATOM}summary", f"{ATOM}content"))})
    return items


def parse_listing(html: str, base: str, pattern: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    pat, host = re.compile(pattern), urlparse(base).netloc
    seen, items = set(), []
    for a in soup.find_all("a", href=True):
        url = urljoin(base, a["href"].split("#")[0])
        u = urlparse(url)
        if u.netloc != host or not pat.search(u.path) or url in seen:
            continue
        title = _clean_title(a)
        if len(title) < 8:
            title = u.path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").capitalize()
        if len(title) < 8:
            continue
        seen.add(url)
        items.append({"guid": url, "title": title[:200], "url": url, "published": None, "summary": ""})
    return items


def _clean_title(a) -> str:
    """Anchor text, or, for image-only card links, the nearest heading in the card."""
    node = a.find(["h2", "h3", "h4"]) or a
    t = re.sub(r"\s+", " ", node.get_text(" ")).strip()
    parent = a.parent
    for _ in range(3):
        if len(t) >= 8 or parent is None:
            break
        h = parent.find(["h2", "h3", "h4", "h5"])
        if h:
            t = re.sub(r"\s+", " ", h.get_text(" ")).strip()
        parent = parent.parent
    return t[:200]


CTYPES = [  # content-engine classification from URL + title
    ("Podcast", r"podcast|episode|\bep\.? ?\d"), ("Webinar", r"webinar|on-demand|livestream|fireside"),
    ("Report", r"report|whitepaper|white paper|e-?book|guide to|state of|landscape|benchmark|survey"),
    ("Research", r"/research/|advisory|cve-|vulnerabilit|exploit|disclos|attack technique|novel|we found|discovered"),
    ("Case study", r"case[- ]stud|customer story|how .+ (uses|secured)"),
    ("Event", r"/events?/|summit|conference|rsa|black hat|def con|booth|meet us"),
    ("Press", r"/press|/news/|announces|launches|partners with|appoints|raises|funding|names .+ (ceo|cro|cmo)"),
    ("Glossary / explainer", r"/glossary/|what is |explained|101|definition"),
]
_CT = [(n, re.compile(r, re.I)) for n, r in CTYPES]


def ctype(url: str, title: str) -> str:
    s = f"{url} {title}"
    return next((n for n, rx in _CT if rx.search(s)), "Blog")


def topics(cfg: Config, text: str) -> list[str]:
    low = text.lower()
    return [t for t in cfg.watch_terms if t.lower() in low]


def pull(fetcher: Fetcher, feed: Feed) -> list[dict]:
    f = fetcher.get(feed.url, render=feed.type == "listing")
    if f.error:
        raise RuntimeError(f.error)
    items = parse_listing(f.html, feed.url, feed.link_pattern or ".") if feed.type == "listing" else parse_xml(f.html)
    if feed.filter:
        r = re.compile(feed.filter)
        items = [i for i in items if r.search(i["title"] + " " + i["summary"])]
    return items


FEED_TYPES = re.compile(r"application/(rss|atom)\+xml", re.I)
COMMON = ["/blog/rss.xml", "/blog/feed", "/rss.xml", "/feed", "/feed.xml", "/blog/feed.xml", "/atom.xml", "/index.xml"]


def discover(con, comp: Entity) -> list[Feed]:
    """Find a company's own blog feed when none is configured: <link rel=alternate> on the homepage or blog, then common paths."""
    key = f"feeds:discovered:{comp.id}"
    cached = db.get_meta(con, key)
    if cached:  # an empty result is retried next run, in case they start a blog
        return [Feed(**f) for f in cached]
    found: list[str] = []
    base = f"https://{comp.domain}"
    for page in (base + "/", base + "/blog", base + "/news", base + "/resources/blog"):
        try:
            r = guard.get(page)
        except Exception:
            continue
        if not r.ok:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        found += [urljoin(r.url, l["href"]) for l in soup.find_all("link", href=True) if FEED_TYPES.search(l.get("type", ""))]
        if found:
            break
    if not found:
        for path in COMMON:
            try:
                r = guard.get(base + path)
                if r.ok and re.search(r"<(rss|feed)\b", r.text[:2000]):
                    found.append(r.url)
                    break
            except Exception:
                continue
    feeds = [{"type": "rss", "url": u} for u in dict.fromkeys(found) if "comments" not in u][:2]
    if not feeds:  # no feed at all: read the blog page itself, keeping links to individual posts
        for path in ("/blog", "/news", "/insights", "/resources/blog"):
            try:
                r = guard.get(base + path)
            except Exception:
                continue
            if r.ok and len(parse_listing(r.text, r.url, rf"^{path}/[^/]+/?$")) >= 1:
                feeds = [{"type": "listing", "url": r.url, "link_pattern": rf"^{path}/[^/]+/?$"}]
                break
    db.set_meta(con, key, feeds)
    return [Feed(**f) for f in feeds]


def run(cfg: Config, only: str | None = None) -> dict:
    new, errors = 0, []
    with db.connect() as con, Fetcher(cfg.settings) as fetcher:
        for comp in cfg.competitors:
            if only and comp.id != only:
                continue
            baseline = con.execute("SELECT COUNT(*) FROM posts WHERE competitor=?", (comp.id,)).fetchone()[0] == 0
            for feed in (comp.feeds or (discover(con, comp) if comp.domain else [])):
                try:
                    items = pull(fetcher, feed)
                except Exception as e:
                    log.warning("feed failed %s: %s", feed.url, e)
                    errors.append({"url": feed.url, "error": str(e)})
                    continue
                for i in items:
                    if not i["guid"]:
                        continue
                    cur = con.execute(
                        "INSERT OR IGNORE INTO posts (competitor,guid,title,url,published,summary,first_seen,topics,ctype) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (comp.id, i["guid"], i["title"], i["url"], i["published"], i["summary"],
                         # first sighting of a whole feed = backfill; date it by publish date so it isn't "new this week"
                         (i["published"] or "1970-01-01") if baseline else db.now(),
                         json.dumps(topics(cfg, i["title"] + " " + i["summary"])), ctype(i["url"], i["title"])))
                    if cur.rowcount and not baseline:
                        new += 1
                        facts.emit(con, comp.id, "content", "blog_post", "low", f"New blog post: {i['title'][:140]}",
                                   detail=i["summary"][:300], evidence=[facts.ev(i["url"], "their blog feed")],
                                   data={"url": i["url"], "published": i["published"]})
                log.info("feed %-8s %3d items  %s", feed.type, len(items), feed.url)
    return {"new_posts": new, "errors": errors}
