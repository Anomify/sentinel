"""Module 3, DNS & email infrastructure.

Daily snapshots of TXT / SPF / MX / DMARC / DKIM. TXT verification tokens are decoded
into the tools they belong to. A *new* verification is an early-warning signal: domain
verification typically happens weeks before a tool shows up anywhere public.
"""
from __future__ import annotations

import logging
import re

from .. import db, facts
from ..config import Config, Entity
from ..facts import Fact, Rule, ev
from .dnsq import query

log = logging.getLogger(__name__)
MODULE = "dns"

# (regex on TXT value, tool, category, what it implies)
TXT_VERIFICATIONS = [
    (r"^google-site-verification=", "Google (Search Console / Workspace)", "Google", None),
    (r"^MS=ms\d+", "Microsoft 365 / Entra ID", "Productivity", "Microsoft tenant (often Azure/M365 for enterprise customers or Marketplace)."),
    (r"^apple-domain-verification=", "Apple Business", "Productivity", None),
    (r"^atlassian-domain-verification=", "Atlassian (Jira/Confluence)", "Engineering", None),
    (r"^docusign=", "DocuSign", "Sales ops", "Contract e-signature, enterprise deal desk."),
    (r"^adobe-(idp-site|sign)-verification=", "Adobe (Sign / Admin Console)", "Productivity", None),
    (r"^facebook-domain-verification=", "Meta Business Manager", "Advertising", "Verified for Meta ads / Business Manager."),
    (r"^hubspot-(domain|developer)-verification=", "HubSpot", "Marketing automation", None),
    (r"^stripe-verification=", "Stripe", "Payments", "Payments, possible self-serve billing."),
    (r"^slack-domain-verification=", "Slack", "Collaboration", None),
    (r"^zoom[-_]?(domain[-_]verifier|_verify)", "Zoom", "Collaboration", None),
    (r"^ZOOM_verify_", "Zoom", "Collaboration", None),
    (r"^dropbox-domain-verification=", "Dropbox", "Productivity", None),
    (r"^openai-domain-verification=", "OpenAI (ChatGPT Enterprise / API org)", "AI", "Verified an OpenAI org, ChatGPT Enterprise/Team or API usage."),
    (r"^anthropic-domain-verification", "Anthropic (Claude for Work / API)", "AI", "Verified an Anthropic org, Claude Enterprise/Team or API usage."),
    (r"^cursor-domain-verification", "Cursor", "Engineering", "Cursor business plan for engineering."),
    (r"^docker-verification=", "Docker", "Engineering", "Docker Business, likely publishing images on Docker Hub."),
    (r"^jetbrains-domain-verification=", "JetBrains", "Engineering", None),
    (r"^pendo-domain-verification=", "Pendo", "Product analytics", "In-app guides/analytics, often ahead of a product-led push."),
    (r"^miro-verification=", "Miro", "Collaboration", None),
    (r"^figma-domain-verification=", "Figma", "Design", None),
    (r"^cisco-ci-domain-verification=", "Cisco (Webex / Duo / Cisco ecosystem)", "Identity", "Cisco identity verification (Webex/Duo, or a Cisco ecosystem relationship)."),
    (r"^jamf-site-verification=", "Jamf", "IT", None),
    (r"^status-page-domain-verification=", "Atlassian Statuspage", "Support", None),
    (r"^parallels-domain-verification=", "Parallels", "IT", None),
    (r"^_?gitlab-pages-verification-code=", "GitLab Pages", "Engineering", None),
    (r"^(mindmatrix|mm)-?(domain-)?verif", "Mindmatrix", "Partner", "Channel enablement platform, a partner/reseller programme is being stood up."),
    (r"^impartner", "Impartner", "Partner", "Partner relationship management, formal channel programme."),
    (r"^partnerstack", "PartnerStack", "Partner", "Affiliate / referral partner programme."),
    (r"^crossbeam", "Crossbeam", "Partner", "Partner account mapping for co-selling."),
    (r"^(globalsign|_globalsign)-domain-verification=", "GlobalSign", "Security", None),
    (r"^(sectigo|comodo)", "Sectigo", "Security", None),
    (r"^(knowbe4|kb4)-site-verification", "KnowBe4", "Security", "Security awareness training, SOC 2 / compliance programme."),
    (r"^(vanta|drata)", "Vanta/Drata", "Security", "Compliance automation (SOC 2 / ISO)."),
    (r"^onetrust-domain-verification=", "OneTrust", "Privacy", None),
    (r"^(_)?amazonses", "Amazon SES", "Email", None),
    (r"^mailjet", "Mailjet", "Email", None),
    (r"^(sendinblue|brevo)-code", "Brevo", "Email", None),
    (r"^mgverify|^mailgun", "Mailgun", "Email", None),
    (r"^salesforce|^sfdc", "Salesforce", "CRM", None),
    (r"^(ahrefs-site-verification|semrush)", "SEO tooling (Ahrefs/Semrush)", "Marketing", None),
    (r"^yandex-verification", "Yandex", "Marketing", None),
    (r"^(webexdomainverification|webex)", "Webex", "Collaboration", None),
    (r"^(twilio|segment)-", "Twilio/Segment", "Product", None),
    (r"^(intercom)", "Intercom", "Support", None),
    (r"^(notion)", "Notion", "Productivity", None),
    (r"^(linear)", "Linear", "Engineering", None),
    (r"^(canva)", "Canva", "Design", None),
    (r"^(smartsheet)", "Smartsheet", "Productivity", None),
    (r"^(airtable)", "Airtable", "Productivity", None),
    (r"^(have-i-been-pwned|hibp)", "Have I Been Pwned", "Security", None),
    (r"^(brave-ledger)", "Brave Creators", "Marketing", None),
    (r"^DirectFedAuthUrl=", "Federated SSO (Okta/ADFS → M365)", "Identity", "Federated identity for Microsoft 365."),
    (r"^NV=", "Unknown verification token (NV=)", "Unknown", None),
]
TXT_RX = [(re.compile(p, re.I), *rest) for p, *rest in TXT_VERIFICATIONS]

SPF_SENDERS = [
    (r"_spf\.google\.com", "Google Workspace"), (r"spf\.protection\.outlook\.com", "Microsoft 365"),
    (r"hubspotemail\.net", "HubSpot (marketing email)"), (r"mktomail\.com|marketo", "Marketo"),
    (r"_spf\.salesforce\.com|exacttarget", "Salesforce / Marketing Cloud"), (r"pardot", "Pardot"),
    (r"sendgrid\.net", "SendGrid"), (r"mailgun\.org", "Mailgun"), (r"amazonses\.com", "Amazon SES"),
    (r"servers\.mcsv\.net|mandrillapp", "Mailchimp / Mandrill"), (r"mail\.zendesk\.com", "Zendesk (support email)"),
    (r"stspg-customer\.com", "Atlassian Statuspage"), (r"_spf\.atlassian\.net", "Atlassian"),
    (r"freshdesk|freshemail", "Freshworks"), (r"customer\.io|customeriomail", "Customer.io"),
    (r"intercom", "Intercom"), (r"sparkpostmail", "SparkPost"), (r"outreach", "Outreach"),
    (r"salesloft", "Salesloft"), (r"_spf\.docusign", "DocuSign"), (r"greenhouse", "Greenhouse"),
    (r"mindmatrix", "Mindmatrix (partner/channel platform)"), (r"impartner", "Impartner (PRM)"), (r"zoho", "Zoho"), (r"postmarkapp|mtasv\.net", "Postmark"), (r"_spf\.mlsend|mailerlite", "MailerLite"),
    (r"spf\.brevo|sendinblue", "Brevo"), (r"klaviyo", "Klaviyo"), (r"rsgsv\.net", "Mailchimp"),
]
MX_PROVIDERS = [
    (r"google\.com$|googlemail\.com$", "Google Workspace"), (r"protection\.outlook\.com$", "Microsoft 365"),
    (r"pphosted\.com$", "Proofpoint"), (r"mimecast", "Mimecast"), (r"barracudanetworks", "Barracuda"),
    (r"iphmx\.com$", "Cisco Secure Email"), (r"messagelabs|symantec", "Broadcom Email Security"),
    (r"zoho", "Zoho Mail"), (r"secureserver\.net$", "GoDaddy"), (r"mailgun", "Mailgun"), (r"amazonaws", "Amazon SES"),
]
DMARC_VENDORS = [(r"dmarcian", "dmarcian"), (r"valimail|vali\.email", "Valimail"), (r"agari", "Agari"),
                 (r"ondmarc|redsift", "Red Sift OnDMARC"), (r"easydmarc", "EasyDMARC"), (r"powerdmarc", "PowerDMARC"),
                 (r"uriports", "URIports"), (r"dmarc\.postmarkapp", "Postmark DMARC"), (r"cloudflare", "Cloudflare DMARC"),
                 (r"mimecast", "Mimecast"), (r"proofpoint|emaildefense", "Proofpoint")]
DKIM_SELECTORS = {"google": "Google Workspace", "selector1": "Microsoft 365", "selector2": "Microsoft 365",
                  "hs1": "HubSpot", "hs2": "HubSpot", "k1": "Mailchimp", "s1": "SendGrid", "s2": "SendGrid",
                  "mte1": "Mailgun?", "mandrill": "Mandrill", "zendesk1": "Zendesk", "zendesk2": "Zendesk",
                  "m1": "Marketo?", "sf1": "Salesforce", "pm": "Postmark", "cio": "Customer.io", "intercom": "Intercom",
                  "smtpapi": "SendGrid", "mxvault": "Mimecast", "dkim": "generic"}


def decode_txt(v: str) -> tuple[str, str, str | None] | None:
    for rx, tool, cat, means in TXT_RX:
        if rx.search(v):
            return tool, cat, means
    return None


def spf_includes(spf: str, depth=0) -> list[str]:
    inc = re.findall(r"(?:include|redirect)[:=]([^\s]+)", spf)
    out = list(inc)
    if depth < 1:  # expand one level (e.g. a vendor's own include list)
        for d in inc:
            for t in query(d, "TXT"):
                if t.startswith("v=spf1"):
                    out += spf_includes(t, depth + 1)
    return out


RULES = {
    "verification": Rule(severity="high", title_add=lambda f: f"New domain verification: {f.label}",
                         title_remove=lambda r: f"Verification removed: {r['label']}",
                         so_what=lambda f: f.value.get("means") or "New TXT verifications typically precede a tool going live by weeks."),
    "txt": Rule(on_add=False, on_remove=False),
    "email_sender": Rule(severity="medium", title_add=lambda f: f"New email sender authorised: {f.label}",
                         so_what=lambda f: "A new SPF include means a new system sending email as them (marketing, support, sales engagement)."),
    "mx": Rule(severity="medium", on_change=True, title_add=lambda f: f"Mail routing via {f.label}"),
    "dmarc": Rule(severity="low", on_change=True, on_add=False),
    "dkim": Rule(severity="low", title_add=lambda f: f"DKIM selector live: {f.key} ({f.label})"),
    "ns": Rule(severity="medium", on_change=True, on_add=False),
}


def run_one(con, comp: Entity) -> dict:
    d = comp.domain.removeprefix("www.")
    if not d:
        return {"skipped": "no domain"}
    src = f"https://dns.google/resolve?name={d}&type=TXT"
    obs: list[Fact] = []
    txts = query(d, "TXT")
    for t in txts:
        dec = decode_txt(t)
        key = t[:200]
        obs.append(Fact("txt", key, t[:120], {"value": t}, facts.CONFIRMED, [ev(src, "DNS TXT (DNS-over-HTTPS)")]))
        if dec:
            tool, cat, means = dec
            obs.append(Fact("verification", key, tool, {"category": cat, "means": means, "record": t[:200]},
                            facts.CONFIRMED, [ev(src, "DNS TXT verification record", t[:80])]))
        if t.lower().startswith("v=spf1"):
            obs.append(Fact("spf", "spf", t[:200], {"record": t}, facts.CONFIRMED, [ev(src, "SPF record")]))
            for inc in spf_includes(t):
                name = next((n for rx, n in SPF_SENDERS if re.search(rx, inc, re.I)), None)
                obs.append(Fact("email_sender", inc, name or inc, {"include": inc, "vendor": name},
                                facts.CONFIRMED if name else facts.LIKELY, [ev(src, "SPF include", inc)]))
    mx_by: dict[str, set] = {}
    for mx in query(d, "MX"):
        host = mx.split()[-1].rstrip(".") if " " in mx else mx
        mx_by.setdefault(next((n for rx, n in MX_PROVIDERS if re.search(rx, host, re.I)), host), set()).add(host)
    for prov, hosts in mx_by.items():
        obs.append(Fact("mx", prov, prov, {"hosts": sorted(hosts)}, facts.CONFIRMED,
                        [ev(f"https://dns.google/resolve?name={d}&type=MX", "MX record", ", ".join(sorted(hosts))[:120])]))
    dm = next((t for t in query(f"_dmarc.{d}", "TXT") if t.lower().startswith("v=dmarc1")), None)
    if dm:
        tags = dict(x.strip().split("=", 1) for x in dm.split(";") if "=" in x)
        vendors = sorted({n for rx, n in DMARC_VENDORS if re.search(rx, dm, re.I)})
        obs.append(Fact("dmarc", "dmarc", f"p={tags.get('p', '?')}", {"policy": tags.get("p"), "pct": tags.get("pct"),
                        "rua": tags.get("rua"), "vendors": vendors, "record": dm}, facts.CONFIRMED,
                        [ev(f"https://dns.google/resolve?name=_dmarc.{d}&type=TXT", "DMARC record")]))
    for sel, vendor in DKIM_SELECTORS.items():
        n = f"{sel}._domainkey.{d}"
        recs = query(n, "TXT") or query(n, "CNAME")
        if recs:
            obs.append(Fact("dkim", sel, vendor, {"record": recs[0][:120]}, facts.CONFIRMED, [ev(f"https://dns.google/resolve?name={n}", "DKIM selector lookup")]))
    ns = sorted(query(d, "NS"))
    if ns:
        obs.append(Fact("ns", "ns", ", ".join(ns)[:120], {"nameservers": ns}, facts.CONFIRMED, [ev(f"https://dns.google/resolve?name={d}&type=NS", "NS records")]))
    kinds = ["txt", "verification", "spf", "email_sender", "mx", "dmarc", "dkim", "ns"]
    if not obs:
        return {"error": "no DNS answers"}
    return facts.sync(con, comp.id, MODULE, obs, kinds, RULES)


def run(cfg: Config, only: str | None = None) -> dict:
    out = {}
    for comp in cfg.competitors:
        if only and comp.id != only:
            continue
        try:
            with db.connect() as con:
                out[comp.id] = run_one(con, comp)
        except Exception as e:
            log.exception("dns failed for %s", comp.id)
            out[comp.id] = {"error": str(e)[:200]}
        log.info("dns %-20s %s", comp.id, out[comp.id])
    return out
