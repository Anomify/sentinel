"""Unit tests for the intelligence modules (offline, deterministic)."""
import os
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def cfg():
    from cimonitor import config
    return config.load()


# ── Module 1: signatures + motion ────────────────────────────────────────────
def test_signature_detection_by_host_cookie_and_html():
    from cimonitor.signatures import detect
    found = detect(["https://snap.licdn.com/li.lms-analytics/insight.min.js"], {"snap.licdn.com", "opps-widget.getwarmly.com"},
                   ["hubspotutk"], '<script src="//js.hs-scripts.com/123.js"></script>')
    assert {"linkedin-insight", "warmly", "hubspot"} <= set(found)


def test_motion_classifier_sales_led_from_stack_and_ctas():
    from cimonitor.collectors.stack import classify_motion
    m = classify_motion({"warmly", "hubspot", "chilipiper"}, {"demo": "Book a demo"})
    assert m["label"] == "Sales-led" and any("Warmly" in r for r in m["reasons"])
    p = classify_motion({"segment", "amplitude", "stripe"}, {"signup": "Start for free", "pricing_public": "prices shown"})
    assert p["label"] == "Product-led"


def test_tracking_id_extraction():
    from cimonitor.signatures import extract_ids
    ids = extract_ids("gtag('config','G-V657TN00XF'); AW-11463784157 GTM-PZG4BT6S _linkedin_partner_id = \"123456\"; fbq('init', '1234567890123')")
    assert ids["ga4"] == {"G-V657TN00XF"} and ids["google_ads"] == {"AW-11463784157"}
    assert ids["linkedin_partner"] == {"123456"} and ids["meta_pixel"] == {"1234567890123"}


# ── Module 2: GTM container ──────────────────────────────────────────────────
def test_gtm_container_parse_finds_conversion_and_trigger():
    from cimonitor.collectors.gtm import funnel_reading, parse_container
    data = parse_container((FIX / "gtm_container.js").read_text())
    conv = data["conversions"]
    assert "book_demo_form" in conv and conv["book_demo_form"]["platform"] == "GA4"
    assert "hs_form_submission" in conv["book_demo_form"]["fires_on"]
    assert "G-V657TN00XF" in data["ids"]["ga4"]
    assert "demo" in funnel_reading(conv)


# ── Module 3: DNS ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("txt,tool", [
    ("pendo-domain-verification=abc", "Pendo"), ("MS=ms123456", "Microsoft 365 / Entra ID"),
    ("anthropic-domain-verification-x1=abc", "Anthropic (Claude for Work / API)"), ("docker-verification=1", "Docker"),
])
def test_txt_verification_decoder(txt, tool):
    from cimonitor.collectors.dns_infra import decode_txt
    assert decode_txt(txt)[0] == tool


def test_spf_sender_mapping_includes_partner_platform(monkeypatch):
    from cimonitor.collectors import dns_infra
    monkeypatch.setattr(dns_infra, "query", lambda n, t: [])
    inc = dns_infra.spf_includes("v=spf1 include:_spf.google.com include:spf.mindmatrix.net ~all")
    names = [next((n for rx, n in dns_infra.SPF_SENDERS if __import__("re").search(rx, i)), None) for i in inc]
    assert "Google Workspace" in names and "Mindmatrix (partner/channel platform)" in names


# ── Module 4: subdomains ─────────────────────────────────────────────────────
def test_subdomain_labels_and_internal_tooling():
    from cimonitor.collectors.subdomains import INTERNAL_TOOLING, label_kind
    d = "acme.com"
    assert label_kind("ai-costs.acme.com", d) == "campaign / product"
    assert label_kind("atxgtm.acme.com", d) == "tracking"
    assert label_kind("stage.acme.com", d) == "environment"
    assert label_kind("support.acme.com", d) == "infrastructure"
    assert INTERNAL_TOOLING.search("argocd.dev") and INTERNAL_TOOLING.search("vault-services")
    assert not INTERNAL_TOOLING.search("hackathon")


# ── Module 6: hiring ─────────────────────────────────────────────────────────
def test_job_tagging():
    from cimonitor.collectors.hiring import tag
    t = tag("Senior Partner Manager, EMEA", "Sales", "London, UK", "Experience with Salesforce and AWS Marketplace")
    assert t["function"] == "Partnerships" and t["region"] == "EMEA" and t["seniority"] == "Senior"
    assert "Salesforce" in t["tech"] and "Partner Manager" in t["families"]
    assert tag("AI Solutions Architect- Federal", "Sales", "Remote- US", "")["function"] == "Sales engineering"
    assert tag("Enterprise Account Director- NYC", "Sales", "New York", "")["seniority"] != "Head / Director"


# ── Module 7: money ──────────────────────────────────────────────────────────
def test_funding_extraction_and_merge():
    import re
    from cimonitor.collectors.money import extract_money
    items = [{"title": "Acme raises $100M Series B led by Big Ventures", "text": "Acme raises $100M Series B led by Big Ventures, with ARR up 10x",
              "url": "https://a/1", "source": "Wire", "published": "2026-09-02T00:00:00+00:00"},
             {"title": "Acme lands $100 million to expand", "text": "Acme lands $100 million to expand", "url": "https://b/2",
              "source": "Paper", "published": "2026-09-03T00:00:00+00:00"}]
    fr, ar, _ = extract_money(items, re.compile("Acme"))
    assert len(fr) == 1 and fr[0].value["series"] == "Series B" and "Big Ventures" in fr[0].value["investors"]
    assert fr[0].confidence == "confirmed"  # two independent sources
    assert ar and "10x" in ar[0].label.lower()


def test_partner_names_from_logo_filenames():
    from cimonitor.collectors.money import partner_names
    html = ('<img src="https://cdn/x/698205771954d477849ed5a9_tevora-logo%201.svg">'
            '<img src="https://cdn/x/69820577bcc04102e7ca33c1_Optiv_2015%201.svg"><img src="https://cdn/x/abc_ArrowRight.svg">')
    names = partner_names(html, "https://www.acme.com/partners")
    assert "Tevora" in names and "Optiv" in names and "ArrowRight" not in names


# ── Module 9 ─────────────────────────────────────────────────────────────────
def test_persona_vocab():
    from cimonitor.collectors.pages import vocab
    v = vocab("Built for CISOs and AI leaders in financial services to stop prompt injection and secure MCP servers")
    assert "CISO / security leaders" in v["personas"] and "Financial services" in v["industries"]
    assert "Agent / MCP security" in v["use_cases"]


# ── Fact store, launch score, deep dive ──────────────────────────────────────
def test_fact_sync_baseline_then_alerts_and_removals():
    from cimonitor import db, facts
    with db.connect() as con:
        r1 = facts.sync(con, "x", "stack", [facts.Fact("tool", "hubspot", "HubSpot")], ["tool"])
        r2 = facts.sync(con, "x", "stack", [facts.Fact("tool", "linkedin-insight", "LinkedIn Insight Tag")], ["tool"])
        r3 = facts.sync(con, "x", "stack", [facts.Fact("tool", "linkedin-insight", "LinkedIn Insight Tag")], ["tool"])
        ev = [e["title"] for e in db.rows(con.execute("SELECT title FROM events"))]
    assert r1["baseline"] and not r2["baseline"]
    assert r2["pending_removal"] == 1 and r3["removed"] == 1  # removed only after two complete reads without it
    assert ev == ["New tool: LinkedIn Insight Tag", "Tool removed: HubSpot"]


def test_launch_score_combines_and_decays():
    from cimonitor import db, facts
    from cimonitor.collectors.radar import launch_score
    c = cfg().competitors[0]
    with db.connect() as con:
        assert launch_score(con, c)["probability"] == 0
        facts.emit(con, c.id, "radar", "staging_page_added", "high", "Pre-launch page /pricing-v2")
        facts.emit(con, c.id, "subdomains", "subdomain_added", "high", "New subdomain", data={"kind": "campaign / product"})
        s = launch_score(con, c)
    assert 0.45 < s["probability"] < 0.6 and s["n"] == 2 and "horizon" not in s
    assert s["kinds"] == {"new page on staging": 1, "new campaign/product subdomain": 1}


def test_deep_dive_builds_with_vs_us_and_evidence():
    from cimonitor import db, facts
    from cimonitor.intel import deepdive
    c = cfg().competitors[0]
    with db.connect() as con:
        facts.sync(con, c.id, "stack", [facts.Fact("tool", "warmly", "Warmly", {"category": "abm", "category_label": "ABM"}, evidence=[facts.ev("https://x", "capture")]),
                                        facts.Fact("motion", "motion", "Sales-led", {"label": "Sales-led", "reasons": ["r"]}, "inferred")], ["tool", "motion"])
    r = deepdive.build(cfg(), c)
    flat = [f for s in r["sections"] for f in s["findings"]]
    assert any(f["vs_us"] for f in flat) and any(f["evidence"] for f in flat)
    assert {f["confidence"] for f in flat} <= {"confirmed", "likely", "inferred"}
    assert "Vs. us" in deepdive.to_markdown(r)


# ── Guardrails ───────────────────────────────────────────────────────────────
def test_guard_blocks_private_ports_and_schemes(monkeypatch):
    from cimonitor import guard
    monkeypatch.setattr(guard, "resolve_ips", lambda h: ["10.0.0.5"])
    for url in ["https://intel.acme.com/", "http://192.168.1.1/", "https://acme.com:8443/", "ftp://acme.com/"]:
        with pytest.raises(guard.Blocked):
            guard.check_host(url)
    monkeypatch.setattr(guard, "resolve_ips", lambda h: ["93.184.216.34"])
    guard.check_host("https://acme.com/")


def test_guard_respects_robots(monkeypatch):
    from urllib import robotparser
    from cimonitor import guard
    rp = robotparser.RobotFileParser()
    rp.parse(["User-agent: *", "Disallow: /"])
    monkeypatch.setitem(guard._robots, "https://stg.acme.com", rp)
    assert guard.robots_allowed("https://stg.acme.com/page") is False


# ── Tenancy + Postgres ───────────────────────────────────────────────────────
def test_workspaces_are_isolated():
    from cimonitor import db, facts, tenancy
    token = tenancy.create("client-a", "Client A")
    with tenancy.use("client-a"), db.connect() as con:
        facts.emit(con, "x", "dns", "k", "high", "only in A")
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert tenancy.authorize("client-a", token, None) and not tenancy.authorize("client-a", "nope", None)
    assert not tenancy.authorize("default", token, None)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to run against Postgres")
def test_postgres_backend(monkeypatch):
    from cimonitor import db, facts
    monkeypatch.setattr(db, "DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(db, "IS_PG", True)
    db.reset_cache()
    with db.connect() as con:
        con.execute("DELETE FROM facts"); con.execute("DELETE FROM events")
        facts.sync(con, "pg", "stack", [facts.Fact("tool", "a", "A")], ["tool"])
        facts.sync(con, "pg", "stack", [facts.Fact("tool", "b", "B")], ["tool"])
        assert [r["title"] for r in db.rows(con.execute("SELECT title FROM events ORDER BY id"))] == ["New tool: B", "Tool removed: A"]
        db.set_meta(con, "k", {"v": 1}); db.set_meta(con, "k", {"v": 2})
        assert db.get_meta(con, "k") == {"v": 2}


def test_subdomain_alerts_only_for_recent_certificates_and_never_removed():
    from datetime import datetime, timedelta, timezone
    from cimonitor import db, facts
    from cimonitor.collectors.subdomains import RULES
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    with db.connect() as con:
        facts.sync(con, "x", "subdomains", [facts.Fact("subdomain", "www.x.com", "www.x.com", {"first_cert": "2022-01-01"})], ["subdomain"], RULES)
        facts.sync(con, "x", "subdomains", [
            facts.Fact("subdomain", "old.x.com", "old.x.com", {"first_cert": "2023-05-01", "kind": "campaign / product"}),
            facts.Fact("subdomain", "launch.x.com", "launch.x.com", {"first_cert": recent, "kind": "campaign / product"})], ["subdomain"], RULES)
        titles = [r["title"] for r in db.rows(con.execute("SELECT title FROM events"))]
    assert titles == ["New subdomain: launch.x.com"]  # old host recorded silently; www absence not a removal alert



# ── Trust fixes ──────────────────────────────────────────────────────────────
def test_news_relevance_rejects_namesakes():
    from cimonitor.collectors.money import relevant
    c = cfg()
    assert not relevant(c.competitor("alice"), "Alice Weidel says AfD will win the vote")
    assert not relevant(c.competitor("alice"), "New Alice store opens downtown")
    assert not relevant(c.competitor("lakera"), "Pope warns about Gandalf-like AI in new letter")
    assert not relevant(c.competitor("hiddenlayer"), "Browns offense finds the hidden layer of the defense")
    assert not relevant(c.competitor("pluto"), "NASA shares new images of Pluto")
    assert relevant(c.competitor("hiddenlayer"), "HiddenLayer raises $100M Series B")
    assert relevant(c.competitor("lakera"), "Check Point completes acquisition of Lakera to secure AI agents")
    assert relevant(c.competitor("alice"), "ActiveFence rebrands as Alice")


def test_cloud_providers_are_scoped_to_their_guardrails_product():
    c = cfg()
    g = c.competitor("google-model-armor")
    assert g.scoped and g.in_scope("Model Armor adds prompt injection filters") and not g.in_scope("Building virtual vehicles on Google Cloud")
    assert not c.competitor("hiddenlayer").scoped
    from cimonitor import jobs
    assert "google-model-armor" not in {x.id for x in jobs._unscoped(c).competitors}


def test_comeet_board_discovered_from_widget():
    import re
    from cimonitor.collectors.hiring import COMEET_RX
    html = "COMEET.init({ token: '5D51D29347D2EA828D3347DBAA2EA85D522FE', 'company-uid': 'D5.005', 'company-name': 'ActiveFence' });"
    wp = 'var comeetvar = {"comeet_token":"B775041672FB775041003953B772265","comeet_uid":"7B.007"};'
    assert re.findall(COMEET_RX[0], html, re.I | re.S) == [("5D51D29347D2EA828D3347DBAA2EA85D522FE", "D5.005")]
    assert re.findall(COMEET_RX[1], wp, re.I | re.S) == [("B775041672FB775041003953B772265", "7B.007")]


def test_split_hero_headline_is_rejoined():
    from cimonitor.insights import hero
    assert hero(["Safe", "for everyone"]) == "Safe for everyone"
    assert hero(["Safe"]) is None


def test_acquisition_coverage_merges_into_one_deal():
    import re
    from cimonitor.collectors.money import extract_money
    items = [{"text": t, "title": t, "url": f"https://n/{i}", "source": "X", "published": d} for i, (t, d) in enumerate([
        ("Check Point acquires Lakera - CTech", "2025-09-16T07:00:00+00:00"),
        ("Check Point to acquire Lakera, redefining AI security - Check Point Blog", "2025-09-16T07:00:00+00:00"),
        ("Check Point completes acquisition of Lakera - ET", "2025-11-11T08:00:00+00:00")])]
    _, _, aq = extract_money(items, re.compile("Lakera"))
    assert len(aq) == 1 and aq[0].value["completed"].startswith("2025-11") and aq[0].label == "Check Point acquires Lakera"


def test_old_news_is_never_critical_and_dated_when_it_happened():
    from cimonitor.facts import _happened
    assert _happened({"published": "2025-09-16T07:00:00+00:00"}).startswith("2025-09-16")
    assert _happened({"date": "2025-09-16"}) == "2025-09-16T00:00:00+00:00"
    assert _happened({}) is None


def test_brand_voice_is_developer_first():
    from cimonitor import llm
    ctx = llm.brand_context(cfg())
    assert "no sales team" in ctx.lower() and "developer" in ctx.lower()


def test_cleanup_never_wipes_data_when_the_watchlist_is_empty(tmp_path, monkeypatch):
    from cimonitor import cleanup, db, tenancy
    with db.connect() as con:
        db.insert(con, "events", {"competitor": "hiddenlayer", "module": "pages", "kind": "x", "severity": "low",
                                  "title": "t", "detected_at": db.now(), "evidence": [], "data": {}})
    empty = tmp_path / "empty-config"
    empty.mkdir()
    monkeypatch.setattr(tenancy, "BASE_CONFIG", empty)
    assert cleanup.run()["removed_competitors"] == 0
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_each_job_sees_fresh_dns(monkeypatch):
    import requests
    from cimonitor import guard
    from cimonitor.collectors import dnsq

    class R:
        def json(self):
            return {"Answer": [{"type": 15, "data": "10 aspmx.l.google.com."}]}
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("transient")
        return R()
    monkeypatch.setattr(requests, "get", get)
    dnsq.clear()
    assert dnsq.query("rival.example", "MX") == []
    guard.reset_caches()
    assert dnsq.query("rival.example", "MX") == ["10 aspmx.l.google.com"]


# ── Collection failures never become signals ────────────────────────────────
def _events(con, competitor=None):
    from cimonitor import db
    q, a = "SELECT kind, title FROM events", ()
    if competitor:
        q, a = q + " WHERE competitor=?", (competitor,)
    return [(r["kind"], r["title"]) for r in db.rows(con.execute(q, a))]


def test_one_missed_read_is_not_a_removal_and_a_quick_return_is_not_news():
    from cimonitor import db, facts
    pages = [facts.Fact("site_page", f"/p{i}", f"/p{i}") for i in range(30)]
    with db.connect() as con:
        facts.sync(con, "x", "radar", pages, ["site_page"])          # baseline
        facts.sync(con, "x", "radar", [], ["site_page"])            # one bad read
        facts.sync(con, "x", "radar", pages, ["site_page"])         # back
        assert _events(con) == []
        facts.sync(con, "x", "radar", [], ["site_page"])            # two bad reads: removed
        facts.sync(con, "x", "radar", [], ["site_page"])
        removed = len(_events(con))
        facts.sync(con, "x", "radar", pages, ["site_page"])         # back within 30 days: restored quietly
        assert len(_events(con)) == removed
        assert len(facts.active(con, "x", "radar", "site_page")) == 30


def test_unread_kinds_and_append_only_kinds_are_never_removed():
    from cimonitor import db, facts
    rules = {"press": facts.Rule(append_only=True)}
    with db.connect() as con:
        facts.sync(con, "x", "money", [facts.Fact("partner", "ibm", "IBM"), facts.Fact("press", "u1", "Story")], ["partner", "press"], rules)
        for _ in range(3):
            facts.sync(con, "x", "money", [], ["partner", "press"], rules, unread={"partner"})
        assert _events(con) == []
        assert {f["key"] for f in facts.active(con, "x", "money")} == {"ibm", "u1"}


def test_radar_sitemap_and_github_outage_raise_no_signals_or_launch_score(monkeypatch):
    from cimonitor import db
    from cimonitor.collectors import radar
    comp = next(c for c in cfg().competitors if c.tier != "self")
    sitemap = {f"/platform/p{i}" for i in range(40)}
    state = {"ok": True}
    monkeypatch.setattr(radar, "_sitemap", lambda base, limit=5000: set(sitemap) if state["ok"] else set())
    monkeypatch.setattr(radar, "_last_published", lambda url: (None, ""))
    monkeypatch.setattr(radar, "staging_candidates", lambda con, c: [])
    monkeypatch.setattr(radar, "github_orgs", lambda con, c: ["acme"])

    def gh(url, **kw):
        if not state["ok"]:
            raise RuntimeError("API rate limit exceeded")
        return [{"full_name": "acme/sdk", "name": "sdk", "fork": False}] if "/orgs/" in url else []
    monkeypatch.setattr(radar.guard, "get_json", gh)
    with db.connect() as con:
        for ok in (True, False, False, False, True):
            state["ok"] = ok
            r = radar.run_one(con, cfg(), comp)
        assert _events(con, comp.id) == []
        assert r["launch"]["probability"] == 0


def test_hiring_board_outage_does_not_close_roles(monkeypatch):
    from cimonitor import db
    from cimonitor.collectors import hiring
    comp = next(c for c in cfg().competitors if c.tier != "self")
    state = {"ok": True}

    def board(token):
        if not state["ok"]:
            raise RuntimeError("502")
        return [{"id": f"j{i}", "title": f"Engineer {i}", "department": "Engineering", "location": "London",
                 "text": "", "url": f"https://jobs/{i}", "posted": "2026-10-01"} for i in range(5)]
    monkeypatch.setattr(hiring, "discover", lambda con, c: [("greenhouse", "acme")])
    monkeypatch.setitem(hiring.FETCH, "greenhouse", board)
    with db.connect() as con:
        for ok in (True, False, False, False, True):
            state["ok"] = ok
            hiring.run_one(con, comp)
        assert _events(con, comp.id) == []


def test_money_partner_page_outage_and_news_window_raise_no_signals(monkeypatch):
    from cimonitor import db
    from cimonitor.collectors import money
    comp = next(c for c in cfg().competitors if c.tier != "self")
    dom = comp.domain.removeprefix("www.")
    state = {"ok": True, "news": True}

    class R:
        ok, url = True, f"https://{dom}/partners"
        text = '<a href="https://ibm.com"><img alt="IBM"></a><a href="https://optiv.com"><img alt="Optiv"></a> Become a partner'

    def get(url, **kw):
        if not state["ok"]:
            raise RuntimeError("timeout")
        return R()
    story = {"title": f"{comp.name} raises $50M Series B for AI security", "url": "https://news/1", "source": "Wire",
             "published": "2026-10-01T00:00:00+00:00", "text": f"{comp.name} raises $50M Series B for AI security"}
    monkeypatch.setattr(money, "_home_links", lambda c: ([f"https://{dom}/partners"], "") if state["ok"] else ([], ""))
    monkeypatch.setattr(money.guard, "get", get)
    monkeypatch.setattr(money, "news", lambda c: [story] if state["news"] else [])
    with db.connect() as con:
        for ok, nw in ((True, True), (False, False), (False, True), (False, False), (True, True)):
            state["ok"], state["news"] = ok, nw
            money.run_one(con, comp)
        assert _events(con, comp.id) == []


def test_dns_lookup_failure_is_not_a_record_removal(monkeypatch):
    import requests
    from cimonitor import db, guard
    from cimonitor.collectors import dns_infra
    comp = next(c for c in cfg().competitors if c.tier != "self")
    state = {"ok": True}

    class R:
        def __init__(self, ans): self.ans = ans
        def json(self): return {"Status": 0, "Answer": self.ans}

    def get(url, params=None, timeout=None):
        if params["type"] == "MX":
            if not state["ok"]:
                raise requests.ConnectionError("DoH down")
            return R([{"type": 15, "data": "10 aspmx.l.google.com."}])
        if params["type"] == "TXT" and params["name"] == comp.domain.removeprefix("www."):
            return R([{"type": 16, "data": '"v=spf1 include:_spf.google.com ~all"'}])
        return R([])
    monkeypatch.setattr(requests, "get", get)
    with db.connect() as con:
        for ok in (True, False, False, False, True):
            state["ok"] = ok
            guard.reset_caches()
            dns_infra.run_one(con, comp)
        assert _events(con, comp.id) == []


# ── Dates and ranking ────────────────────────────────────────────────────────
def _ago(days):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def test_late_discovered_news_is_in_this_weeks_view_with_both_dates():
    from cimonitor import db, facts, insights
    with db.connect() as con:
        eid = facts.emit(con, "hiddenlayer", "content", "blog_post", "low", "Post from 9 days ago", data={"published": _ago(9)})
        old = facts.emit(con, "hiddenlayer", "money", "funding_added", "critical", "Old round", data={"date": _ago(40)})
        e = db.row(con.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone())
        assert e["occurred_at"][:10] == _ago(9)[:10] and e["detected_at"][:10] == _ago(0)[:10]
        assert eid in [x["id"] for x in insights.events(con, 7)]
        assert con.execute("SELECT severity FROM events WHERE id=?", (old,)).fetchone()[0] == "low"


def test_overview_top_signals_are_newest_first_within_severity_and_deltas_compare_like_with_like():
    from cimonitor import db, insights
    c = cfg()
    rival = next(x.id for x in c.competitors if x.tier != "self")
    with db.connect() as con:
        for d in (6, 3, 0):
            db.insert(con, "events", {"competitor": rival, "module": "pages", "kind": "page_change", "severity": "high",
                                      "title": f"{d}d", "detected_at": _ago(d), "evidence": [], "data": {}})
            db.insert(con, "events", {"competitor": rival, "module": "pages", "kind": "page_change", "severity": "high",
                                      "title": f"prev {d}d", "detected_at": _ago(d + 7.5), "evidence": [], "data": {}})
        db.insert(con, "events", {"competitor": rival, "module": "pages", "kind": "x", "severity": "noise",
                                  "title": "noise", "detected_at": _ago(10), "evidence": [], "data": {}})
        for i, d in enumerate((1, 2, 9, 10)):
            con.execute("INSERT INTO posts (competitor,guid,title,url,first_seen) VALUES (?,?,?,?,?)", (rival, f"g{i}", "t", "u", _ago(d)))
        ov = insights.overview(c, con, 7)
    assert [e["title"] for e in ov["top_events"]] == ["0d", "3d", "6d"]
    me = next(x for x in ov["competitors"] if x["id"] == rival)
    assert me["heat_delta"] == 0 and ov["kpis"]["changes_prev"] == 3


def test_digest_leaves_out_our_own_activity():
    from cimonitor import db, digest
    c = cfg()
    us = next(x.id for x in c.competitors if x.tier == "self")
    with db.connect() as con:
        db.insert(con, "events", {"competitor": us, "module": "pages", "kind": "page_change", "severity": "critical",
                                  "title": "Our pricing page changed", "detected_at": _ago(0), "evidence": [], "data": {}})
    d = digest.build(c, 7)
    assert all(ch["competitor"] != us for ch in d["changes"]) and us not in {l["id"] for l in d["launch"]}


# ── AI visibility ────────────────────────────────────────────────────────────
def _ai(con, run, at, qid, mentioned, err=None, answer="x", cites=()):
    from cimonitor import db
    db.insert(con, "ai_results", {"run_id": run, "run_at": at, "engine": "perplexity", "model": "m", "question_id": qid,
                                  "question": qid, "answer": "" if err else answer, "citations": list(cites),
                                  "mentions": {} if err else {"__brand__": {"mentioned": mentioned, "rank": 1 if mentioned else None},
                                                              "hiddenlayer": {"mentioned": True, "rank": 2}},
                                  "brand_rank": None, "error": err, "accuracy": None})


def test_failed_and_partial_ai_runs_do_not_replace_the_latest_complete_run():
    from cimonitor import db, insights
    c = cfg()
    qs = [q.id for q in c.questions]
    branded = insights.branded_questions(c)
    measured = [q for q in qs if q not in branded]
    with db.connect() as con:
        for q in qs:
            _ai(con, "good", _ago(2), q, q in measured[: len(measured) // 2])
        for q in qs:
            _ai(con, "outage", _ago(1), q, False, err="429 quota")
        _ai(con, "smoke", _ago(0), qs[0], True)
        v = insights.visibility(c, con)
    assert v["latest"]["run_id"] == "good" and v["latest"]["measured"] == len(measured)
    assert next(s for s in v["share"] if s["id"] == "__brand__")["share"] == round((len(measured) // 2) / len(measured), 3)
    assert [t["run_id"] for t in v["trend"]] == ["good"]
    assert {r["run_id"]: r["complete"] for r in v["runs"]} == {"good": True, "outage": False, "smoke": False}


def test_questions_naming_a_vendor_are_left_out_of_share():
    from cimonitor import insights
    c = cfg()
    branded = insights.branded_questions(c)
    assert {"q10", "q11", "q12"} <= branded and "q01" not in branded  # "HiddenLayer alternatives" vs "best AI security platforms"


def test_source_gaps_skip_vendor_sites_and_redirect_links():
    from cimonitor import db, insights
    c = cfg()
    cites = [{"url": "https://www.hiddenlayer.com/x"}, {"url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/a"},
             {"url": "https://owasp.org/llm-top-10"}]
    with db.connect() as con:
        for q in c.questions:
            _ai(con, "r", _ago(0), q.id, False, cites=cites)
        v = insights.visibility(c, con)
    assert [g["domain"] for g in v["source_gaps"]] == ["owasp.org"]


def test_alice_and_bob_is_not_a_competitor_mention():
    from cimonitor.collectors import ai_search
    c = cfg()
    m = ai_search.score(c, "Prompt injection: Alice sends a message to Bob, and an attacker hides instructions.", [])
    assert not m["alice"]["mentioned"]
    m = ai_search.score(c, "Top tools: HiddenLayer, Alice (formerly ActiveFence) and Lakera Guard.", [])
    assert m["alice"]["mentioned"] and m["hiddenlayer"]["rank"] == 1 and m["alice"]["rank"] == 2
    assert not ai_search.score(c, "the alice library is unrelated", [])["alice"]["mentioned"]


# ── Collection health ────────────────────────────────────────────────────────
def test_health_flags_overdue_failed_and_partially_read_modules():
    from cimonitor import db, digest, insights
    c = cfg()
    rival = next(x for x in c.competitors if x.tier != "self")
    with db.connect() as con:
        db.insert(con, "runs", {"job": "dns", "started_at": _ago(0), "finished_at": _ago(0), "status": "ok",
                                "stats": {rival.id: {"facts": 3, "unread": ["mx"], "failed_lookups": 2}}})
        db.insert(con, "runs", {"job": "hiring", "started_at": _ago(5), "finished_at": _ago(5), "status": "ok", "stats": {}})
        db.insert(con, "runs", {"job": "money", "started_at": _ago(0), "finished_at": _ago(0), "status": "error",
                                "stats": {}, "error": "boom"})
        h = insights.collection_health(c, con)
    by = {m["job"]: m["status"] for m in h["modules"]}
    assert by["dns"] == "ok" and by["hiring"] == "stale" and by["money"] == "error" and by["ai"] == "stale"
    assert [(i["competitor"], i["job"], i["status"]) for i in h["issues"]] == [(rival.id, "dns", "partial")]
    assert h["status"] == "degraded" and "Collection gaps" in digest.health_note(h)
    assert digest.health_note({"status": "ok"}) == "Collection: every module current."


def test_pre_launch_signals_are_reported_as_evidence_not_a_forecast():
    import re
    from cimonitor import db, digest, facts
    from cimonitor.collectors.radar import launch_score
    from cimonitor.intel import deepdive
    c = cfg()
    rival = next(x for x in c.competitors if x.tier != "self")
    with db.connect() as con:
        for i in range(3):
            facts.emit(con, rival.id, "radar", "staging_page_added", "high", f"Pre-launch page /new-{i}")
        launch_score(con, rival)
    d = digest.build(c, 7)
    html = digest.render_html(d)
    assert d["kpis"]["launch_indicators"] == 3 and "3 indicators" in html
    assert not re.search(r"likely within|Launch risk|launch probability", html, re.I)
    r = deepdive.build(c, rival)
    texts = " ".join(f["title"] for s in r["sections"] for f in s["findings"]) + " ".join(str(x["value"]) for x in r["summary"])
    assert "3 pre-launch indicators" in texts and "probability" not in texts.lower()


# ── Stories: one move, one signal ────────────────────────────────────────────
def test_reports_of_one_move_share_a_story():
    from cimonitor.facts import story_key
    now = _ago(0)
    keys = {story_key("funding_added", "Funding: Series B · $100M", now),
            story_key("press_added", "In the news: HiddenLayer Raises $100M Series B to Advance Trustworthy AI - PR Newswire", now),
            story_key("press_added", "In the news: HiddenLayer nabs $100M as enterprises rush to secure AI - TechCrunch", now),
            story_key("mention_added", "On Hacker News: HiddenLayer raises $100 million", now)}
    assert keys == {"funding:100M"}
    a = story_key("press_added", "In the news: HiddenLayer Unveils Agentic Runtime Security - PR Newswire", now)
    b = story_key("press_added", "In the news: HiddenLayer Unveils Agentic Runtime Security - Yahoo Finance", now)
    assert a == b and a != story_key("press_added", "In the news: HiddenLayer joins Databricks ecosystem", now)
    assert story_key("site_page_added", "New page live: /a", now) == story_key("site_page_added", "New page live: /b", now)
    assert story_key("page_change", "New hero headline", now) is None


def test_feed_shows_one_signal_per_story_and_reviewing_it_reviews_every_report():
    from fastapi.testclient import TestClient
    from cimonitor import db, facts, insights
    from cimonitor.api import app
    with db.connect() as con:
        ids = [facts.emit(con, "hiddenlayer", "money", "press_added", "low", f"In the news: HiddenLayer raises $100M Series B - {s}")
               for s in ("Wire", "TechCrunch", "Yahoo")]
        fund = facts.emit(con, "hiddenlayer", "money", "funding_added", "critical", "Funding: Series B · $100M")
        other = facts.emit(con, "hiddenlayer", "pages", "page_change", "high", "New hero headline")
        ev = insights.events(con, 7)
    assert [(e["id"], e["related"]) for e in ev] == [(other, 1), (fund, 4)]
    c = TestClient(app)
    assert len(c.get(f"/api/events/{fund}").json()["reports"]) == 4
    c.post(f"/api/events/{fund}/ack")
    with db.connect() as con:
        assert all(con.execute("SELECT acknowledged FROM events WHERE id=?", (i,)).fetchone()[0] for i in ids)


def test_syndicated_copies_are_not_independent_confirmation():
    import re
    from cimonitor.collectors.money import extract_money
    item = lambda src, title: {"title": f"{title} - {src}", "text": title, "url": f"https://{src}/x", "source": src,  # noqa: E731
                               "published": "2026-09-02T00:00:00+00:00"}
    same = [item(s, "Acme raises $40M Series A for AI security") for s in ("Yahoo Finance", "MSN", "Morningstar")]
    assert extract_money(same, re.compile("Acme"))[0][0].confidence == "likely"
    assert extract_money([item("PR Newswire", "Acme raises $40M Series A")], re.compile("Acme"))[0][0].confidence == "confirmed"
    two = [item("TechCrunch", "Acme raises $40M Series A"), item("SiliconANGLE", "Acme lands $40 million to secure AI agents")]
    assert extract_money(two, re.compile("Acme"))[0][0].confidence == "confirmed"


# ── Evidence vs interpretation ───────────────────────────────────────────────
def test_source_text_is_served_verbatim_and_only_ai_text_loses_em_dashes():
    from fastapi.testclient import TestClient
    from cimonitor import cleanup, db, facts
    from cimonitor.api import app
    with db.connect() as con:
        eid = facts.emit(con, "hiddenlayer", "money", "press_added", "low", "In the news: HiddenLayer — the AI security company",
                         so_what="Matters — a lot")
        cleanup.ai_text_dashes(con)
    e = TestClient(app).get(f"/api/events/{eid}").json()
    assert "—" in e["title"] and "—" not in e["so_what"]


def test_ai_cannot_silently_drop_a_page_change(monkeypatch):
    from cimonitor import db, llm
    from cimonitor.collectors import pages
    from cimonitor.collectors.fetch import Fetched
    from cimonitor.config import Page
    c = cfg()
    comp = next(x for x in c.competitors if x.tier != "self")
    html = {"v": "<html><body><h1>Secure AI</h1><p>Plans from $99/month</p><p>Talk to sales</p></body></html>"}

    class F:
        def get(self, url, render=True, screenshot=None):
            return Fetched(url, 200, html["v"])
    monkeypatch.setattr(llm, "analyze_change", lambda *a, **k: {"headline": "Minor tweak", "category": "cosmetic", "severity": "noise",
                                                                   "summary": "s", "so_what": "w", "action": "a"})
    monkeypatch.setattr(llm, "provider", lambda cfg=None: "gemini")
    page = Page("pricing", "https://example.test/pricing")
    with db.connect() as con:
        pages.check_page(con, c, F(), comp, page)                                  # baseline
        html["v"] = html["v"].replace("$99", "$149")                               # a price change the model calls noise
        r1 = pages.check_page(con, c, F(), comp, page)
        html["v"] = html["v"].replace("Talk to sales", "Talk to our team today")   # a real but minor change
        r2 = pages.check_page(con, c, F(), comp, page)
        rows = db.rows(con.execute("SELECT severity, data FROM events ORDER BY id"))
        n_changes = con.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
    assert r1["severity"] == "critical" and r2["status"] == "noise" and n_changes == 2
    assert [r["severity"] for r in rows] == ["critical", "noise"] and rows[0]["data"]["analysed_by"] == "gemini"


def test_recommendations_carry_the_date_of_what_we_know_about_ourselves():
    from cimonitor import llm
    from cimonitor.intel import deepdive
    c = cfg()
    assert c.brand.profile.get("profile_as_of")
    assert c.brand.profile["profile_as_of"] in llm.brand_context(c)
    assert deepdive.build(c, next(x for x in c.competitors if x.tier != "self"))["profile_as_of"] == c.brand.profile["profile_as_of"]


def test_partner_extraction_skips_menus_and_customer_logos():
    from cimonitor.collectors.money import partner_names
    html = ('<nav><img alt="AI Agent Security Summit navigation item"><img alt="Academy"></nav>'
            '<img alt="AISPM navigation item"><img alt="Alice client logo of Amazon Web Services">'
            '<section><img alt="Nvidia partner"><img alt="Optiv logo"></section><footer><img alt="LinkedIn"></footer>')
    assert partner_names(html, "https://www.acme.com/partners") == ["Nvidia", "Optiv"]


# ── SSRF ─────────────────────────────────────────────────────────────────────
def _public_dns(monkeypatch, guard, private=()):
    monkeypatch.setattr(guard, "resolve_ips", lambda h: ["10.0.0.9"] if h in private else ["93.184.216.34"])
    monkeypatch.setattr(guard, "system_ips", lambda h: [])
    monkeypatch.setattr(guard, "robots_allowed", lambda url, ua=guard.UA: True)
    monkeypatch.setattr(guard, "throttle", lambda url: None)


def test_guard_fails_closed_on_unresolvable_or_partly_private_hosts(monkeypatch):
    from cimonitor import guard
    monkeypatch.setattr(guard, "resolve_ips", lambda h: [])
    monkeypatch.setattr(guard, "system_ips", lambda h: [])
    with pytest.raises(guard.Blocked, match="does not resolve"):
        guard.check_host("https://ghost.acme.com/")
    monkeypatch.setattr(guard, "resolve_ips", lambda h: ["93.184.216.34"])
    monkeypatch.setattr(guard, "system_ips", lambda h: ["127.0.0.1"])  # local resolver disagrees (rebinding, hosts file)
    with pytest.raises(guard.Blocked, match="private"):
        guard.check_host("https://acme.com/")


def test_redirects_to_internal_addresses_are_never_followed(monkeypatch):
    from cimonitor import guard
    _public_dns(monkeypatch, guard, private={"intranet.acme.com"})
    calls = []

    class R:
        def __init__(self, status, loc=None):
            self.status_code, self.headers, self.is_redirect = status, {"location": loc} if loc else {}, bool(loc)
    hops = {"https://acme.com/": R(302, "http://169.254.169.254/latest/meta-data/"),
            "https://acme.com/a": R(301, "https://intranet.acme.com/admin"),
            "https://acme.com/b": R(302, "/c"), "https://acme.com/c": R(200)}
    monkeypatch.setattr(guard._session, "get", lambda url, **kw: calls.append(url) or hops[url])
    for start in ("https://acme.com/", "https://acme.com/a"):
        with pytest.raises(guard.Blocked):
            guard.get(start)
    assert guard.get("https://acme.com/b").status_code == 200
    assert calls == ["https://acme.com/", "https://acme.com/a", "https://acme.com/b", "https://acme.com/c"]  # never the internal hops


def test_browser_requests_to_private_addresses_are_aborted(monkeypatch):
    from cimonitor import guard
    from cimonitor.collectors.fetch import route_guard
    _public_dns(monkeypatch, guard)
    done = []

    class Route:
        def __init__(self, url):
            self.request = type("Req", (), {"url": url})()
        def abort(self, reason): done.append(("abort", self.request.url))
        def continue_(self): done.append(("continue", self.request.url))
    for u in ("http://127.0.0.1:8000/api/jobs/ai", "http://169.254.169.254/", "https://cdn.acme.com/app.js", "data:image/png;base64,x"):
        route_guard(Route(u))
    assert [a for a, _ in done] == ["abort", "abort", "continue", "continue"]
