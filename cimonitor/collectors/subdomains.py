"""Module 4 — Subdomain & certificate monitoring.

Certificate Transparency (crt.sh, Cert Spotter fallback) reveals every hostname that gets
a public TLS certificate, often weeks before anything links to it. Each name is resolved
over DNS-over-HTTPS and classified by hosting. Public hosts are screenshotted on first
sight and when they change. Names that resolve to private/internal addresses are recorded
as facts ("the DNS entry exists") and are NEVER contacted.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
from collections import Counter
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from .. import db, facts, guard
from ..config import Config, Entity
from ..facts import Fact, Rule, ev
from ..signatures import extract_ids
from .dnsq import cname_chain, query
from .fetch import Fetcher

log = logging.getLogger(__name__)
MODULE = "subdomains"
MAX_SHOTS_PER_RUN = 25  # page fetches per run (politeness budget)
MAX_HOSTS = 400         # hostnames resolved per competitor per run (newest certificates first)

HOSTING_CNAME = [
    (r"proxy-ssl\.webflow\.com|\.webflow\.io$|cdn\.webflow\.com", "Webflow"),
    (r"\.hubspot\.(net|com)$|hs-sites|hubspot-?cname|\.hscoltfront\.net|hs-?sitesdomain", "HubSpot"),
    (r"\.zendesk\.com$", "Zendesk"), (r"\.freshdesk\.com$", "Freshdesk"), (r"\.intercom\.help$|custom\.intercom", "Intercom"),
    (r"cloudfront\.net$", "AWS CloudFront"), (r"elb\.amazonaws\.com$", "AWS (load balancer)"),
    (r"s3[.-][\w-]*\.?amazonaws\.com$|s3-website", "AWS S3"), (r"amazonaws\.com$|awsglobalaccelerator", "AWS"),
    (r"azurewebsites\.net$|cloudapp\.(azure|net)|azurefd\.net$|trafficmanager\.net$|azureedge\.net$|azurestaticapps", "Azure"),
    (r"ghs\.googlehosted\.com$|googleusercontent|\.run\.app$|appspot\.com$|web\.app$|firebaseapp", "Google Cloud"),
    (r"vercel-dns\.com$|\.vercel\.app$", "Vercel"), (r"netlify\.(app|com)$", "Netlify"), (r"github\.io$", "GitHub Pages"),
    (r"herokudns|herokuapp", "Heroku"), (r"fastly\.net$", "Fastly"), (r"cdn\.cloudflare\.net$|pages\.dev$", "Cloudflare"),
    (r"framer\.(app|website)$|sites\.framer", "Framer"), (r"readme\.io$", "ReadMe"), (r"gitbook\.io$|gitbook-hosting", "GitBook"),
    (r"stspg-customer\.com$|statuspage\.io$", "Atlassian Statuspage"), (r"greenhouse\.io$", "Greenhouse"),
    (r"lever\.co$", "Lever"), (r"ashbyhq\.com$", "Ashby"), (r"mintlify", "Mintlify"), (r"unbounce", "Unbounce"),
    (r"instapage", "Instapage"), (r"mktossl\.com$|marketo", "Marketo"), (r"pardot|salesforce-sites|force\.com$", "Salesforce"),
    (r"wpengine|kinsta|pantheon", "WordPress host"), (r"shopify", "Shopify"), (r"okta(preview)?\.com$", "Okta"),
    (r"auth0\.com$", "Auth0"), (r"stape\.(io|net)|stape\.", "Stape (server-side GTM)"), (r"atlassian\.net$", "Atlassian"),
    (r"impartner|mindmatrix|allbound|partnerstack|crossbeam", "Partner portal (PRM)"), (r"goldcast|on24|hopin", "Events platform"),
    (r"akamai|edgekey|edgesuite", "Akamai"), (r"wixdns", "Wix"), (r"squarespace", "Squarespace"),
]
HOSTING_IP = [
    ("198.202.211.1/32", "Webflow"), ("75.2.70.75/32", "Webflow"), ("99.83.190.102/32", "Webflow"),
    ("199.60.103.0/24", "HubSpot"), ("185.199.108.0/22", "GitHub Pages"), ("76.76.21.0/24", "Vercel"),
    ("75.2.60.5/32", "Netlify"), ("151.101.0.0/16", "Fastly"), ("104.16.0.0/13", "Cloudflare"), ("172.64.0.0/13", "Cloudflare"),
    ("188.114.96.0/20", "Cloudflare"), ("216.198.0.0/18", "Zendesk"), ("35.190.0.0/17", "Google Cloud"),
    ("34.0.0.0/9", "Google Cloud"), ("35.184.0.0/13", "Google Cloud"), ("13.32.0.0/15", "AWS CloudFront"),
    ("18.64.0.0/14", "AWS CloudFront"), ("3.0.0.0/9", "AWS"), ("52.0.0.0/10", "AWS"), ("54.0.0.0/8", "AWS"),
    ("20.0.0.0/8", "Azure"), ("40.64.0.0/10", "Azure"), ("13.64.0.0/11", "Azure"),
]
_NETS = [(ipaddress.ip_network(n), p) for n, p in HOSTING_IP]
PTR_HOSTING = [(r"amazonaws\.com$", "AWS"), (r"googleusercontent\.com$|1e100\.net$", "Google Cloud"),
               (r"cloudapp\.azure\.com$|msedge\.net$", "Azure"), (r"cloudflare", "Cloudflare"), (r"linode|akamai", "Akamai/Linode"),
               (r"digitalocean", "DigitalOcean"), (r"hetzner", "Hetzner"), (r"ovh", "OVH")]

INFRA_WORDS = set("""www api app apps dev develop development stage staging stg prod production test testing qa uat sandbox
demo vpn mail smtp imap mx auth sso login id identity logging logs log vault argocd argo temporal grafana prometheus kibana
k8s kube cluster cdn static assets img images media files download downloads status support help docs doc kb portal
admin console dashboard internal intranet git gitlab github jenkins ci cd build registry harbor sentry jira confluence
wiki ns ns1 ns2 autodiscover lyncdiscover sip enterpriseregistration enterpriseenrollment email links click track
go info em e mta bounce partners partner careers jobs blog news events community forum store shop us eu uk de ap
apac emea global int ext edge proxy gateway gw lb monitor metrics health beta preview alpha canary next new old
legacy v1 v2 v3 secure cloudflare-test test1 test2 m mobile""".split())
# Internal tooling: never contacted even when it resolves to a public IP (guardrail: record, don't reach).
INTERNAL_TOOLING = re.compile(
    r"(^|[.-])(vault|argo|argocd|temporal|grafana|prometheus|kibana|elastic|jenkins|gitlab|harbor|registry|k8s|kube|"
    r"cluster|vpn|sso|okta|adfs|auth|login|admin|internal|intranet|corp|jira|confluence|wiki|sentry|splunk|logging|logs?|git|github|"
    r"metrics|monitor|consul|nomad|rancher|airflow|kafka|redis|db|database|mongo|postgres|mysql|smtp|imap|mail|exchange|"
    r"autodiscover|lyncdiscover|sip|ldap|rdp|ssh|bastion|jump|nexus|artifactory|sonar|teamcity|bamboo|spinnaker|"
    r"api-internal|backoffice|ops|devops|infra|kargo|atlantis|terraform|airbyte|metabase|superset|retool|n8n|langfuse|"
    r"mlflow|jupyter|notebook|backstage|buildkite|drone|concourse|flux|keycloak|pgadmin|rabbitmq|minio|opensearch|"
    r"clickhouse|unleash|alerts?|pagerduty|opsgenie|status-internal|staging-api|dev-api|preview-api|tools?|dash|"
    r"analytics-internal|ci|cd|build|deploy|runner|agent-runner|worker|queue|cron|scheduler|vpn\d*|proxy|gateway|gw|edge|"
    r"origin|lb|ingress|nat|bastion\d*|mgmt|management|sandbox|lab|labs-internal)([.-]|\d|$)", re.I)
# Hosts Sentinel may contact (screenshot / fetch): clearly public-facing names, or campaign/product names that
# pass the internal-tooling filter. Everything else is recorded from CT/DNS only.
PUBLIC_FACING = set("""www docs doc developer developers dev-portal support help status blog partners partner community
careers jobs events learn academy trust security register store shop go info get try demo resources news press
investors hub university training certifications certification marketplace app console signup login-page""".split())
ENV_RX = re.compile(r"(^|[.-])(dev|stage|staging|stg|qa|uat|test|sandbox|preview|beta|canary)([.-]|\d|$)", re.I)


def ct_names(domain: str) -> tuple[dict[str, str], str]:
    """{hostname: earliest cert date}, sources. crt.sh (retried — it is often overloaded) merged with Cert Spotter."""
    import time
    names: dict[str, str] = {}
    sources = []

    def add(n: str, d: str):
        n = n.strip().lower().rstrip(".")
        if n.endswith(domain):
            names[n] = min(x for x in (names.get(n), d) if x) if (names.get(n) or d) else ""

    for attempt in range(3):
        try:
            r = guard.get(f"https://crt.sh/?q=%25.{domain}&output=json", timeout=90, respect_robots=False)
            for c in r.json():
                for n in str(c.get("name_value", "")).split("\n"):
                    add(n, (c.get("not_before") or "")[:10])
            sources.append("crt.sh")
            break
        except Exception as e:
            log.info("crt.sh attempt %d failed for %s: %s", attempt + 1, domain, e)
            time.sleep(4 * (attempt + 1))
    after, pages = None, 0
    try:
        while pages < (1 if "crt.sh" in sources else 4):  # paginate only when crt.sh is unavailable (free-tier rate limit)
            url = f"https://api.certspotter.com/v1/issuances?domain={domain}&include_subdomains=true&expand=dns_names"
            j = guard.get_json(url + (f"&after={after}" if after else ""), timeout=40, respect_robots=False)
            for c in j:
                for n in c.get("dns_names", []):
                    add(n, (c.get("not_before") or "")[:10])
            pages += 1
            if not j or len(j) < 50:
                break
            after = j[-1]["id"]
        sources.append("Cert Spotter")
    except Exception as e:
        log.info("Cert Spotter failed for %s: %s", domain, e)
    return names, " + ".join(sources) or "none"


def classify(host: str) -> dict:
    chain = cname_chain(host)
    ips = [a for a in query(host, "A")] + [a for a in query(host, "AAAA")]
    hosting = next((p for c in chain for rx, p in HOSTING_CNAME if re.search(rx, c, re.I)), None)
    if not hosting:
        for ip in ips:
            try:
                a = ipaddress.ip_address(ip)
            except ValueError:
                continue
            hosting = next((p for n, p in _NETS if a.version == n.version and a in n), None)
            if hosting:
                break
    if not hosting and ips:
        try:
            ptr = query(ipaddress.ip_address(ips[0]).reverse_pointer, "PTR")
            hosting = next((p for x in ptr for rx, p in PTR_HOSTING if re.search(rx, x, re.I)), None)
        except ValueError:
            pass
    private = bool(ips) and all(guard.is_private(i) for i in ips)
    return {"ips": ips[:6], "cname": chain[-1] if chain else None, "cname_chain": chain[:4], "hosting": hosting or ("Private network" if private else "Unknown"),
            "private": private, "resolves": bool(ips or chain)}


def label_kind(host: str, domain: str) -> str:
    sub = host[: -len(domain) - 1] if host != domain else ""
    if not sub:
        return "apex"
    parts = re.split(r"[.-]", sub)
    if re.search(r"gtm|sgtm|tagging|^ss$|^sst$", parts[0]):
        return "tracking"
    if ENV_RX.search(sub):
        return "environment"
    if all(p in INFRA_WORDS or p.isdigit() or len(p) <= 2 for p in parts):
        return "infrastructure"
    return "campaign / product"


def page_signals(html: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    title = (soup.title.string or "").strip()[:140] if soup.title and soup.title.string else ""
    text = re.sub(r"\s+", " ", soup.get_text(" "))
    return {"title": title, "hash": hashlib.sha1(text[:20000].encode()).hexdigest()[:16],
            "words": len(text.split()), "last_published": (re.search(r"Last Published: ([^-]+?)\s*-->", html or "") or [None, None])[1]}


def run_one(con, cfg: Config, comp: Entity, fetcher: Fetcher | None, shots_left: list[int]) -> dict:
    domain = comp.domain.removeprefix("www.")
    if not domain:
        return {"skipped": "no domain"}
    names, source = ct_names(domain)
    if not names:
        return {"error": f"no CT results ({source})"}
    prev = {f["key"]: f for f in facts.active(con, comp.id, MODULE, "subdomain")}
    truncated = 0
    if len(names) > MAX_HOSTS:
        # Huge CT histories (e.g. hyperscaler subdomains): keep hosts we already track + the newest certificates.
        keep = set(prev) | {h for h, _ in sorted(names.items(), key=lambda kv: kv[1] or "", reverse=True)[:MAX_HOSTS]}
        truncated = len(names) - len(keep)
        names = {h: d for h, d in names.items() if h in keep}
    obs: list[Fact] = []
    page_ids: dict[str, dict] = {}
    for host in sorted(names):
        if host.startswith("*."):
            obs.append(Fact("wildcard", host, host, {"first_cert": names[host]}, facts.CONFIRMED,
                            [ev(f"https://crt.sh/?q={host}", f"Certificate Transparency ({source})")]))
            continue
        info = classify(host)
        info["first_cert"] = names[host]
        info["kind"] = label_kind(host, domain)
        e = [ev(f"https://crt.sh/?q={host}", f"Certificate Transparency ({source})", f"first cert {names[host]}")]
        conf = facts.CONFIRMED
        old = prev.get(host, {}).get("value") or {}
        info.update({k: old[k] for k in ("title", "hash", "status", "screenshot", "last_published", "words") if k in old})
        if info["private"]:
            info["note"] = "Resolves to a private address — recorded only, never contacted."
        elif INTERNAL_TOOLING.search(host[: -len(domain) - 1] if host != domain else ""):
            info["internal"] = True
            info["note"] = "Internal-tooling hostname — recorded from CT/DNS only, never contacted."
        elif not _contactable(host, domain, info["kind"]):
            info["note"] = "Not a clearly public-facing name — recorded from CT/DNS only, not contacted."
        elif info["resolves"] and fetcher and _due(host, prev, old) and shots_left[0] > 0:
            # Fetch on first sight, then re-check weekly; screenshot on first sight and on change.
            shots_left[0] -= 1
            f = fetcher.get(f"https://{host}/", screenshot=f"{comp.id}-sub")
            info["checked_at"] = db.now()
            if f.html:
                sig = page_signals(f.html)
                changed = bool(old.get("hash")) and old.get("hash") != sig["hash"]
                if host not in prev or changed or not old.get("screenshot"):
                    info.update(sig, status=f.status, screenshot=f.screenshot)
                    if f.screenshot:
                        e.append(ev(f"https://{host}/", "headless browser screenshot", sig["title"], f.screenshot))
                else:
                    info.update(status=f.status)
                for k, vals in extract_ids(f.html).items():
                    for v in vals:
                        page_ids.setdefault(f"{k}:{v}", {"type": k, "id": v, "hosts": []})["hosts"].append(host)
            elif f.error:
                info["status"] = f.error[:80]
        elif old.get("checked_at"):
            info["checked_at"] = old["checked_at"]
        elif not info["resolves"]:
            info["note"] = "Certificate issued but no DNS record now (decommissioned, internal-only, or not yet live)."
            conf = facts.LIKELY
        obs.append(Fact("subdomain", host, host, info, conf, e))
    hosting = Counter(f.value.get("hosting") for f in obs if f.kind == "subdomain")
    for k, v in page_ids.items():
        obs.append(Fact("page_id", k, k, v, facts.CONFIRMED, [ev(f"https://{v['hosts'][0]}/", "tracking ID on subdomain page")]))
    # CT logs are append-only history: a hostname never genuinely disappears from them, and how much each
    # source returns varies run to run. So known hosts are always carried forward (no false removals);
    # real decommissioning shows up as the host no longer resolving.
    if True:
        seen = {f.key for f in obs}
        for kind in ("subdomain", "wildcard"):
            for f in facts.active(con, comp.id, MODULE, kind):
                if f["key"] not in seen:
                    obs.append(Fact(kind, f["key"], f["label"], f["value"], f["confidence"], f["evidence"] or []))
    stats = facts.sync(con, comp.id, MODULE, obs, ["subdomain", "wildcard", "page_id"], RULES)
    facts.metric(con, comp.id, MODULE, "subdomains", datetime.now(timezone.utc).strftime("%Y-%m"),
                 sum(1 for f in obs if f.kind == "subdomain"))
    stats.update(source=source, hosting=dict(hosting.most_common(8)), truncated=truncated)
    return stats


def _contactable(host: str, domain: str, kind: str) -> bool:
    if host in (domain, f"www.{domain}"):
        return True
    first = host[: -len(domain) - 1].split(".")[0]
    return first in PUBLIC_FACING or kind == "campaign / product"


def _due(host: str, prev: dict, old: dict) -> bool:
    if host not in prev or not old.get("checked_at"):
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(old["checked_at"])
    except ValueError:
        return True
    return age.days >= 7


def _sub_sev(f: Fact) -> str:
    k = f.value.get("kind")
    return "high" if k in ("campaign / product", "tracking") else "medium" if k == "environment" else "low"


def _sub_so_what(f: Fact) -> str | None:
    v = f.value
    if v.get("private") or v.get("internal"):
        return "Internal hostname exposed via a public certificate — signals internal tooling/infrastructure (not contacted)."
    if v.get("kind") == "campaign / product":
        return "A new non-infrastructure name with a certificate usually means a campaign, microsite or product launch is coming."
    if v.get("kind") == "tracking":
        return "A first-party tagging endpoint (server-side GTM): their tracking survives ad blockers and browser restrictions."
    if v.get("kind") == "environment":
        return "New environment — something is being built or staged."
    return None


def _recent_cert(f: Fact, days: int = 30) -> bool:
    """Only alert on hosts whose first certificate is recent; an old host newly observed is not news."""
    fc = f.value.get("first_cert")
    if not fc:
        return True
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(fc).replace(tzinfo=timezone.utc)).days <= days
    except ValueError:
        return True


RULES = {
    "subdomain": Rule(severity="medium", severity_fn=_sub_sev, so_what=_sub_so_what, alert_if=_recent_cert, on_remove=False,
                      title_add=lambda f: f"New subdomain: {f.key}" + (f" ({f.value.get('hosting')})" if f.value.get("hosting") not in (None, "Unknown") else ""),
                      title_remove=lambda r: f"Subdomain gone from CT/DNS: {r['key']}"),
    "wildcard": Rule(severity="medium", alert_if=_recent_cert, on_remove=False, title_add=lambda f: f"New wildcard certificate: {f.key}",
                     so_what=lambda f: "Wildcard certs usually mean a new environment or multi-tenant service."),
    "page_id": Rule(on_add=False, on_remove=False),
}


def run(cfg: Config, only: str | None = None, screenshots: bool = True) -> dict:
    out, shots = {}, [MAX_SHOTS_PER_RUN]
    fetch_ctx = Fetcher(cfg.settings) if screenshots else None
    try:
        fetcher = fetch_ctx.__enter__() if fetch_ctx else None
        for comp in cfg.competitors:
            if only and comp.id != only:
                continue
            try:
                with db.connect() as con:
                    out[comp.id] = run_one(con, cfg, comp, fetcher, shots)
            except Exception as e:
                log.exception("subdomains failed for %s", comp.id)
                out[comp.id] = {"error": str(e)[:200]}
            log.info("subdomains %-20s %s", comp.id, out[comp.id])
    finally:
        if fetch_ctx:
            fetch_ctx.__exit__(None, None, None)
    return out


__all__ = ["run", "classify", "label_kind", "requests"]
