"""Module 8, Ads intelligence.

Sources, all official or explicitly public:
  • Google Ads Transparency Center via the official BigQuery public dataset
    (bigquery-public-data.google_ads_transparency_center), needs Google Cloud credentials.
  • Meta Ad Library API (graph.facebook.com/ads_archive), needs META_ADS_TOKEN.
  • LinkedIn Ad Library: LinkedIn's robots.txt prohibits automated access, so Sentinel does
    NOT scrape it. It produces a one-click deep link for a human to check instead.
Then every channel is cross-checked against the pixels Module 1 detected, which settles
questions like "are they actually running LinkedIn ads, or just retargeting?".
"""
from __future__ import annotations

import logging
import os
from urllib.parse import quote_plus

from .. import db, facts, guard
from ..config import Config, Entity
from ..facts import Fact, Rule, ev

log = logging.getLogger(__name__)
MODULE = "ads"

CHANNELS = {
    "google": {"name": "Google Ads", "pixels": {"google-ads", "doubleclick"}},
    "linkedin": {"name": "LinkedIn Ads", "pixels": {"linkedin-insight"}},
    "meta": {"name": "Meta Ads", "pixels": {"meta-pixel"}},
    "microsoft": {"name": "Microsoft Ads", "pixels": {"bing-uet"}},
    "reddit": {"name": "Reddit Ads", "pixels": {"reddit-pixel"}},
    "x": {"name": "X Ads", "pixels": {"x-pixel"}},
}


def deep_links(comp: Entity) -> dict[str, str]:
    name = comp.name.split("(")[0].strip()
    return {
        "google": f"https://adstransparency.google.com/?region=anywhere&domain={comp.domain.removeprefix('www.')}",
        "linkedin": f"https://www.linkedin.com/ad-library/search?accountOwner={quote_plus(name)}",
        "meta": f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=ALL&q={quote_plus(name)}",
        "microsoft": f"https://adlibrary.ads.microsoft.com/?q={quote_plus(name)}",
    }


def google_bigquery(comp: Entity) -> list[dict] | None:
    """Official public dataset. Returns None when not configured."""
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError:
        return None
    if not (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_CLOUD_PROJECT")):
        return None
    name = comp.ads.get("google_advertiser") or comp.name.split("(")[0].strip()
    client = bigquery.Client()
    q = """
      SELECT creative_id, advertiser_disclosed_name, ad_format_type, topic,
             MIN(region.first_shown) first_shown, MAX(region.last_shown) last_shown
      FROM `bigquery-public-data.google_ads_transparency_center.creative_stats`, UNNEST(region_stats) region
      WHERE LOWER(advertiser_disclosed_name) LIKE @n
      GROUP BY 1,2,3,4 ORDER BY last_shown DESC LIMIT 200"""
    job = client.query(q, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("n", "STRING", f"%{name.lower()}%")]))
    return [dict(r) for r in job.result()]


def meta_api(comp: Entity) -> list[dict] | None:
    tok = os.environ.get("META_ADS_TOKEN")
    if not tok:
        return None
    name = comp.name.split("(")[0].strip()
    url = ("https://graph.facebook.com/v21.0/ads_archive?ad_type=ALL&ad_reached_countries=['DE','FR','NL','IE','ES','IT']"
           f"&search_terms={quote_plus(name)}&fields=id,page_name,ad_creation_time,ad_delivery_start_time,ad_delivery_stop_time,"
           f"ad_creative_bodies,ad_creative_link_titles,publisher_platforms&limit=100&access_token={tok}")
    j = guard.get_json(url, respect_robots=False)
    return [a for a in j.get("data", []) if name.lower() in (a.get("page_name") or "").lower()]


# How each channel reads in a sentence: "{who} started running Microsoft (Bing) search ads".
CHANNEL_WORDS = {"google": "Google search ads", "linkedin": "LinkedIn ads", "meta": "Meta (Facebook/Instagram) ads",
                 "microsoft": "Microsoft (Bing) search ads", "reddit": "Reddit ads", "x": "X (Twitter) ads"}


def _state(v: dict) -> str:
    """live: the ad library shows ads · tag: only their tracking tag is installed · none: tag, but no ads in the library."""
    st = str((v or {}).get("status") or "")
    return "live" if st.startswith("active") else "tag" if st.startswith("pixel only") else "none"


def _channel_title(f: Fact, before: str | None = None) -> str:
    what, now = CHANNEL_WORDS.get(f.key, f.label), _state(f.value)
    if now == "live":
        n = f.value.get("library_ads")
        return f"{{who}} started running {what}" + (f" ({n} ads live)" if n else "") if before in (None, "tag") else f"{{who}}'s {what} are live again"
    if now == "tag":
        return f"{{who}} is setting up {what}: the tracking tag is on their site"
    return f"{{who}} paused their {what}" if before == "live" else f"{{who}} has the {what} tag but no ads running"


RULES = {
    # Only a move between live, tag-only and paused is news; creative counts change every day.
    "ad_channel": Rule(severity="medium", on_change=True, severity_fn=lambda f: "low" if _state(f.value) == "none" else "medium",
                       title_add=lambda f: _channel_title(f),
                       title_change=lambda cur, f: _channel_title(f, _state(cur.get("value"))),
                       alert_change=lambda cur, f: _state(cur.get("value")) != _state(f.value),
                       title_remove=lambda r: f"{{who}} removed their {CHANNEL_WORDS.get(r['key'], r['label'])} tag",
                       so_what=lambda f: f.value.get("reading")),
    "ad_creative": Rule(severity="medium", title_add=lambda f: f"{{who}} is running a new {f.value.get('platform')} ad: {f.label}"),
}


def run_one(con, comp: Entity) -> dict:
    tools = {t["key"] for t in facts.active(con, comp.id, "stack", "tool")}
    links = deep_links(comp)
    obs: list[Fact] = []
    status = {}
    lib: dict[str, list | None] = {"linkedin": None}
    unread: set[str] = set()  # an ad library that errored: its creatives are unknown this run, not ended
    try:
        lib["google"] = google_bigquery(comp)
    except Exception as e:
        log.info("BigQuery ads lookup failed: %s", e)
        lib["google"] = None
        unread |= {"ad_channel", "ad_creative"}
    try:
        lib["meta"] = meta_api(comp)
    except Exception as e:
        log.info("Meta Ad Library failed: %s", e)
        lib["meta"] = None
        unread |= {"ad_channel", "ad_creative"}
    # LinkedIn: check policy explicitly and log the decision (it is disallowed → manual link).
    li_ok = guard.robots_allowed(links["linkedin"])
    guard.audit(links["linkedin"], "allowed" if li_ok else "blocked",
                "LinkedIn Ad Library permitted by robots.txt" if li_ok else "robots.txt prohibits automated access, manual deep link provided")
    for ch, meta in CHANNELS.items():
        pixel = bool(tools & meta["pixels"])
        ads = lib.get(ch)
        if ads is None:
            if not pixel:
                continue
            st, conf = "pixel only (library not checked)", facts.INFERRED
            reading = (f"{meta['name']} tag is installed. Without ad-library confirmation this means retargeting audiences are being built"
                       f" and ads are likely or soon running. Verify: {links.get(ch, 'n/a')}")
        elif ads:
            st, conf = f"active · {len(ads)} creatives in library", facts.CONFIRMED
            reading = f"Confirmed running {meta['name']} ({len(ads)} creatives)." + ("" if pixel else " No conversion pixel detected, likely brand/awareness only, or tracking via server-side tagging.")
        else:
            st, conf = "no ads in library", facts.CONFIRMED if not pixel else facts.LIKELY
            reading = (f"Pixel present but no ads in the library: audience building / retargeting prep, or ads paused." if pixel
                       else f"No {meta['name']} activity found.")
            if not pixel:
                continue
        status[ch] = st
        e = [ev(links.get(ch), "ad library" if ads is not None else "pixel detected by stack fingerprinting (Module 1)", st)]
        obs.append(Fact("ad_channel", ch, meta["name"], {"status": st, "pixel": pixel, "library_ads": None if ads is None else len(ads),
                                                         "reading": reading, "verify_url": links.get(ch)}, conf, e))
        for a in (ads or [])[:40]:
            if ch == "google":
                obs.append(Fact("ad_creative", f"google:{a['creative_id']}", f"{a.get('ad_format_type', 'ad')} · {a.get('topic') or ''}".strip(" ·"),
                                {"platform": "Google", "first_shown": str(a.get("first_shown")), "last_shown": str(a.get("last_shown")),
                                 "format": a.get("ad_format_type")}, facts.CONFIRMED,
                                [ev(f"https://adstransparency.google.com/advertiser/creative/{a['creative_id']}", "BigQuery public dataset")]))
            elif ch == "meta":
                body = (a.get("ad_creative_bodies") or [""])[0][:140]
                obs.append(Fact("ad_creative", f"meta:{a['id']}", body or (a.get("ad_creative_link_titles") or ["Meta ad"])[0],
                                {"platform": "Meta", "first_shown": a.get("ad_delivery_start_time"), "last_shown": a.get("ad_delivery_stop_time"),
                                 "placements": a.get("publisher_platforms")}, facts.CONFIRMED,
                                [ev(f"https://www.facebook.com/ads/library/?id={a['id']}", "Meta Ad Library API")]))
    stats = facts.sync(con, comp.id, MODULE, obs, ["ad_channel", "ad_creative"], RULES, unread=unread)
    stats.update(channels=status, sources={"google": lib["google"] is not None, "meta": lib["meta"] is not None,
                                           "linkedin": "manual (robots.txt)"}, links=links)
    db.set_meta(con, f"ads_links:{comp.id}", links)
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
            log.exception("ads failed for %s", comp.id)
            out[comp.id] = {"error": str(e)[:200]}
        log.info("ads %-20s %s", comp.id, {k: v for k, v in out[comp.id].items() if k != "links"})
    return out
