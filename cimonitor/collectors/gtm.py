"""Module 2, Tag manager & conversion forensics.

Reads the public Google Tag Manager container (gtm.js is public by design: every visitor's
browser downloads it), parses every tag/trigger, extracts tracking IDs and conversion
events, detects server-side GTM, and links IDs shared across domains (sister sites).
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from .. import db, facts, guard
from ..config import Config, Entity
from ..facts import Fact, Rule, ev
from ..signatures import ID_PATTERNS, extract_ids
from .fetch import Capture

log = logging.getLogger(__name__)
MODULE = "gtm"

TAG_TYPES = {
    "__googtag": "Google tag", "__gaawe": "GA4 event", "__gaawc": "GA4 config", "__awct": "Google Ads conversion",
    "__sp": "Google Ads remarketing", "__gclidw": "Conversion linker", "__html": "Custom HTML", "__img": "Custom image pixel",
    "__bzi": "LinkedIn Insight", "__baut": "Microsoft Ads UET", "__flc": "Floodlight counter", "__fls": "Floodlight sales",
    "__ua": "Universal Analytics", "__hjtc": "Hotjar", "__cvt": "Community template", "__zone": "Zone", "__paused": "Paused tag",
}
EVENT_MACRO = "__e"


def container_ids(caps: list[Capture]) -> tuple[set[str], dict[str, str]]:
    """GTM IDs seen, plus {GTM-ID: host it was served from} (server-side GTM when not Google)."""
    ids, hosts = set(), {}
    for c in caps:
        for u in c.requests + c.requests_post:
            m = re.search(r"/gtm\.js\?id=(GTM-[A-Z0-9]+)", u)
            if m:
                ids.add(m.group(1))
                hosts[m.group(1)] = urlparse(u).hostname or ""
        ids |= set(re.findall(r"\bGTM-[A-Z0-9]{5,9}\b", c.html or ""))
    return ids, hosts


def fetch_container(gid: str, host: str | None) -> tuple[dict | None, str]:
    urls = []
    if host and host != "www.googletagmanager.com":
        urls.append(f"https://{host}/gtm.js?id={gid}")
    urls.append(f"https://www.googletagmanager.com/gtm.js?id={gid}")
    for u in urls:
        try:
            r = guard.get(u, respect_robots=False)  # a public script every visitor downloads
            if r.ok and "var data" in r.text:
                return parse_container(r.text), u
        except guard.Blocked:
            continue
        except Exception as e:
            log.info("container fetch %s failed: %s", u, e)
    return None, urls[-1]


def parse_container(js: str) -> dict:
    i = js.find("var data = ")
    if i < 0:
        return {}
    data, _ = json.JSONDecoder().raw_decode(js[i + len("var data = "):])
    res = data.get("resource", {})
    macros, tags, preds, rules = res.get("macros", []), res.get("tags", []), res.get("predicates", []), res.get("rules", [])

    def macro_is_event(arg):
        return isinstance(arg, list) and len(arg) == 2 and arg[0] == "macro" and \
            0 <= arg[1] < len(macros) and macros[arg[1]].get("function") == EVENT_MACRO

    # predicate index → human condition
    conds = []
    for p in preds:
        a0, a1 = p.get("arg0"), p.get("arg1")
        if macro_is_event(a0):
            conds.append(("event", str(a1)))
        else:
            comp = macros[a0[1]].get("vtp_component", "") if isinstance(a0, list) and a0[0] == "macro" and a0[1] < len(macros) else ""
            conds.append(("cond", f"{comp or 'var'} {p.get('function', '').lstrip('_')} {a1}"))
    # rule → which tags fire, on which predicates
    fires_on: dict[int, list[str]] = {}
    for rule in rules:
        ifs = [x for r in rule if r[0] == "if" for x in r[1:]]
        adds = [x for r in rule if r[0] == "add" for x in r[1:]]
        trig = [conds[i][1] for i in ifs if i < len(conds) and conds[i][0] == "event"] or \
               [conds[i][1] for i in ifs if i < len(conds)]
        for t in adds:
            fires_on.setdefault(t, []).extend(trig)

    out_tags, conversions, ids_text = [], {}, js
    for idx, t in enumerate(tags):
        fn = t.get("function", "")
        kind = TAG_TYPES.get(fn, "Custom template" if fn.startswith("__cvt") else fn)
        vt = {k: v for k, v in t.items() if k.startswith("vtp_") and isinstance(v, (str, int, bool))}
        triggers = sorted({x for x in fires_on.get(idx, []) if x not in ("gtm.js", "gtm.init", "gtm.init_consent")})
        loads_on = sorted(set(fires_on.get(idx, [])))
        ident = vt.get("vtp_eventName") or vt.get("vtp_tagId") or vt.get("vtp_conversionId") or vt.get("vtp_partnerId") or ""
        entry = {"index": idx, "type": kind, "function": fn, "id": str(ident), "triggers": loads_on, "paused": bool(t.get("paused"))}
        if fn == "__gaawe" and vt.get("vtp_eventName"):
            conversions[vt["vtp_eventName"]] = {"platform": "GA4", "fires_on": triggers or loads_on,
                                                "measurement_id": vt.get("vtp_measurementIdOverride")}
        if fn == "__awct":
            label = vt.get("vtp_conversionLabel", "")
            conversions[f"Google Ads conversion {label}".strip()] = {"platform": "Google Ads", "fires_on": triggers or loads_on,
                                                                    "conversion_id": f"AW-{vt.get('vtp_conversionId', '')}"}
        if fn == "__bzi":
            entry["id"] = str(vt.get("vtp_id") or vt.get("vtp_partnerId") or "")
        if fn == "__html":
            h = str(t.get("vtp_html", ""))
            entry["snippet"] = re.sub(r"\s+", " ", h)[:240]
            for ev_name in re.findall(r"event\s*:\s*['\"]([\w.-]{3,60})['\"]", h):
                conversions.setdefault(ev_name, {"platform": "dataLayer (custom HTML)", "fires_on": loads_on})
        out_tags.append(entry)
    # custom events used as triggers are conversion-ish signals too
    for kind, val in conds:
        if kind == "event" and not val.startswith("gtm.") and val not in conversions:
            conversions[val] = {"platform": "trigger event", "fires_on": []}
    return {"tags": out_tags, "conversions": conversions, "ids": {k: sorted(v) for k, v in extract_ids(ids_text).items()},
            "counts": {"tags": len(tags), "triggers": len(rules), "variables": len(macros)}}


def funnel_reading(conversions: dict) -> str:
    names = " ".join(conversions).lower()
    bits = []
    if re.search(r"demo|meeting|contact|sales", names):
        bits.append("demo/meeting requests")
    if re.search(r"sign_?up|trial|register|account", names):
        bits.append("self-serve sign-ups")
    if re.search(r"call", names):
        bits.append("phone calls")
    if re.search(r"download|ebook|report|whitepaper", names):
        bits.append("gated-content downloads")
    if re.search(r"webinar|event", names):
        bits.append("event registrations")
    if re.search(r"form_submission|hs_form", names) and not bits:
        bits.append("form fills")
    return ("They optimise for " + ", ".join(bits) + ".") if bits else "No explicit conversion events found."


RULES = {
    "container": Rule(severity="low", on_change=True),
    "tracking_id": Rule(severity="high", title_add=lambda f: f"New tracking ID: {f.label}",
                        so_what=lambda f: "A new ad/analytics account usually means a new channel or campaign."),
    "conversion": Rule(severity="high", title_add=lambda f: f"New conversion event tracked: {f.key}",
                       title_remove=lambda r: f"Conversion event no longer tracked: {r['key']}",
                       so_what=lambda f: "Shows what they're now optimising campaigns for."),
    "gtm_tag": Rule(severity="medium", title_add=lambda f: f"GTM tag added: {f.label}", title_remove=lambda r: f"GTM tag removed: {r['label']}"),
    "sgtm": Rule(severity="high", title_add=lambda f: f"Server-side tagging detected on {f.key}",
                 so_what=lambda f: "First-party server-side tracking: their measurement is more robust than client-side tags suggest (ad-blocker resistant)."),
    "funnel": Rule(on_add=False, on_remove=False, on_change=True, severity="medium"),
}


def run_one(con, cfg: Config, comp: Entity, caps: list[Capture]) -> dict:
    if not caps:
        return {"skipped": "no captures"}
    observed: list[Fact] = []
    gids, served = container_ids(caps)
    page_text = "\n".join((c.html or "") + "\n" + "\n".join(c.requests + c.requests_post) for c in caps)
    page_ids = extract_ids(page_text)
    all_conv: dict = {}
    for gid in sorted(gids):
        host = served.get(gid)
        data, src = fetch_container(gid, host)
        e = [ev(src, "public GTM container (gtm.js)")]
        if host and host != "www.googletagmanager.com":
            observed.append(Fact("sgtm", host, f"{host} serves {gid}", {"container": gid, "url": src}, facts.CONFIRMED, e))
        if not data:
            observed.append(Fact("container", gid, gid, {"host": host, "parsed": False}, facts.CONFIRMED, e))
            continue
        observed.append(Fact("container", gid, gid, {"host": host, **data["counts"]}, facts.CONFIRMED, e))
        for t in data["tags"]:
            if t["function"] in ("__paused",):
                continue
            key = f"{t['function']}:{t['id'] or t['index']}"
            label = f"{t['type']}{(' · ' + t['id']) if t['id'] else ''}"
            observed.append(Fact("gtm_tag", key, label, {k: v for k, v in t.items() if k != "index"}, facts.CONFIRMED, e))
        for name, c in data["conversions"].items():
            all_conv[name] = c
            observed.append(Fact("conversion", name, name, c, facts.CONFIRMED,
                                 [ev(src, "GTM container trigger/tag analysis", f"fires on {', '.join(c['fires_on']) or 'load'}")]))
        for k, vals in data["ids"].items():
            for v in vals:
                page_ids.setdefault(k, set()).add(v)
    for k, vals in page_ids.items():
        if k == "gtm" and vals <= gids:
            pass
        for v in sorted(vals):
            observed.append(Fact("tracking_id", f"{k}:{v}", f"{ID_PATTERNS[k][1]} {v}",
                                 {"type": k, "id": v, "hosts": [comp.domain]}, facts.CONFIRMED,
                                 [ev(caps[0].url, "page source / network / container")]))
    # Server-side GTM candidates from subdomain names (Module 4 data), e.g. "atxgtm", "sgtm", "ss"
    for f in facts.active(con, comp.id, "subdomains", "subdomain"):
        name = f["key"].split(".")[0]
        if re.search(r"gtm|sgtm|^ss$|^sst$|tagging|^data$|^metrics$|^collect$", name) and not f["value"].get("private"):
            observed.append(Fact("sgtm", f["key"], f"{f['key']} (tagging subdomain)", {"via": "subdomain name", "hosting": f["value"].get("hosting")},
                                 facts.LIKELY, f["evidence"] or []))
    if all_conv:
        observed.append(Fact("funnel", "funnel", funnel_reading(all_conv), {"conversions": sorted(all_conv)}, facts.INFERRED,
                             [ev(None, "inferred from tracked conversion events")]))
    return facts.sync(con, comp.id, MODULE, observed, ["container", "tracking_id", "conversion", "gtm_tag", "sgtm", "funnel"], RULES)


def registrable(host: str) -> str:
    parts = host.lower().split(".")
    return ".".join(parts[-3:]) if len(parts) > 2 and parts[-2] in ("co", "com", "org", "net", "ac") and len(parts[-1]) == 2 else ".".join(parts[-2:])


def link_ids(con, cfg: Config) -> list[dict]:
    """Same tracking ID on different registrable domains ⇒ same owner (sister site / microsite)."""
    rows = db.rows(con.execute("SELECT * FROM facts WHERE module IN ('gtm','subdomains') AND kind IN ('tracking_id','page_id') AND removed_at IS NULL"))
    by_id: dict[str, dict] = {}
    for r in rows:
        v = r["value"] or {}
        key = f"{v.get('type')}:{v.get('id')}"
        if not v.get("id") or v.get("type") in ("ua",):
            continue
        d = by_id.setdefault(key, {"hosts": set(), "competitors": set()})
        d["hosts"] |= set(v.get("hosts") or [])
        d["competitors"].add(r["competitor"])
    links = []
    for key, d in by_id.items():
        doms = {registrable(h) for h in d["hosts"] if h}
        if len(doms) > 1:
            links.append({"id": key, "domains": sorted(doms), "competitors": sorted(d["competitors"])})
    for comp in cfg.competitors:
        own = {registrable(x) for x in comp.domains}
        obs = []
        for l in links:
            if comp.id in l["competitors"]:
                for dmn in l["domains"]:
                    if dmn not in own:
                        obs.append(Fact("linked_site", dmn, dmn, {"shared_id": l["id"]}, facts.LIKELY,
                                        [ev(f"https://{dmn}/", "shared tracking ID", l["id"])]))
        facts.sync(con, comp.id, "gtm_links", obs, ["linked_site"], {"linked_site": Rule(
            severity="high", title_add=lambda f: f"Sister site found: {f.key} shares {f.value['shared_id']}",
            so_what=lambda f: "Shared analytics/ads IDs reveal campaign microsites and brands they don't link publicly.")})
    return links
