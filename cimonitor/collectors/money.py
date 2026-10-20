"""Module 7, Partners, channel & money.

  • Partner pages: partner names (logo grids/links) tracked over time → partner count series.
  • Marketplace listings (AWS, Azure, GCP, Databricks, Snowflake…): discovered from links
    on their own site plus configured listing URLs.
  • Partner programme / reseller signals (programme pages, "become a partner" forms, detected, never submitted).
  • Press & funding via Google News RSS: rounds, investors, ARR / growth claims extracted.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup

from .. import db, facts, guard
from ..config import Config, Entity
from ..facts import Fact, Rule, ev

log = logging.getLogger(__name__)
MODULE = "money"

MARKETPLACES = [
    (r"aws\.amazon\.com/marketplace/(pp|seller-profile)", "AWS Marketplace"),
    (r"azuremarketplace\.microsoft\.com|appsource\.microsoft\.com|marketplace\.microsoft\.com", "Microsoft Azure Marketplace"),
    (r"console\.cloud\.google\.com/marketplace|cloud\.google\.com/marketplace", "Google Cloud Marketplace"),
    (r"marketplace\.databricks\.com|databricks\.com/.*marketplace", "Databricks Marketplace"),
    (r"app\.snowflake\.com/marketplace|snowflake\.com/.*marketplace", "Snowflake Marketplace"),
    (r"marketplace\.redhat\.com|catalog\.redhat\.com", "Red Hat Marketplace"),
    (r"splunkbase\.splunk\.com", "Splunkbase"), (r"store\.servicenow\.com", "ServiceNow Store"),
    (r"crowdstrike\.com/marketplace|marketplace\.crowdstrike", "CrowdStrike Marketplace"),
    (r"hub\.docker\.com/r/", "Docker Hub"), (r"huggingface\.co/", "Hugging Face"),
    (r"oracle\.com/.*marketplace|cloudmarketplace\.oracle", "Oracle Cloud Marketplace"),
    (r"carahsoft\.com", "Carahsoft (public-sector reseller)"),
]
MKT_RX = [(re.compile(p, re.I), n) for p, n in MARKETPLACES]
PARTNER_PATH = re.compile(r"/(partners?|partner-program|alliances?|integrations?|ecosystem|resellers?|channel)(/|$)", re.I)
PROGRAM_TEXT = re.compile(r"(become a partner|partner program|reseller|channel partner|mssp|msp program|referral partner|deal registration)", re.I)
GENERIC = re.compile(r"^(logo|image|img|icon|partner|partners|customer|arrow|close|menu|button|background|hero|graphic|"
                     r"vector|frame|group|rectangle|ellipse|untitled|\d+|[a-f0-9-]{12,})$", re.I)

FUNDING_RX = re.compile(
    r"(?:raises|raised|secures|secured|closes|closed|lands|announces|bags|nabs)\s+(?:a\s+)?\$?\s?(\d+(?:\.\d+)?)\s*(m|million|b|billion|bn)\b"
    r"(?:[^.]{0,60}?(series\s+[a-f]\d?|seed|pre-seed|growth|strategic))?", re.I)
SERIES_RX = re.compile(r"\b(series\s+[a-f]\d?|seed round|pre-seed|growth round)\b", re.I)
LEAD_RX = re.compile(r"led by ([A-Z][\w&.'\- ]{2,60}?)(?:,| and | with |\.|$| to | as )")
ARR_RX = [
    re.compile(r"\$\s?(\d+(?:\.\d+)?)\s?(m|million|b|billion)\s+(?:in\s+)?(arr|annual recurring revenue|revenue run[- ]rate)", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s?x\s+(arr|revenue|growth|year[- ]over[- ]year)", re.I),
    re.compile(r"(arr|revenue)\s+(?:grew|growth of|increased|up)\s+(\d+(?:\.\d+)?\s?(?:%|x))", re.I),
]
ACQ_RX = re.compile(r"\b(acquires|acquired by|to acquire|acquisition of|merges with)\b", re.I)


def _home_links(comp: Entity) -> tuple[list[str], str]:
    base = f"https://{comp.domain}/"
    try:
        r = guard.get(base)
        soup = BeautifulSoup(r.text, "html.parser")
        return [urljoin(r.url, a["href"]) for a in soup.find_all("a", href=True)], r.text
    except Exception:
        return [], ""


SKIP_HOSTS = re.compile(r"(linkedin|twitter|x\.com|facebook|youtube|instagram|github|google|apple|bit\.ly|t\.co|medium|"
                        r"webflow|hubspot|hubspotusercontent[\w-]*|hsforms|cookieyes|vimeo|wistia|calendly|greenhouse|lever|ashby)\.", re.I)
ICONISH = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z]+){0,2}$")  # "ShieldCheck", "ArrowRight" (UI icon sets)


# Alt text that names something other than a partner: menu entries, customer logos, people, awards.
NOT_A_PARTNER = re.compile(r"navigation item|menu item|nav item|\bclient\b|\bcustomer|testimonial|headshot|avatar|award|badge", re.I)


def partner_names(html: str, page_url: str = "") -> list[str]:
    """Names from logo alts, logo filenames and outbound partner links (alt text is often missing)."""
    soup = BeautifulSoup(html, "html.parser")
    # Site chrome isn't a partner list: menus, headers and footers carry product, page and social icons.
    for chrome in soup.find_all(["nav", "header", "footer"]):
        chrome.decompose()
    names, trusted = set(), set()
    own = (urlparse(page_url).hostname or "").removeprefix("www.")
    for img in soup.find_all("img"):
        raw = (img.get("alt") or "").strip()
        if NOT_A_PARTNER.search(raw):
            continue
        alt = re.sub(r"\s*(logo|icon|image)\s*$", "", raw, flags=re.I)
        alt = re.sub(r"^(logo of|logo)\s+", "", alt, flags=re.I)
        alt = re.sub(r"\s+partner\s*$", "", alt, flags=re.I).strip(" -|")  # "Nvidia partner" → "Nvidia"
        if 2 <= len(alt) <= 40 and not GENERIC.match(alt) and not re.search(r"\.(png|svg|jpe?g|webp)$", alt, re.I):
            trusted.add(alt)
            continue
        src = img.get("src") or ""
        stem = re.sub(r"%20", " ", src.rsplit("/", 1)[-1])
        stem = re.sub(r"^[a-f0-9]{20,}_", "", stem)
        stem = re.sub(r"\.(png|svg|jpe?g|webp|avif)$", "", stem, flags=re.I)
        yr = re.match(r"^([A-Za-z][A-Za-z0-9]{2,20})[_-](?:19|20)\d\d\b", stem)
        if yr:
            trusted.add(yr.group(1))
            continue
        m = re.match(r"(?i)(?:logo[-_ ]?)?([a-z0-9][a-z0-9 &.+-]{1,30}?)[-_ ]?(?:logo|wordmark)(?:[-_ ].*)?$", stem)
        if m and not GENERIC.match(m.group(1)) and m.group(1).lower() not in ("main", "site", "footer", "header", own.split(".")[0]):
            n = m.group(1).replace("-", " ").replace("_", " ").strip()
            trusted.add(n if any(c.isupper() for c in n[1:]) else n.title())
    for a in soup.find_all("a", href=True):
        h = (urlparse(a["href"]).hostname or "").removeprefix("www.")
        if h and own and not h.endswith(own) and not SKIP_HOSTS.search(h + ".") and (a.find("img") or len(a.get_text(strip=True)) < 30):
            label = a.get_text(" ", strip=True)
            names.add(label if 2 <= len(label) <= 30 and not GENERIC.match(label) else h.split(".")[-2].title())
    names = {n for n in names if not ICONISH.match(n.replace(" ", "")) or len(n.split()) > 1 or n.isupper()}
    return sorted(trusted | {n for n in names if n.lower() not in {t.lower() for t in trusted}})


# Business context an article must carry when it only names the competitor by an ordinary word ("Alice").
# The category an article must be about. A bare "AI" is not enough (it's in every headline now).
CATEGORY_RX = re.compile(r"\b(AI security|AI safety|security|secure|cyber\w*|guardrails?|LLMs?|GenAI|generative AI|large language model|"
                         r"prompt injection|jailbreak\w*|red[- ]team\w*|agentic|AI agents?|agent security|MCP|model scanning|"
                         r"machine learning|ML models?|trust (and|&) safety|content moderation|moderation|deepfake\w*|"
                         r"threat\w*|vulnerabilit\w*|CISO|SOC|data protection|AI governance|responsible AI)\b", re.I)
CONTEXT_RX = CATEGORY_RX  # kept for callers that import the old name
JUNK_RX = re.compile(r"obituar|funeral|cremation|memorial|passed away|in loving memory|legacy\.com|\| legacy|"
                     r"high school|college (football|basketball)|\bNFL\b|\bNBA\b|\bMLB\b|\bNHL\b|football|quarterback|touchdown|"
                     r"\bsports?\b|recipe|horoscope|\bAfD\b|Bundestag|election|\bpope\b|vatican|Tolkien|Lord of the Rings|"
                     r"\bstore\b.*\b(opening|hours|sale)\b|celebrity|actress|singer|album", re.I)


def _unique_token(t: str) -> bool:
    """A coined, case-distinctive name ("HiddenLayer", "WonderFence"): safe to match on its own, case-sensitively."""
    return " " not in t and bool(re.search(r"[a-z][A-Z]", t))


def news_terms(comp: Entity) -> tuple[list[str], list[str]]:
    """(distinct, needs_category): domains and coined names match alone; every other name needs a category keyword."""
    names = {re.sub(r"\s*\(.*?\)", "", n).strip() for n in comp.names}
    names = {t for t in names if len(t) > 2}
    distinct = sorted(set(comp.domains) | {t for t in names if _unique_token(t)})
    return distinct, sorted(names - set(distinct))


def relevant(comp: Entity, text: str) -> bool:
    """Is this article about the competitor (the company), not a namesake? Domain or coined name, or name + category."""
    if JUNK_RX.search(text or ""):
        return False
    distinct, other = news_terms(comp)
    for t in distinct:
        if "." in t and re.search(rf"(?<![\w.]){re.escape(t)}(?![\w])", text, re.I):
            return True
        if "." not in t and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text):  # case-sensitive
            return True
    named = any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, 0 if re.fullmatch(r"[A-Z][a-z]+", t) else re.I) for t in other)
    return named and bool(CATEGORY_RX.search(text))


def news(comp: Entity) -> list[dict]:
    distinct, plain = news_terms(comp)
    parts = [f'"{t}"' for t in distinct] + [f'("{t}" AI OR security)' for t in plain]
    q = comp.news_query or " OR ".join(parts)
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
    r = guard.get(url, respect_robots=False)
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = (it.find("source").text if it.find("source") is not None else "") or ""
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "").isoformat()
        except (TypeError, ValueError):
            pub = None
        desc = BeautifulSoup(it.findtext("description") or "", "html.parser").get_text(" ")
        item = {"title": title, "url": link, "source": src, "published": pub, "text": f"{title}. {desc}", "feed": url}
        if relevant(comp, item["text"]):
            out.append(item)
    return out


def purge_irrelevant(con, comp: Entity) -> int:
    """Remove press items already stored that fail the relevance check (e.g. obituaries of people called Alice)."""
    n = 0
    for table, col in (("events", "title"), ("facts", "label")):
        for r in db.rows(con.execute(f"SELECT id, {col} AS t FROM {table} WHERE competitor=? AND module=? AND kind='press'",
                                     (comp.id, MODULE))):
            if not relevant(comp, (r["t"] or "").removeprefix("In the news: ")):
                con.execute(f"DELETE FROM {table} WHERE id=?", (r["id"],))
                n += 1
    return n


# The company's own announcement, distributed by a newswire: a primary source, not a third-party report.
WIRES = re.compile(r"pr newswire|prnewswire|business ?wire|globe ?newswire|accesswire|einpresswire|newsfile", re.I)


def _headline(note: str) -> str:
    """A headline without its " - Publisher" suffix, lowercased and depunctuated: syndicated copies compare equal."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\s+-\s+[^-]+$", "", note or "").lower()).split())


def independent_reports(v: dict) -> int:
    """Distinct headlines among the reports: the same wire story on ten sites counts once."""
    return len({_headline(e.get("note") or "") for e in v["evidence"]} - {""})


def corroborated(v: dict) -> bool:
    """Confirmed: the company announced it (a newswire release), or at least two differently-worded reports carry it."""
    return any(WIRES.search(s or "") for s in v["sources"]) or independent_reports(v) >= 2


def extract_money(items: list[dict], names_rx: re.Pattern) -> tuple[list[Fact], list[Fact], list[Fact]]:
    rounds, arr, acq = {}, {}, {}
    for n in items:
        t = n["text"]
        if not names_rx.search(t):
            continue
        e = [ev(n["url"], f"news coverage ({n['source'] or 'Google News'})", n["title"][:140])]
        m = FUNDING_RX.search(t)
        if m:
            amt = float(m.group(1)) * (1000 if m.group(2).lower().startswith("b") else 1)
            series = (m.group(3) or (SERIES_RX.search(t).group(1) if SERIES_RX.search(t) else "") or "").title()
            key = f"{series or 'round'}:{amt:g}M"
            lead = LEAD_RX.search(t)
            r = rounds.setdefault(key, {"amount_musd": amt, "series": series or None, "investors": set(), "date": n["published"],
                                        "sources": [], "evidence": []})
            if lead:
                r["investors"].add(lead.group(1).strip())
            r["sources"].append(n["source"])
            r["evidence"] += e
            if n["published"] and (not r["date"] or n["published"] < r["date"]):
                r["date"] = n["published"]
        for rx in ARR_RX:
            mm = rx.search(t)
            if mm:
                claim = mm.group(0).strip()
                arr.setdefault(claim.lower(), {"claim": claim, "headline": n["title"], "date": n["published"], "evidence": e})
        if ACQ_RX.search(t):
            acq.setdefault(n["title"][:120], {"headline": n["title"], "date": n["published"], "evidence": e})
    merged: dict[str, dict] = {}
    for k, v in sorted(rounds.items(), key=lambda kv: kv[1]["series"] is None):
        twin = next((mk for mk, mv in merged.items() if mv["amount_musd"] == v["amount_musd"] and
                     abs((datetime.fromisoformat(mv["date"] or "2000-01-01T00:00:00+00:00") -
                          datetime.fromisoformat(v["date"] or "2000-01-01T00:00:00+00:00")).days) < 120), None)
        if twin:
            merged[twin]["investors"] |= v["investors"]; merged[twin]["sources"] += v["sources"]; merged[twin]["evidence"] += v["evidence"]
        else:
            merged[k] = v
    rounds = merged
    fr = [Fact("funding", k, f"{v['series'] or 'Funding'} · ${v['amount_musd']:g}M", {
        "amount_musd": v["amount_musd"], "series": v["series"], "investors": sorted(v["investors"]), "date": v["date"],
        "sources": sorted(set(filter(None, v["sources"])))[:6], "independent_reports": independent_reports(v)},
        facts.CONFIRMED if corroborated(v) else facts.LIKELY, v["evidence"][:4]) for k, v in rounds.items()]
    ar = [Fact("arr_claim", k[:150], v["claim"], {"headline": v["headline"], "date": v["date"]}, facts.LIKELY, v["evidence"]) for k, v in arr.items()]
    # One fact per deal: coverage of the same acquisition within ~4 months (announcement, close) is merged.
    deals: list[dict] = []
    for v in sorted(acq.values(), key=lambda v: v["date"] or "9999"):
        d = datetime.fromisoformat(v["date"]) if v["date"] else None
        prev = deals[-1] if deals else None
        if prev and d and prev["d"] and (d - prev["d"]).days <= 120:
            prev["headlines"].append(v["headline"]); prev["evidence"] += v["evidence"]
            if re.search(r"\bcomplet", v["headline"], re.I):
                prev["completed"] = v["date"]
        else:
            deals.append({"d": d, "date": v["date"], "headlines": [v["headline"]], "evidence": list(v["evidence"]),
                          "completed": v["date"] if re.search(r"\bcomplet", v["headline"], re.I) else None})
    aq = []
    for dl in deals:
        clean = [re.sub(r"\s+-\s+[^-]+$", "", h).strip() for h in dl["headlines"]]
        label = min(clean, key=len)  # the plainest headline ("Check Point acquires Lakera ...")
        aq.append(Fact("m_and_a", f"deal:{(dl['date'] or 'undated')[:7]}", label,
                       {"date": dl["date"], "completed": dl["completed"], "sources": len(dl["headlines"])},
                       facts.CONFIRMED if len(dl["headlines"]) >= 2 else facts.LIKELY, dl["evidence"][:4]))
    return fr, ar, aq


RULES = {
    # Logo extraction is too imprecise to alert on (in live data most "partners" were menu items or customer logos):
    # partners are recorded and counted, but adding or dropping one is not a signal until precision is proven.
    "partner": Rule(severity="medium", on_add=False, on_remove=False, title_add=lambda f: f"New partner listed: {f.label}",
                    title_remove=lambda r: f"Partner removed: {r['label']}"),
    "marketplace": Rule(severity="high", title_add=lambda f: f"New marketplace listing: {f.label}",
                        so_what=lambda f: "Marketplace listings let buyers burn committed cloud spend, a big enterprise procurement accelerator."),
    "partner_program": Rule(severity="high", title_add=lambda f: f"Partner programme signal: {f.label}",
                            so_what=lambda f: "A formal channel/reseller motion is being built."),
    # News search returns a moving window: a story dropping out of it is not a removal, and coming back is not new.
    "press": Rule(severity="low", on_remove=False, append_only=True, title_add=lambda f: f"In the news: {f.label}"),
    "funding": Rule(severity="critical", on_remove=False, append_only=True, title_add=lambda f: f"Funding: {f.label}",
                    so_what=lambda f: "Fresh capital usually means hiring sprees, bigger launches and aggressive pricing in the next 2–3 quarters."),
    "arr_claim": Rule(severity="high", on_remove=False, append_only=True, title_add=lambda f: f"Growth claim: {f.label}"),
    "m_and_a": Rule(severity="critical", on_remove=False, append_only=True, title_add=lambda f: f"M&A: {f.label}"),
}


def run_one(con, comp: Entity) -> dict:
    purged = purge_irrelevant(con, comp)
    obs: list[Fact] = []
    links, home_html = _home_links(comp)
    own = comp.domain.removeprefix("www.")
    ppages = list(comp.partner_pages) + [u for u in links if (urlparse(u).hostname or "").endswith(own) and PARTNER_PATH.search(urlparse(u).path)]
    ppages = list(dict.fromkeys(u.split("#")[0].rstrip("/") for u in ppages))[:4]
    mkt_links = [u for u in links if any(rx.search(u) for rx, _ in MKT_RX)] + list(comp.marketplaces)
    names_all: set[str] = set()
    # Partner pages and marketplace links are found from their homepage; if it or a partner page can't be read,
    # leave what we know alone rather than reporting every partner as removed.
    unread = set() if links else {"partner", "partner_program", "marketplace"}
    for pu in ppages:
        try:
            r = guard.get(pu)
        except Exception:
            unread |= {"partner", "partner_program", "marketplace"}
            continue
        if not r.ok:
            unread |= {"partner", "partner_program", "marketplace"}
            continue
        for n in partner_names(r.text, pu):
            names_all.add(n)
            obs.append(Fact("partner", n.lower(), n, {"page": pu}, facts.LIKELY, [ev(pu, "partner page logo/link extraction")]))
        soup = BeautifulSoup(r.text, "html.parser")
        mkt_links += [urljoin(pu, a["href"]) for a in soup.find_all("a", href=True) if any(rx.search(a["href"]) for rx, _ in MKT_RX)]
        for m in set(PROGRAM_TEXT.findall(soup.get_text(" "))):
            obs.append(Fact("partner_program", m.lower(), m.title(), {"page": pu}, facts.CONFIRMED, [ev(pu, "partner page copy")]))
        if soup.find("form") and re.search(r"partner|reseller", pu, re.I):
            obs.append(Fact("partner_program", "application form", "Partner application form", {"page": pu}, facts.CONFIRMED,
                            [ev(pu, "form detected on partner page (not submitted)")]))
    for u in dict.fromkeys(mkt_links):
        name = next(n for rx, n in MKT_RX if rx.search(u))
        obs.append(Fact("marketplace", u.split("?")[0], name, {"platform": name, "url": u}, facts.CONFIRMED,
                        [ev(u, "link from their own site / configured listing")]))
    try:
        items = news(comp)
    except Exception as e:
        log.info("news failed for %s: %s", comp.id, e)
        items = []
    rx = comp.mention_regex()
    for n in items[:60]:
        if rx.search(n["title"]) and relevant(comp, n["title"]):
            obs.append(Fact("press", n["url"][:300], n["title"][:200], {"source": n["source"], "published": n["published"]},
                            facts.CONFIRMED, [ev(n["url"], "Google News RSS")]))
    fr, ar, aq = extract_money(items, rx)
    obs += fr + ar + aq
    kinds = ["partner", "marketplace", "partner_program", "funding", "arr_claim", "m_and_a", "press"]
    stats = facts.sync(con, comp.id, MODULE, obs, kinds, RULES, unread=unread)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    if not unread:  # a partial read would under-count
        facts.metric(con, comp.id, MODULE, "partners", month, len(names_all))
        facts.metric(con, comp.id, MODULE, "marketplaces", month, len({f.label for f in obs if f.kind == "marketplace"}))
    stats.update(partner_pages=ppages, partners=len(names_all), news=len(items), funding=len(fr), irrelevant_purged=purged,
                 unread=sorted(unread))
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
            log.exception("money failed for %s", comp.id)
            out[comp.id] = {"error": str(e)[:200]}
        log.info("money %-20s %s", comp.id, out[comp.id])
    return out
