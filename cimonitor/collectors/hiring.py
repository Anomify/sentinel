"""Module 6, Hiring intelligence via the public job-board APIs (Greenhouse, Lever, Ashby).

Every role is tagged by function, seniority and region, and its description is mined for
the tech stack. "Firsts" (first Partner Manager, first role in EMEA…) are the strongest
strategic tells, so they get their own alerts. Monthly series feed the trend lines.
"""
from __future__ import annotations

import html as htmllib
import logging
import re
from collections import Counter
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from .. import db, facts, guard
from ..config import Config, Entity
from ..facts import Fact, Rule, ev

log = logging.getLogger(__name__)
MODULE = "hiring"

FUNCTIONS = [  # first match wins; order matters
    ("DevRel", r"developer (relations|advocate|evangelist)|devrel|community (manager|lead)"),
    ("Partnerships", r"partner|channel|alliance|reseller|\bmsp\b|ecosystem"),
    ("Sales engineering", r"solutions? (engineer|architect|consultant)|sales engineer|pre-?sales|\bse\b|field cto"),
    ("Sales", r"account (executive|manager|director)|\b(sdr|bdr|ae)\b|sales|business development|revenue|enterprise rep|federal"),
    ("Marketing", r"marketing|\bpmm\b|demand gen|growth|brand|content|communications|\bpr\b|events|social media|seo"),
    ("Customer success", r"customer (success|support|experience)|implementation|onboarding|technical account|\btam\b|support engineer"),
    ("ML / Research", r"machine learning|\bml\b|research|scientist|\bai\b (engineer|researcher)|threat (intel|research)|adversarial"),
    ("Security", r"security (engineer|analyst|architect|operations)|\bsoc\b|appsec|penetration|red team|grc|compliance|"
                 r"threat (analyst|hunter|expert)|fraud|osint|webint|cyber"),
    ("Product & design", r"product (manager|owner|lead|designer|marketing)|\bpm\b|designer|\bux\b|\bui\b"),
    ("Engineering", r"engineer|developer|\bsre\b|devops|platform|backend|front-?end|full-?stack|software|architect|qa|"
                    r"technical staff|cto office|office of the cto"),
    ("G&A", r"finance|legal|counsel|people|\bhr\b|talent|recruit|accounting|controller|operations|office manager|executive assistant|it\b"),
]
FUNC_RX = [(n, re.compile(r, re.I)) for n, r in FUNCTIONS]
# C-level excludes "CTO Office" (a team) and "Field CTO" (a senior sales-engineering role).
SENIORITY = [("C-level", r"\bchief\b|(?<!field )\bc[etomrfi]o\b(?! office)"), ("VP", r"\bvp\b|vice president|\bsvp\b|\bevp\b"),
             ("Head / Director", r"\bhead of\b|(?<!account )(?<!client )director|field cto"), ("Staff / Principal", r"staff|principal|distinguished"),
             ("Senior", r"\bsenior\b|\bsr\.?\b|account director|client director"),  # an account director is a senior seller, not a manager of people
             ("Manager / Lead", r"manager|\blead\b|team lead"),
             ("Intern", r"intern|co-?op|apprentice"), ("Junior", r"junior|\bjr\.?\b|associate|entry")]
SEN_RX = [(n, re.compile(r, re.I)) for n, r in SENIORITY]
REGIONS = [
    ("EMEA", r"\b(uk|united kingdom|london|england|germany|berlin|munich|france|paris|ireland|dublin|netherlands|amsterdam|"
             r"spain|madrid|poland|warsaw|israel|tel aviv|europe|emea|dubai|uae|sweden|stockholm|switzerland|zurich|italy|denmark|"
             r"belgium|portugal|lisbon|czech|romania|nordics|dach|middle east|africa|saudi)\b"),
    ("APAC", r"\b(singapore|australia|sydney|melbourne|india|bangalore|bengaluru|japan|tokyo|apac|asia|korea|seoul|hong kong|"
             r"new zealand|philippines|vietnam|indonesia|malaysia|china|taiwan)\b"),
    ("LATAM", r"\b(brazil|são paulo|sao paulo|mexico|argentina|colombia|chile|latam|latin america)\b"),
    ("North America", r"\b(us|usa|u\.s\.|united states|remote[- ]us|canada|toronto|new york|nyc|san francisco|austin|seattle|"
                      r"boston|chicago|denver|atlanta|washington|dc|virginia|texas|california|ny|ca|tx|ma|wa|va|co|fl|"
                      r"north america|amer|americas|federal)\b"),
]
REG_RX = [(n, re.compile(r, re.I)) for n, r in REGIONS]
TECH = ["Python", "Go", "Golang", "Rust", "Java", "TypeScript", "JavaScript", "React", "Node.js", "C++", "Kubernetes", "Docker",
        "Terraform", "AWS", "Azure", "GCP", "Kafka", "Postgres", "PostgreSQL", "Snowflake", "Databricks", "Spark", "PyTorch",
        "TensorFlow", "Hugging Face", "LangChain", "LLM", "RAG", "MLOps", "OpenTelemetry", "Splunk", "Elastic", "Datadog",
        "Salesforce", "HubSpot", "Outreach", "Salesloft", "Gong", "Clari", "6sense", "ZoomInfo", "Apollo", "Marketo",
        "Jira", "FedRAMP", "SOC 2", "ISO 27001", "MITRE ATLAS", "OWASP", "MCP", "Bedrock", "Vertex AI", "SageMaker"]
TECH_RX = [(t, re.compile(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", re.I if len(t) > 3 else 0)) for t in TECH]
TITLE_FAMILY = [("Partner Manager", r"partner (manager|development|account)"), ("Channel", r"channel"),
                ("Federal / public sector", r"federal|public sector|government|\bdod\b"), ("Developer relations", r"developer (relations|advocate)"),
                ("Product marketing", r"product marketing|\bpmm\b"), ("Field CTO", r"field cto"), ("Customer success", r"customer success"),
                ("Demand generation", r"demand gen"), ("Solutions architect", r"solutions? architect"), ("Threat research", r"threat|research"),
                ("Marketplace / cloud alliances", r"marketplace|aws|azure|gcp|cloud alliance")]


# "Manager" in these titles names the thing managed (an account, a product, a community), not a team of people.
IC_MANAGER = re.compile(r"\b(account|customer success|success|product|partner|program|project|community|marketing|campaign|"
                        r"channel|territory|content|social media|technical account|solutions|release|brand|event)s? manager\b", re.I)


def tag(title: str, dept: str, location: str, text: str) -> dict:
    t = f"{title} {dept}"
    fn = next((n for n, rx in FUNC_RX if rx.search(title)), None) or next((n for n, rx in FUNC_RX if rx.search(dept)), "Other")
    sen = next((n for n, rx in SEN_RX if rx.search(IC_MANAGER.sub("", title) if n == "Manager / Lead" else title)), "Mid / IC")
    loc = f"{location}"
    reg = next((n for n, rx in REG_RX if rx.search(loc)), None)
    if not reg:
        reg = "Remote" if re.search(r"remote", loc, re.I) else "Unspecified"
    tech = sorted({name for name, rx in TECH_RX if rx.search(text)})
    fam = [n for n, r in TITLE_FAMILY if re.search(r, t, re.I)]
    return {"function": fn, "seniority": sen, "region": reg, "tech": tech, "families": fam}


def _text(h: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(htmllib.unescape(h or ""), "html.parser").get_text(" "))


def fetch_greenhouse(token: str) -> list[dict]:
    j = guard.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true", respect_robots=False)
    out = []
    for x in j.get("jobs", []):
        out.append({"id": f"gh:{x['id']}", "title": x.get("title", ""), "location": (x.get("location") or {}).get("name", ""),
                    "department": ", ".join(d["name"] for d in x.get("departments") or []), "url": x.get("absolute_url"),
                    "posted": x.get("first_published") or x.get("updated_at"), "text": _text(x.get("content", ""))})
    return out


def fetch_lever(token: str) -> list[dict]:
    j = guard.get_json(f"https://api.lever.co/v0/postings/{token}?mode=json", respect_robots=False)
    out = []
    for x in j:
        c = x.get("categories") or {}
        out.append({"id": f"lv:{x['id']}", "title": x.get("text", ""), "location": c.get("location", "") or ", ".join(c.get("allLocations") or []),
                    "department": " / ".join(filter(None, [c.get("department"), c.get("team")])), "url": x.get("hostedUrl"),
                    "posted": datetime.fromtimestamp(x["createdAt"] / 1000, timezone.utc).isoformat() if x.get("createdAt") else None,
                    "text": x.get("descriptionPlain", "") + " " + " ".join(_text(l.get("content", "")) for l in x.get("lists") or [])})
    return out


def fetch_ashby(token: str) -> list[dict]:
    j = guard.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false", respect_robots=False)
    out = []
    for x in j.get("jobs", []):
        loc = x.get("location", "") + (" Remote" if x.get("isRemote") else "")
        out.append({"id": f"ab:{x.get('id') or x.get('jobUrl')}", "title": x.get("title", ""), "location": loc,
                    "department": " / ".join(filter(None, [x.get("department"), x.get("team")])), "url": x.get("jobUrl"),
                    "posted": x.get("publishedAt"), "text": x.get("descriptionPlain", "")})
    return out


def fetch_comeet(token: str) -> list[dict]:
    """Comeet's public careers API. token is "<company-uid>:<api token>", both published in the careers-page widget."""
    uid, tok = token.split(":", 1)
    j = guard.get_json(f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={tok}&details=true", respect_robots=False)
    out = []
    for x in j if isinstance(j, list) else []:
        loc = (x.get("location") or {})
        where = loc.get("name") or ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
        desc = " ".join(_text(d.get("value") or "") for d in x.get("details") or [] if isinstance(d, dict))
        out.append({"id": f"cm:{x.get('uid')}", "title": x.get("name", ""), "location": where + (" Remote" if loc.get("is_remote") else ""),
                    "department": x.get("department") or "", "url": x.get("url_active_page") or x.get("url_comeet_hosted_page"),
                    "posted": x.get("time_updated"), "text": desc})
    return out


def fetch_greetinghr(url: str) -> list[dict]:
    """GreetingHR career sites (common in Korea): each opening is a link to /o/<id>; title first, then team and terms."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    r = guard.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/o/\d+")):
        href = urljoin(r.url, a["href"])
        parts = [x.strip() for x in a.stripped_strings]
        if not parts or href in seen:
            continue
        seen.add(href)
        out.append({"id": f"gh-kr:{re.search(r'/o/(\d+)', href).group(1)}", "title": parts[0], "location": parts[-1] if len(parts) > 2 else "",
                    "department": " / ".join(parts[1:3]) if len(parts) > 2 else "", "url": href, "posted": None, "text": " ".join(parts)})
    return out


FETCH = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby, "comeet": fetch_comeet, "greetinghr": fetch_greetinghr}
API_URL = {"greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs", "lever": "https://api.lever.co/v0/postings/{t}",
           "ashby": "https://api.ashbyhq.com/posting-api/job-board/{t}", "comeet": "https://www.comeet.co/careers-api/2.0/company/{t}/positions",
           "greetinghr": "{t}"}
COMEET_RX = [  # widget init styles: COMEET.init({token, company-uid}) and the WordPress plugin's comeetvar
    r"""token["']?\s*:\s*["']([0-9A-F]{20,})["'][^}]{0,200}?company-uid["']?\s*:\s*["']([0-9A-F]{1,3}\.[0-9A-F]{3})["']""",
    r"""comeet_token["']?\s*:\s*["']([0-9A-F]{20,})["'][^}]{0,200}?comeet_uid["']?\s*:\s*["']([0-9A-F]{1,3}\.[0-9A-F]{3})["']""",
]
BOARD_RX = [("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)"),
            ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)"),
            ("lever", r"jobs\.lever\.co/([a-z0-9_-]+)"), ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)"),
            ("ashby", r"api\.ashbyhq\.com/posting-api/job-board/([a-z0-9_.-]+)")]


def discover(con, comp: Entity) -> list[tuple[str, str]]:
    if comp.ats:
        return list(comp.ats.items())
    found = []
    # 1) links / requests already captured by Module 1, plus the careers page
    pages = [*([comp.careers] if getattr(comp, "careers", None) else []), f"https://{comp.domain}/careers", f"https://{comp.domain}/careers/",
             f"https://{comp.domain}/company/careers", f"https://{comp.domain}/jobs"]
    blob = " ".join(f["key"] for f in facts.active(con, comp.id, "stack", "third_party"))
    for u in pages:
        try:
            r = guard.get(u)
            if r.ok:
                blob += " " + r.text
                break
        except Exception:
            continue
    for ats, rx in BOARD_RX:
        for m in re.findall(rx, blob, re.I):
            if m not in ("embed", "v1"):
                found.append((ats, m.lower()))
    plain = blob.replace('\\"', '"').replace("\\", "")
    for rx in COMEET_RX:
        for tok, uid in re.findall(rx, plain, re.I | re.S):
            found.append(("comeet", f"{uid}:{tok}"))
    # 2) a careers site that lists openings itself (GreetingHR)
    if not found and getattr(comp, "careers", None):
        try:
            if fetch_greetinghr(comp.careers):
                found.append(("greetinghr", comp.careers))
        except Exception:
            pass
    # 3) official APIs with likely tokens
    if not found:
        root = comp.domain.removeprefix("www.").split(".")[0]
        cands = list(dict.fromkeys([comp.id, root, re.sub(r"[^a-z0-9]", "", comp.name.lower().split("(")[0])]))
        for ats in ("greenhouse", "lever", "ashby"):
            for c in cands:
                try:
                    if FETCH[ats](c):
                        found.append((ats, c))
                        break
                except Exception:
                    continue
            if found:
                break
    return list(dict.fromkeys(found))


def _sev(f: Fact) -> str:
    v = f.value
    if v["seniority"] in ("C-level", "VP", "Head / Director") or v["function"] in ("Partnerships", "DevRel"):
        return "high"
    return "medium" if v["function"] in ("Sales", "Marketing", "Sales engineering", "ML / Research") else "low"


RULES = {
    "job": Rule(severity="medium", severity_fn=_sev, title_add=lambda f: f"{{who}} is hiring: {f.label} · {f.value['location'] or f.value['region']}",
                title_remove=lambda r: f"{{who}} closed a job: {r['label']}"),
    "board": Rule(on_add=False, on_remove=False),
}


def run_one(con, comp: Entity) -> dict:
    boards = discover(con, comp)
    if not boards:
        return {"skipped": "no public job board found (set ats: in watchlist.yaml)"}
    jobs = []
    obs: list[Fact] = []
    failed = []
    for ats, token in boards:
        try:
            got = FETCH[ats](token)
        except Exception as e:
            log.info("%s %s failed: %s", ats, token, e)
            failed.append(f"{ats}:{token}")
            continue
        shown = token if ats == "greetinghr" else token.split(":")[0]
        api = API_URL[ats].format(t=shown)
        obs.append(Fact("board", f"{ats}:{shown}", f"{ats.title()} · {shown}", {"ats": ats, "token": shown, "jobs": len(got)},
                        facts.CONFIRMED, [ev(api, f"{ats.title()} public job-board API")]))
        for j in got:
            t = tag(j["title"], j["department"], j["location"], j["title"] + " " + j["text"])
            jobs.append((j, t))
            obs.append(Fact("job", j["id"], j["title"], {**t, "location": j["location"], "department": j["department"],
                                                         "url": j["url"], "posted": j["posted"], "ats": ats},
                            facts.CONFIRMED, [ev(j["url"], f"{ats.title()} public API")]))
    # Firsts, compare against everything ever seen for this competitor
    hist = facts.history(con, comp.id, MODULE, "job")
    seen_fn = {h["value"].get("function") for h in hist}
    seen_reg = {h["value"].get("region") for h in hist}
    seen_fam = {x for h in hist for x in h["value"].get("families", [])}
    seen_ids = {h["key"] for h in hist}
    # A board that didn't answer must not make its open roles look closed.
    stats = facts.sync(con, comp.id, MODULE, obs, ["job", "board"], RULES, unread={"job", "board"} if failed else ())
    if not stats["baseline"]:
        for j, t in jobs:
            if j["id"] in seen_ids:
                continue
            firsts = []
            if t["function"] not in seen_fn:
                firsts.append(f"first {t['function']} role")
            if t["region"] not in seen_reg and t["region"] not in ("Unspecified", "Remote"):
                firsts.append(f"first role in {t['region']}")
            firsts += [f"first {f} role" for f in t["families"] if f not in seen_fam]
            for fs in firsts:
                facts.emit(con, comp.id, MODULE, "first_role", "high", f"{fs.capitalize()}: {j['title']}",
                           detail=j["location"], evidence=[ev(j["url"], "job-board API")],
                           so_what="A first-of-its-kind role signals a new motion, market or channel.")
                seen_fn.add(t["function"]); seen_reg.add(t["region"]); seen_fam.update(t["families"])
    # Monthly series: open roles by function (snapshot) and roles posted per month (from posting dates)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    if not failed:  # a partial read would under-count open roles
        for fn, n in Counter(t["function"] for _, t in jobs).items():
            facts.metric(con, comp.id, MODULE, f"open:{fn}", month, n)
        facts.metric(con, comp.id, MODULE, "open:total", month, len(jobs))
    posted = Counter()
    for h in facts.history(con, comp.id, MODULE, "job"):
        p = (h["value"].get("posted") or h["first_seen"] or "")[:7]
        if p:
            posted[(h["value"].get("function"), p)] += 1
    for (fn, p), n in posted.items():
        facts.metric(con, comp.id, MODULE, f"posted:{fn}", p, n)
    stats.update(boards=[f"{a}:{t}" for a, t in boards], open_roles=len(jobs), failed_boards=failed)
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
            log.exception("hiring failed for %s", comp.id)
            out[comp.id] = {"error": str(e)[:200]}
        log.info("hiring %-20s %s", comp.id, out[comp.id])
    return out
