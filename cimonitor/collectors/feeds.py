"""Blog/news intake: RSS & Atom feeds, plus listing-page scraping for sites with no feed."""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .. import db
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
    """Anchor text, or — for image-only card links — the nearest heading in the card."""
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


def run(cfg: Config, only: str | None = None) -> dict:
    new, errors = 0, []
    with db.connect() as con, Fetcher(cfg.settings) as fetcher:
        for comp in cfg.competitors:
            if only and comp.id != only:
                continue
            baseline = con.execute("SELECT COUNT(*) FROM posts WHERE competitor=?", (comp.id,)).fetchone()[0] == 0
            for feed in comp.feeds:
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
                        "INSERT OR IGNORE INTO posts (competitor,guid,title,url,published,summary,first_seen,topics) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (comp.id, i["guid"], i["title"], i["url"], i["published"], i["summary"],
                         # first sighting of a whole feed = backfill; date it by publish date so it isn't "new this week"
                         (i["published"] or "1970-01-01") if baseline else db.now(),
                         json.dumps(topics(cfg, i["title"] + " " + i["summary"]))))
                    new += cur.rowcount if not baseline else 0
                log.info("feed %-8s %3d items  %s", feed.type, len(items), feed.url)
    return {"new_posts": new, "errors": errors}
