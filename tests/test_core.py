import os
from datetime import datetime

import pytest


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_DEMO", "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import cimonitor.db as db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    yield


def cfg():
    from cimonitor import config
    return config.load()


PAGE_V1 = """<html><head><title>Acme</title><meta name="description" content="AI security for everyone"></head>
<body><h1>Security for AI</h1><h2>Runtime protection</h2><p>Protect models at runtime.</p>
<a class="btn" href="/demo">Book a demo</a><p>Starter $49 / month</p><p>We raised $100M</p>
<div class="cookie-banner">We use cookies. Accept all</div></body></html>"""
PAGE_V2 = PAGE_V1.replace("Security for AI", "Security for agentic AI").replace("$49", "$79") \
    .replace("Protect models at runtime.", "Protect agentic workflows and MCP servers at runtime.")


class FakeFetcher:
    def __init__(self, html):
        self.html = html

    def get(self, url, render=True):
        from cimonitor.collectors.fetch import Fetched
        return Fetched(url, 200, self.html)


def test_extract_signals_and_noise():
    from cimonitor.collectors.pages import extract
    ex = extract(PAGE_V1, cfg())
    assert ex["signals"]["h1"] == ["Security for AI"]
    assert "Book a demo" in ex["signals"]["ctas"]
    assert any("$49" in p for p in ex["signals"]["prices"])
    assert not any("100M" in p for p in ex["signals"]["prices"]), "funding amounts are not prices"
    assert "cookie" not in ex["text"].lower()


def test_change_detection_end_to_end():
    from cimonitor import db
    from cimonitor.collectors.pages import check_page
    c = cfg()
    comp, page = c.competitors[0], c.competitors[0].pages[0]
    with db.connect() as con:
        assert check_page(con, c, FakeFetcher(PAGE_V1), comp, page)["status"] == "baseline"
        assert check_page(con, c, FakeFetcher(PAGE_V1), comp, page)["status"] == "unchanged"
        r = check_page(con, c, FakeFetcher(PAGE_V2), comp, page)
        assert r["status"] == "changed"
        ch = db.row(con.execute("SELECT * FROM changes").fetchone())
    assert ch["severity"] == "critical" and ch["category"] == "pricing"
    assert "h1" in ch["signals"] and "prices" in ch["signals"]
    assert ch["signals"]["terms"]["MCP"] == {"from": 0, "to": 1}


def test_ai_scoring_ranks_by_first_mention():
    from cimonitor.collectors.ai_search import score
    c = cfg()
    s = score(c, "Top picks: Lakera Guard, then HiddenLayer. WonderFence is also good.",
              [{"url": "https://www.hiddenlayer.com/x"}])
    assert s["lakera"]["rank"] == 1 and s["hiddenlayer"]["rank"] == 2 and s["alice"]["rank"] == 3
    assert s["hiddenlayer"]["cited"] == 1
    assert s["__brand__"]["mentioned"] is False


def test_schedule_parsing():
    from cimonitor.jobs import next_due
    now = datetime(2026, 10, 14, 9, 0)  # Wednesday
    assert next_due("every 6h", None, now) == now
    assert next_due("every 6h", datetime(2026, 10, 14, 5), now) == datetime(2026, 10, 14, 11)
    assert next_due("weekly mon 08:00", None, now) == datetime(2026, 10, 12, 8)  # overdue → run now
    assert next_due("weekly mon 08:00", datetime(2026, 10, 12, 8, 1), now) == datetime(2026, 10, 19, 8)
    assert next_due("daily 07:00", datetime(2026, 10, 14, 7, 0, 5), now) == datetime(2026, 10, 15, 7)


def test_rss_and_atom_parsing():
    from cimonitor.collectors.feeds import parse_xml
    rss = """<rss><channel><item><title>Hello</title><link>https://a/1</link><guid>g1</guid>
             <pubDate>Mon, 13 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Body&lt;/p&gt;</description></item></channel></rss>"""
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>e1</id><title>Atom post</title>
              <link href="https://b/1"/><updated>2026-10-13T00:00:00Z</updated></entry></feed>"""
    a, b = parse_xml(rss), parse_xml(atom)
    assert a[0]["title"] == "Hello" and a[0]["summary"] == "Body" and a[0]["published"].startswith("2026-10-13")
    assert b[0]["url"] == "https://b/1"


def test_digest_renders_without_llm():
    from cimonitor import digest
    d = digest.build(cfg())
    html = digest.render_html(d)
    assert "<html" in html and d["brief"]["headline"]
    assert digest.render_slack(d)["blocks"][0]["type"] == "header"
