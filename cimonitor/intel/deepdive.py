"""The intelligence layer: an auto-generated, always-current competitor deep dive.

Structure mirrors a hand-built competitive teardown: each finding states what we found,
how sure we are (confirmed / likely / inferred), the evidence trail (source, timestamp,
method, screenshot) and a "Vs. us" recommendation. Claude writes the Vs. us when
configured; otherwise rule-based recommendations are used.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .. import db, facts, llm
from ..config import Config, Entity
from ..signatures import BY_ID, CATEGORIES

log = logging.getLogger(__name__)

SECTIONS = [
    ("summary", "Snapshot"),
    ("stack", "GTM stack"),
    ("tracking", "Tracking & conversions"),
    ("dns", "Email & DNS infrastructure"),
    ("subdomains", "Subdomains & infrastructure"),
    ("radar", "Pre-launch radar"),
    ("product", "Product & feature launches"),
    ("social", "Social media"),
    ("hiring", "Hiring"),
    ("money", "Partners, channel & money"),
    ("ads", "Advertising"),
    ("positioning", "Positioning & content"),
    ("ai", "AI search visibility"),
]
CONF_RANK = {"confirmed": 0, "likely": 1, "inferred": 2}


def _f(section, fid, title, detail="", confidence="confirmed", evidence=None, vs_us=None, first_seen=None, data=None, weight=1):
    return {"id": f"{section}:{fid}", "section": section, "title": title, "detail": detail, "confidence": confidence,
            "evidence": (evidence or [])[:4], "vs_us": vs_us, "first_seen": first_seen, "data": data or {}, "weight": weight}


def _ev(fs: list[dict]) -> list[dict]:
    out = []
    for f in fs:
        out += f.get("evidence") or []
    seen, uniq = set(), []
    for e in out:
        k = (e.get("url"), e.get("method"))
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:4]


def _first(fs: list[dict]) -> str | None:
    d = [f["first_seen"] for f in fs if f.get("first_seen")]
    return min(d) if d else None


def build(cfg: Config, comp: Entity) -> dict:
    from .. import insights
    with db.connect() as con:
        A = lambda m, k=None: facts.active(con, comp.id, m, k)  # noqa: E731
        stack_tools, motion, conv_paths = A("stack", "tool"), A("stack", "motion"), A("stack", "conversion_path")
        third = A("stack", "third_party")
        gtm_c, gtm_ids, gtm_conv, sgtm, funnel = A("gtm", "container"), A("gtm", "tracking_id"), A("gtm", "conversion"), A("gtm", "sgtm"), A("gtm", "funnel")
        linked = A("gtm_links", "linked_site")
        verifs, senders, mx, dmarc = A("dns", "verification"), A("dns", "email_sender"), A("dns", "mx"), A("dns", "dmarc")
        subs, wild = A("subdomains", "subdomain"), A("subdomains", "wildcard")
        stg, stg_pages, publishes, repos = A("radar", "staging_site"), A("radar", "staging_page"), facts.history(con, comp.id, "radar", "publish"), A("radar", "repo")
        jobs, boards = A("hiring", "job"), A("hiring", "board")
        partners, mkts, prog, funding, arr, mna, press = (A("money", k) for k in ("partner", "marketplace", "partner_program", "funding", "arr_claim", "m_and_a", "press"))
        adch = A("ads", "ad_channel")
        prods, rels, launches = A("product", "product_page"), A("product", "release"), A("product", "launch")
        socials, sposts, smentions = A("social", "profile"), A("social", "post"), A("social", "mention")
        launch = db.get_meta(con, f"launch:{comp.id}") or {}
        firsts = db.rows(con.execute("SELECT * FROM events WHERE competitor=? AND kind='first_role' ORDER BY detected_at DESC LIMIT 6", (comp.id,)))
        snap = db.row(con.execute("SELECT * FROM snapshots WHERE competitor=? AND kind='homepage' AND error IS NULL ORDER BY id DESC LIMIT 1", (comp.id,)).fetchone())
        snaps_all = db.rows(con.execute("SELECT fetched_at, signals FROM snapshots WHERE competitor=? AND error IS NULL AND signals IS NOT NULL ORDER BY id", (comp.id,)))
        posts = db.rows(con.execute("SELECT ctype, published, first_seen, title, url FROM posts WHERE competitor=? ORDER BY COALESCE(published, first_seen) DESC", (comp.id,)))
        vis = insights.visibility(cfg, con)
        hiring_series = facts.series(con, comp.id, "hiring", "open:")
    out: list[dict] = []

    # ── GTM stack
    if stack_tools:
        by_cat = defaultdict(list)
        for t in stack_tools:
            by_cat[t["value"]["category"]].append(t)
        for cat in ("abm", "ads", "scheduling", "chat", "demo", "map", "product", "partner", "testing", "payments", "calltracking", "events", "replay"):
            ts = by_cat.get(cat)
            if not ts:
                continue
            names = ", ".join(t["label"] for t in ts)
            means = next((BY_ID[t["key"]].means for t in ts if t["key"] in BY_ID and BY_ID[t["key"]].means), "")
            out.append(_f("stack", cat, f"{CATEGORIES[cat]}: {names}", means,
                          min((t["confidence"] for t in ts), key=lambda c: CONF_RANK[c]), _ev(ts), first_seen=_first(ts),
                          vs_us=VSUS_STACK.get(cat), weight=3 if cat in ("abm", "ads", "partner") else 2))
        pre = [t for t in stack_tools if t["value"].get("fires_before_consent")]
        if pre:
            out.append(_f("stack", "preconsent", f"{len(pre)} tracking tools fire before cookie consent",
                          "Loaded before the consent banner was accepted: " + ", ".join(t["label"] for t in pre),
                          "confirmed", _ev(pre), first_seen=_first(pre),
                          vs_us="Privacy-sensitive buyers (EU, regulated) notice this. Make our own consent-first tracking a quiet trust point in security reviews.", weight=2))
        out.append(_f("stack", "count", f"{len(stack_tools)} marketing/web tools detected across {len(third)} third-party domains",
                      "Full inventory in the Stack tab.", "confirmed", _ev(stack_tools[:2]), weight=1))
    if motion:
        m = motion[0]
        out.append(_f("summary", "motion", f"Go-to-market motion: {m['label']}", " · ".join(m["value"].get("reasons", [])),
                      "inferred", m["evidence"], first_seen=m["first_seen"], data=m["value"],
                      vs_us=VSUS_MOTION.get(m["label"]), weight=5))
    if conv_paths:
        out.append(_f("stack", "conversion", "Conversion paths: " + ", ".join(c["label"] for c in conv_paths), "", "confirmed", _ev(conv_paths)))

    # ── Tracking & conversions
    if gtm_conv:
        names = [c["key"] for c in gtm_conv]
        out.append(_f("tracking", "conversions", "Tracked conversions: " + ", ".join(names[:8]),
                      (funnel[0]["label"] if funnel else ""), "confirmed", _ev(gtm_conv), first_seen=_first(gtm_conv),
                      vs_us="Their ad platforms optimise toward these events. Match the high-intent moment (e.g. demo booking) with a faster path on our side and compare in win/loss.", weight=4))
    if gtm_ids:
        ids = sorted({f["value"]["type"] + " " + f["value"]["id"] for f in gtm_ids if f["value"]["type"] != "gtm"})
        out.append(_f("tracking", "ids", "Tracking IDs: " + ", ".join(ids[:8]), f"{len(gtm_c)} GTM container(s) parsed.", "confirmed", _ev(gtm_ids)))
    if sgtm:
        out.append(_f("tracking", "sgtm", "Server-side tagging: " + ", ".join(sorted({s['key'] for s in sgtm})),
                      "First-party tagging endpoint: their attribution survives ad blockers and Safari ITP, so their reported ad performance is more complete than most.",
                      min((s["confidence"] for s in sgtm), key=lambda c: CONF_RANK[c]), _ev(sgtm), first_seen=_first(sgtm),
                      vs_us="Expect their paid channels to be well-optimised. Don't assume you can out-bid them on retargeting; compete on positioning instead.", weight=3))
    if linked:
        out.append(_f("tracking", "linked", "Sister sites sharing tracking IDs: " + ", ".join(l["key"] for l in linked),
                      "Same analytics/ads IDs on other domains: campaign microsites or related brands.", "likely", _ev(linked), first_seen=_first(linked), weight=3))

    # ── DNS
    if verifs:
        cats = defaultdict(set)
        for v in verifs:
            cats[v["value"].get("category", "Other")].add(v["label"])
        notable = list({v["label"]: v for v in verifs if v["value"].get("means")}.values())
        for v in sorted(notable, key=lambda v: v["first_seen"] or "", reverse=True)[:6]:
            out.append(_f("dns", f"v:{v['label']}", f"{v['label']} verified", v["value"]["means"], "confirmed", v["evidence"],
                          first_seen=v["first_seen"], vs_us=VSUS_VERIF.get(v["value"].get("category")), weight=2 if v["value"].get("category") in ("Partner", "AI") else 1))
        out.append(_f("dns", "verifs", f"{len(verifs)} TXT verifications across {len(cats)} categories",
                      "; ".join(f"{k}: {', '.join(sorted(v))}" for k, v in sorted(cats.items())), "confirmed", _ev(verifs[:2])))
    if senders:
        names = sorted({s["label"] for s in senders})
        partnerish = [s for s in senders if re.search(r"partner|channel|PRM", s["label"], re.I)]
        out.append(_f("dns", "senders", "Authorised email senders: " + ", ".join(names), "From the SPF record: every system allowed to send email as them.",
                      "confirmed", _ev(senders)))
        for s in partnerish:
            out.append(_f("dns", f"ps:{s['key']}", f"Partner platform sends email as them: {s['label']}",
                          "A channel-enablement platform authorised in SPF means partners receive co-branded campaigns from them.",
                          "confirmed", s["evidence"], first_seen=s["first_seen"], vs_us=VSUS_VERIF["Partner"], weight=4))
    if mx or dmarc:
        out.append(_f("dns", "mail", f"Mail: {', '.join(m['label'] for m in mx) or 'n/a'} · DMARC {dmarc[0]['label'] if dmarc else 'missing'}",
                      "", "confirmed", _ev(mx + dmarc)))

    # ── Subdomains
    if subs:
        kinds = Counter(s["value"].get("kind") for s in subs)
        hosting = Counter(s["value"].get("hosting") for s in subs)
        out.append(_f("subdomains", "count", f"{len(subs)} hostnames from certificate transparency",
                      "By type: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()) + ". Hosting: " + ", ".join(f"{k} {v}" for k, v in hosting.most_common(6)),
                      "confirmed", _ev(subs[:2])))
        camp = [s for s in subs if s["value"].get("kind") == "campaign / product"]
        for s in sorted(camp, key=lambda s: s["value"].get("first_cert") or "", reverse=True)[:8]:
            v = s["value"]
            det = " · ".join(x for x in [v.get("hosting"), v.get("title"), f"first cert {v.get('first_cert')}" if v.get("first_cert") else None, v.get("note")] if x)
            out.append(_f("subdomains", f"s:{s['key']}", s["key"], det, "inferred" if v.get("private") else s["confidence"],
                          s["evidence"], first_seen=s["first_seen"], data={"screenshot": v.get("screenshot")},
                          vs_us=None if v.get("private") else "Check what this is for; campaign hostnames usually precede a launch or event.", weight=2))
        priv = [s for s in subs if s["value"].get("private")]
        if priv:
            out.append(_f("subdomains", "private", f"{len(priv)} hostnames resolve to private addresses: " + ", ".join(p["key"] for p in priv[:8]),
                          "Internal service names exposed via public certificates/DNS. Recorded only; never contacted.", "confirmed", _ev(priv), weight=2))
        envs = [s for s in subs if s["value"].get("kind") == "environment"]
        if envs:
            out.append(_f("subdomains", "envs", "Environments: " + ", ".join(e["key"] for e in envs[:8]), "", "confirmed", _ev(envs)))
    if wild:
        out.append(_f("subdomains", "wild", "Wildcard certificates: " + ", ".join(w["key"] for w in wild[:8]),
                      "Wildcards usually front multi-tenant services or per-customer environments.", "confirmed", _ev(wild)))

    # ── Radar
    if launch:
        p = launch.get("probability", 0)
        out.append(_f("radar", "launch", f"Launch probability {round(p * 100)}%" + (f" · likely within {launch['horizon']}" if p >= 0.3 else ""),
                      "; ".join(s["signal"] + ": " + s["title"] for s in launch.get("signals", [])[:4]) or "No launch signals in the last 45 days.",
                      "inferred", [], data=launch, vs_us="Prepare a response plan: messaging counter, sales talk track and a pricing stance." if p >= 0.5 else None,
                      weight=5 if p >= 0.5 else 1))
    for s in stg:
        out.append(_f("radar", f"stg:{s['key']}", f"Staging site: {s['key']}", s["value"].get("crawl") or "Public staging mirror monitored for pre-launch pages.",
                      "confirmed", s["evidence"], first_seen=s["first_seen"]))
    if stg_pages:
        out.append(_f("radar", "stgpages", f"{len(stg_pages)} pages on staging not yet on production", ", ".join(p["label"] for p in stg_pages[:10]),
                      "confirmed", _ev(stg_pages), first_seen=_first(stg_pages), vs_us="Read these pages now; they are their next launch.", weight=5))
    if publishes:
        ts = sorted({p["value"].get("at") for p in publishes if p["value"].get("site") == "production"})
        out.append(_f("radar", "cadence", f"Site published {len(ts)} time(s) since monitoring began", f"Latest: {ts[-1] if ts else '-'}",
                      "confirmed", _ev(publishes[-2:])))
    if repos:
        recent = sorted(repos, key=lambda r: r["value"].get("pushed_at") or "", reverse=True)[:5]
        out.append(_f("radar", "repos", f"{len(repos)} public repos; most active: " + ", ".join(r["label"].split("/")[-1] for r in recent),
                      "", "confirmed", _ev(recent)))

    # ── Hiring
    if jobs:
        fn = Counter(j["value"]["function"] for j in jobs)
        reg = Counter(j["value"]["region"] for j in jobs)
        sen = Counter(j["value"]["seniority"] for j in jobs)
        gtm_share = sum(fn[k] for k in ("Sales", "Sales engineering", "Marketing", "Partnerships", "Customer success")) / max(1, len(jobs))
        out.append(_f("hiring", "mix", f"{len(jobs)} open roles · {round(gtm_share * 100)}% go-to-market",
                      "By function: " + ", ".join(f"{k} {v}" for k, v in fn.most_common()) + ". By region: " + ", ".join(f"{k} {v}" for k, v in reg.most_common()),
                      "confirmed", _ev(boards), weight=3, data={"functions": dict(fn), "regions": dict(reg), "seniority": dict(sen)},
                      vs_us=("They're scaling sales capacity. Expect more outbound into our accounts; arm reps with the battlecard and a displacement offer."
                             if gtm_share >= 0.5 else "R&D-heavy hiring: product velocity will rise. Watch the radar for launches.")))
        senior = [j for j in jobs if j["value"]["seniority"] in ("VP", "C-level", "Head / Director")]
        if senior:
            out.append(_f("hiring", "senior", "Senior hires: " + "; ".join(j["label"] for j in senior[:6]), "", "confirmed", _ev(senior), weight=2))
        tech = Counter(t for j in jobs for t in j["value"].get("tech", []))
        if tech:
            out.append(_f("hiring", "tech", "Tech named in job descriptions: " + ", ".join(t for t, _ in tech.most_common(12)), "", "confirmed", _ev(jobs[:2])))
    for e in firsts:
        out.append(_f("hiring", f"first:{e['id']}", e["title"], e.get("so_what") or "", "confirmed", e["evidence"], first_seen=e["detected_at"],
                      vs_us="A first-of-its-kind role marks a new motion or market. Pre-empt it in the accounts it will target.", weight=4))

    # ── Product
    by_date = lambda xs: sorted(xs, key=lambda f: f["value"].get("published") or f["first_seen"] or "", reverse=True)  # noqa: E731
    for f_ in by_date(launches)[:6]:
        out.append(_f("product", f"launch:{f_['key']}", f"Launch: {f_['label']}", f_["value"].get("source", ""), f_["confidence"], f_["evidence"],
                      first_seen=f_["first_seen"], weight=4))
    if prods:
        newest = sorted(prods, key=lambda f: f["first_seen"] or "", reverse=True)
        out.append(_f("product", "catalogue", f"{len(prods)} product and solution pages", ", ".join(p["label"] for p in newest[:10]),
                      "confirmed", _ev(newest[:2]), weight=3))
    if rels:
        newest = sorted(rels, key=lambda f: f["first_seen"] or "", reverse=True)
        out.append(_f("product", "releases", f"Release notes: {len(rels)} entries tracked", "Latest: " + "; ".join(r["label"][:80] for r in newest[:4]),
                      "confirmed", _ev(newest[:1]), weight=3))

    # ── Social
    if socials:
        auto = [p["label"] for p in socials if p["value"].get("automated")]
        out.append(_f("social", "profiles", "On " + ", ".join(p["label"] for p in socials),
                      ("Posts tracked automatically on " + ", ".join(auto) + ". " if auto else "") +
                      "; ".join(f"{p['label']}: check by hand" for p in socials if p["value"].get("manual"))[:300],
                      "confirmed", _ev(socials[:2]), weight=2))
    recent = sorted(sposts, key=lambda f: f["value"].get("published") or "", reverse=True)
    if recent:
        from collections import Counter as _C
        by = _C(p["value"].get("platform") for p in recent)
        out.append(_f("social", "posts", f"{len(recent)} social posts tracked (" + ", ".join(f"{k} {v}" for k, v in by.most_common()) + ")",
                      "Latest: " + "; ".join(p["label"][:90] for p in recent[:3]), "confirmed", _ev(recent[:2]), weight=3))
    for m in sorted(smentions, key=lambda f: (f["value"].get("engagement") or {}).get("points", 0), reverse=True)[:3]:
        pts = (m["value"].get("engagement") or {}).get("points", 0)
        out.append(_f("social", f"hn:{m['key']}", f"Hacker News: {m['label']}", f"{pts} points", m["confidence"], m["evidence"], weight=3 if pts >= 50 else 2))

    # ── Money
    for f_ in sorted(funding, key=lambda f: f["value"].get("date") or "", reverse=True)[:3]:
        v = f_["value"]
        out.append(_f("money", f"fund:{f_['key']}", f"{f_['label']}" + (f" · {v['date'][:10]}" if v.get("date") else ""),
                      ("Investors: " + ", ".join(v["investors"]) if v.get("investors") else "") + (f" · Sources: {', '.join(v.get('sources', [])[:3])}" if v.get("sources") else ""),
                      f_["confidence"], f_["evidence"], first_seen=f_["first_seen"],
                      vs_us="Fresh capital → aggressive hiring, launches and discounting over the next 2–3 quarters. Lock in renewals early." if (v.get("date") or "") > "2025" else None,
                      weight=4 if (v.get("date") or "") > "2025" else 1))
    for a in arr[:3]:
        out.append(_f("money", f"arr:{a['key']}", f"Growth claim: {a['label']}", a["value"].get("headline", ""), a["confidence"], a["evidence"], weight=3))
    for a in mna[:3]:
        out.append(_f("money", f"mna:{a['key']}", a["label"], "", a["confidence"], a["evidence"], weight=4))
    if prog or partners:
        out.append(_f("money", "partners", f"Partner programme: {len(partners)} partners listed" + (f" · {', '.join(p['label'] for p in prog[:4])}" if prog else ""),
                      ", ".join(p["label"] for p in partners[:20]), "likely" if partners else "confirmed", _ev(prog + partners[:2]), first_seen=_first(prog + partners),
                      vs_us=VSUS_VERIF["Partner"], weight=3))
    if mkts:
        out.append(_f("money", "mkts", "Marketplace listings: " + ", ".join(sorted({m['label'] for m in mkts})),
                      "Buyers can purchase through committed cloud spend.", "confirmed", _ev(mkts), first_seen=_first(mkts),
                      vs_us="If we're not co-listed on the same marketplaces, procurement-led deals will tilt to them. Prioritise matching listings.", weight=4))
    if press:
        out.append(_f("money", "press", f"{len(press)} press mentions tracked", "Latest: " + "; ".join(p["label"][:90] for p in sorted(press, key=lambda p: p['value'].get('published') or '', reverse=True)[:3]),
                      "confirmed", _ev(press[:2])))

    # ── Ads
    for a in adch:
        out.append(_f("ads", a["key"], f"{a['label']}: {a['value']['status']}", a["value"]["reading"], a["confidence"], a["evidence"], first_seen=a["first_seen"],
                      data={"verify_url": a["value"].get("verify_url")}, weight=2))

    # ── Positioning & content
    if snap:
        sig = snap.get("signals") or {}
        if sig.get("h1"):
            out.append(_f("positioning", "hero", f"Hero: “{sig['h1'][0]}”", snap.get("meta") or "", "confirmed",
                          [{"url": f"https://{comp.domain}/", "observed_at": snap["fetched_at"], "method": "homepage snapshot", "screenshot": snap.get("screenshot")}], weight=3))
        pers = sorted((sig.get("personas") or {}).items(), key=lambda kv: -kv[1])
        if pers:
            out.append(_f("positioning", "buyers", "Buyer hierarchy: " + " → ".join(k for k, _ in pers[:4]),
                          "Ranked by how often each buyer is addressed on the homepage.", "inferred",
                          [{"url": f"https://{comp.domain}/", "observed_at": snap["fetched_at"], "method": "copy analysis"}],
                          vs_us="If their primary buyer differs from ours, lean into the gap; if it's the same, sharpen our proof for that persona.", weight=3))
        ind = sorted((sig.get("industries") or {}).items(), key=lambda kv: -kv[1])
        uc = sorted((sig.get("use_cases") or {}).items(), key=lambda kv: -kv[1])
        if ind or uc:
            out.append(_f("positioning", "focus", "Focus: " + ", ".join(k for k, _ in uc[:4]), ("Industries: " + ", ".join(k for k, _ in ind[:4])) if ind else "",
                          "inferred", [{"url": f"https://{comp.domain}/", "observed_at": snap["fetched_at"], "method": "copy analysis"}]))
    if len(snaps_all) > 1:
        first, last = snaps_all[0]["signals"] or {}, snaps_all[-1]["signals"] or {}
        top = lambda s: max((s.get("personas") or {"–": 0}).items(), key=lambda kv: kv[1])[0]  # noqa: E731
        if (first.get("personas") and last.get("personas")) and top(first) != top(last):
            out.append(_f("positioning", "shift", f"Buyer focus shifted: {top(first)} → {top(last)}", f"Since {snaps_all[0]['fetched_at'][:10]}",
                          "inferred", [], weight=4))
    if posts:
        last90 = [p for p in posts if (p["published"] or p["first_seen"] or "") >= _days_ago(90)]
        types = Counter(p["ctype"] or "Blog" for p in last90)
        out.append(_f("positioning", "content", f"Content engine: {len(last90)} pieces in 90 days",
                      ", ".join(f"{k} {v}" for k, v in types.most_common()) or "-", "confirmed",
                      [{"url": p["url"], "observed_at": p["first_seen"], "method": "feed"} for p in posts[:2]]))

    # ── AI visibility
    sh = next((s for s in vis.get("share", []) if s["id"] == comp.id), None)
    bs = next((s for s in vis.get("share", []) if s["id"] == "__brand__"), None)
    if sh:
        out.append(_f("ai", "share", f"Mentioned in {round(sh['share'] * 100)}% of AI answers" + (f" (us: {round(bs['share'] * 100)}%)" if bs else ""),
                      f"Average position #{sh['avg_rank']}" if sh.get("avg_rank") else "", "confirmed", [],
                      vs_us="Close the gap on the questions where they appear and we don't (AI Visibility → gaps)." if bs and sh["share"] > bs["share"] else None, weight=3))

    # Vs. us: Claude where available (overrides rule text), keeps rule text otherwise.
    try:
        ai = {} if comp.tier == "self" else llm.vs_us(cfg, comp.name, [f for f in out if f["weight"] >= 2])
        for f in out:
            if f["id"] in ai:
                f["vs_us"] = ai[f["id"]]
                f["vs_us_by"] = llm.provider(cfg) or "ai"
    except Exception:
        log.exception("vs us")
    summary = _summary(comp, out, motion, jobs, funding, launch, stack_tools, subs)
    return {"competitor": comp.id, "name": comp.name, "domain": comp.domain, "generated_at": db.now(),
            "summary": summary, "sections": [{"id": s, "title": t, "findings": sorted([f for f in out if f["section"] == s], key=lambda f: -f["weight"])}
                                             for s, t in SECTIONS if any(f["section"] == s for f in out)],
            "counts": Counter(f["confidence"] for f in out)}


def _days_ago(n: int) -> str:
    return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - n * 86400, timezone.utc).isoformat()


def _summary(comp, out, motion, jobs, funding, launch, tools, subs) -> list[dict]:
    lat = sorted(funding, key=lambda f: f["value"].get("date") or "", reverse=True)
    return [
        {"label": "Motion", "value": motion[0]["label"] if motion else "-"},
        {"label": "Launch probability", "value": f"{round((launch or {}).get('probability', 0) * 100)}%"},
        {"label": "Open roles", "value": str(len(jobs))},
        {"label": "Latest funding", "value": lat[0]["label"] if lat else "-"},
        {"label": "GTM tools", "value": str(len(tools))},
        {"label": "Hostnames", "value": str(len(subs))},
    ]


VSUS_STACK = {
    "abm": "They de-anonymise visitors and route accounts to SDRs. Expect fast, targeted outbound after anyone from our pipeline visits their site; warn champions and get ahead with our own follow-up.",
    "ads": "Paid acquisition is live. Audit our share of voice on their branded and category keywords, and make sure our comparison pages rank.",
    "scheduling": "Instant demo booking shortens their time-to-meeting. Match it with an instant-booking flow on our demo form.",
    "chat": "Conversational capture on-site. Make sure our own site answers the same questions faster.",
    "demo": "Buyers can self-tour their product. Publish an interactive tour of ours so we're not the 'talk to sales first' option.",
    "partner": "A channel programme is forming. Get to the top resellers/MSSPs first and offer better margins or deal registration.",
    "product": "Product-led instrumentation on the marketing site: a self-serve funnel. Consider a free tier or sandbox to compete on developer adoption.",
    "map": None, "testing": "They personalise per account. Expect tailored landing pages for named accounts.",
    "payments": "Self-serve purchase exists. Price-sensitive and SMB buyers can buy without talking to sales.",
}
VSUS_MOTION = {
    "Sales-led": "Compete on time-to-value: offer a frictionless trial or sandbox that sidesteps their demo gate, and arm sales for enterprise bake-offs.",
    "Product-led": "Expect bottom-up adoption inside our accounts. Win the economic buyer with enterprise controls, security reviews and ROI proof.",
    "Hybrid": "They hedge both motions. Find which one is actually converting (watch conversion events and hiring mix) and attack the weaker side.",
}
VSUS_VERIF = {
    "Partner": "They are standing up a partner programme. Recruit the same partners first, with better margins and deal registration.",
    "AI": "They are adopting frontier AI internally. Expect faster content and product velocity.",
    "Product analytics": "Investing in in-product guidance: a product-led onboarding push is likely.",
    "Advertising": "Ad accounts verified: expect paid campaigns on that platform.",
    "Payments": "Billing infrastructure: a self-serve or usage-based pricing plan may be coming.",
}


def to_markdown(r: dict) -> str:
    L = [f"# {r['name']}: competitive deep dive", f"_Generated {r['generated_at'][:16].replace('T', ' ')} UTC by Sentinel · passive public sources only_", ""]
    L += [" · ".join(f"**{s['label']}:** {s['value']}" for s in r["summary"]), ""]
    for sec in r["sections"]:
        L += [f"## {sec['title']}", ""]
        for f in sec["findings"]:
            L.append(f"**{f['title']}**  `{f['confidence']}`")
            if f["detail"]:
                L.append(f"{f['detail']}")
            if f.get("vs_us"):
                L.append(f"> **Vs. us:** {f['vs_us']}")
            for e in f["evidence"][:2]:
                if e.get("url"):
                    L.append(f"<sub>Source: {e['url']} · {e.get('method', '')} · {(e.get('observed_at') or '')[:10]}</sub>")
            L.append("")
    return "\n".join(L)


def run(cfg: Config, only: str | None = None) -> dict:
    out = {}
    for comp in cfg.competitors:
        if only and comp.id != only:
            continue
        try:
            r = build(cfg, comp)
            with db.connect() as con:
                db.insert(con, "reports", {"competitor": comp.id, "created_at": r["generated_at"], "payload": r, "markdown": to_markdown(r)})
                con.execute("DELETE FROM reports WHERE competitor=? AND id NOT IN (SELECT id FROM reports WHERE competitor=? ORDER BY id DESC LIMIT 30)",
                            (comp.id, comp.id))
            out[comp.id] = {"findings": sum(len(s["findings"]) for s in r["sections"])}
        except Exception as e:
            log.exception("deep dive failed for %s", comp.id)
            out[comp.id] = {"error": str(e)[:200]}
    return out
