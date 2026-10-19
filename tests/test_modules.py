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
        ev = [e["title"] for e in db.rows(con.execute("SELECT title FROM events"))]
    assert r1["baseline"] and not r2["baseline"]
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
    assert 0.45 < s["probability"] < 0.6 and s["horizon"] == "2–4 weeks"


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

