"""Tool signature library: what a competitor's website loads → which GTM tools they run.

Each signature matches on request hosts (suffix), request URL regexes, cookie names and
HTML snippets. `motion` hints feed the sales-led vs product-led classifier; `means`
is the one-line "so what" used in change alerts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES = {
    "ads": "Advertising & retargeting",
    "abm": "ABM, intent & de-anonymisation",
    "map": "Marketing automation & CRM",
    "analytics": "Web analytics",
    "product": "Product analytics & CDP",
    "replay": "Session replay & heatmaps",
    "chat": "Chat & conversational",
    "scheduling": "Meeting routing & scheduling",
    "demo": "Interactive demos",
    "testing": "A/B testing & personalisation",
    "consent": "Consent management",
    "cms": "CMS & hosting",
    "video": "Video",
    "support": "Support & docs",
    "tag": "Tag management",
    "partner": "Partner & channel",
    "events": "Webinars & events",
    "reviews": "Reviews & social proof",
    "calltracking": "Call tracking",
    "monitoring": "Monitoring & security",
    "payments": "Payments & self-serve",
    "hiring": "Recruiting & careers",
}


@dataclass
class Sig:
    id: str
    name: str
    cat: str
    hosts: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    cookies: list[str] = field(default_factory=list)
    html: list[str] = field(default_factory=list)
    motion: str | None = None          # "sales" | "product"
    means: str | None = None           # what adding this tool signals


S = Sig
SIGNATURES: list[Sig] = [
    # ── Advertising & retargeting
    S("linkedin-insight", "LinkedIn Insight Tag", "ads", ["snap.licdn.com", "px.ads.linkedin.com"], cookies=["^li_sugr$", "^bcookie$", "^lidc$", "^UserMatchHistory$", "^AnalyticsSyncHistory$"],
      html=[r"_linkedin_partner_id"], motion="sales", means="They are running (or preparing) LinkedIn ads and building LinkedIn retargeting audiences."),
    S("google-ads", "Google Ads", "ads", ["googleadservices.com", "googleads.g.doubleclick.net"], [r"googletagmanager\.com/gtag/js\?id=AW-", r"/pagead/"], ["^_gcl_au$"],
      [r"AW-\d{6,}"], means="Paid search / Google Ads conversion tracking is live."),
    S("meta-pixel", "Meta Pixel", "ads", ["connect.facebook.net"], [r"facebook\.com/tr"], ["^_fbp$"], [r"fbq\(['\"]init"], means="Running or retargeting on Meta (Facebook/Instagram)."),
    S("bing-uet", "Microsoft Advertising (UET)", "ads", ["bat.bing.com"], cookies=["^_uetsid$", "^_uetvid$"], means="Running Microsoft/Bing search ads."),
    S("x-pixel", "X (Twitter) Pixel", "ads", ["static.ads-twitter.com", "analytics.twitter.com", "ads-api.twitter.com"], means="Running ads on X."),
    S("reddit-pixel", "Reddit Pixel", "ads", ["redditstatic.com", "alb.reddit.com"], cookies=["^_rdt_uuid$"], means="Running Reddit ads (often developer-audience campaigns)."),
    S("tiktok-pixel", "TikTok Pixel", "ads", ["analytics.tiktok.com"], cookies=["^_ttp$"]),
    S("quora-pixel", "Quora Pixel", "ads", ["q.quora.com"]),
    S("doubleclick", "Google Marketing Platform (DV360/CM360)", "ads", ["fls.doubleclick.net", "ad.doubleclick.net"], means="Programmatic display via Google Marketing Platform."),
    S("stackadapt", "StackAdapt", "ads", ["tags.srv.stackadapt.com", "srv.stackadapt.com"], means="Programmatic B2B display / native ads."),
    S("adroll", "AdRoll", "ads", ["d.adroll.com", "s.adroll.com"], means="Retargeting display ads."),
    S("terminus", "Terminus", "abm", ["tag.terminus.services", "s.terminus.services"], motion="sales", means="ABM advertising to target account lists."),
    S("rollworks", "RollWorks", "abm", ["rollworks.com"], motion="sales", means="ABM advertising to target account lists."),
    S("capterra", "Capterra / Gartner Digital Markets", "reviews", ["ct.capterra.com"], means="Paying for software-directory leads."),
    S("g2", "G2 tracking", "reviews", ["tracking.g2crowd.com", "g2.com/assets"], [r"g2crowd"], means="Using G2 buyer-intent data."),
    # ── ABM / intent / de-anonymisation
    S("6sense", "6sense", "abm", ["j.6sc.co", "b.6sc.co", "epsilon.6sense.com"], cookies=["^_gd_visitor$", "^_gd_session$"], motion="sales", means="Account-based intent: identifying in-market accounts for SDR outreach."),
    S("demandbase", "Demandbase", "abm", ["tag.demandbase.com", "api.company-target.com", "scripts.demandbase.com"], motion="sales", means="ABM / account identification for targeted sales plays."),
    S("warmly", "Warmly", "abm", ["opps-widget.getwarmly.com", "getwarmly.com"], motion="sales", means="De-anonymising website visitors to route warm accounts to sales."),
    S("rb2b", "RB2B", "abm", ["s3-us-west-2.amazonaws.com/b2bjsstore", "ddwl4m2hdecbv.cloudfront.net", "rb2b.com"], [r"b2bjsstore"], motion="sales", means="Person-level visitor identification pushed to sales (LinkedIn profiles)."),
    S("zoominfo", "ZoomInfo WebSights", "abm", ["ws.zoominfo.com", "js.zi-scripts.com"], motion="sales", means="Identifying visiting companies for outbound."),
    S("clearbit", "Clearbit / HubSpot Breeze Intelligence", "abm", ["tag.clearbitscripts.com", "x.clearbitjs.com", "reveal.clearbit.com"], motion="sales", means="Company enrichment/reveal of anonymous visitors."),
    S("koala", "Koala", "abm", ["cdn.getkoala.com", "api2.getkoala.com"], motion="sales", means="Product-and-web intent signals for sales prioritisation."),
    S("vector", "Vector", "abm", ["cdn.vector.co"], motion="sales", means="Contact-level visitor identification for ads + outbound."),
    S("leadfeeder", "Dealfront / Leadfeeder", "abm", ["sc.lfeeder.com", "lftracker.leadfeeder.com"], cookies=["^_lfa$"], motion="sales"),
    S("albacross", "Albacross", "abm", ["serve.albacross.com"], motion="sales"),
    S("commonroom", "Common Room", "abm", ["cdn.cr-relay.com"], means="Community + web signals into a GTM workspace."),
    S("bombora", "Bombora", "abm", ["ml314.com"], motion="sales"),
    S("liveintent", "LiveIntent identity graph", "abm", ["liadm.com"], cookies=["^_li_ss$", "^lidid$", "^_lc2_fpi"], motion="sales",
      means="Email-based identity resolution, matching anonymous visitors to known people for outreach/ads."),
    S("usbrowserspeed", "Identity-resolution pixel (usbrowserspeed)", "abm", ["usbrowserspeed.com"], motion="sales",
      means="Third-party person-level visitor identification (commonly behind tools like RB2B/Vector-style de-anonymisation)."),
    S("mutiny", "Mutiny", "testing", ["client-registry.mutinycdn.com", "api.mutinyhq.com", "mutinycdn.com"], motion="sales", means="Personalising the site per target account (ABM web personalisation)."),
    S("intellimize", "Intellimize", "testing", ["cdn.intellimize.co", "log.intellimize.co"]),
    S("unbounce", "Unbounce", "cms", ["unbounce.com", "ubembed.com"], means="Dedicated paid-campaign landing pages."),
    # ── Marketing automation & CRM
    S("hubspot", "HubSpot", "map", ["js.hs-scripts.com", "js.hsforms.net", "hsforms.com", "js.hs-analytics.net", "js.hs-banner.com", "track.hubspot.com", "js.hscollectedforms.net", "forms.hsforms.com"],
      cookies=["^hubspotutk$", "^__hstc$", "^__hssc$"], html=[r"hs-scripts\.com", r"hbspt\.forms"], means="HubSpot is the marketing automation/CRM backbone."),
    S("marketo", "Marketo", "map", ["munchkin.marketo.net", "mktoresp.com"], [r"/js/forms2/"], ["^_mkto_trk$"], [r"mktoForm_"], motion="sales", means="Enterprise marketing automation (Adobe Marketo)."),
    S("pardot", "Salesforce Account Engagement (Pardot)", "map", ["pi.pardot.com", "go.pardot.com"], cookies=["^visitor_id\\d+"], motion="sales"),
    S("salesforce", "Salesforce", "map", ["force.com", "salesforce-sites.com"], [r"webto(lead|case)"], motion="sales"),
    S("eloqua", "Oracle Eloqua", "map", ["img.en25.com", "elqcfg"], motion="sales"),
    S("customerio", "Customer.io", "map", ["assets.customer.io", "track.customer.io"], motion="product"),
    S("mailchimp", "Mailchimp", "map", ["chimpstatic.com", "list-manage.com"]),
    # ── Analytics
    S("ga4", "Google Analytics 4", "analytics", ["google-analytics.com", "analytics.google.com"], [r"gtag/js\?id=G-", r"/g/collect"], ["^_ga$", "^_ga_"]),
    S("plausible", "Plausible", "analytics", ["plausible.io"]),
    S("fathom", "Fathom", "analytics", ["cdn.usefathom.com"]),
    S("adobe-analytics", "Adobe Analytics", "analytics", ["omtrdc.net", "2o7.net", "assets.adobedtm.com"]),
    S("matomo", "Matomo", "analytics", [], [r"matomo\.js", r"piwik\.js"]),
    S("dreamdata", "Dreamdata", "analytics", ["cdn.dreamdata.cloud"], motion="sales", means="B2B revenue attribution, they're measuring pipeline by channel."),
    S("hockeystack", "HockeyStack", "analytics", ["cdn.jsdelivr.net/npm/hockeystack", "hockeystack.com"], [r"hockeystack"], means="B2B revenue attribution across the funnel."),
    S("factors", "Factors.ai", "analytics", ["app.factors.ai", "fa.factors.ai"], motion="sales"),
    # ── Product analytics & CDP
    S("segment", "Segment", "product", ["cdn.segment.com", "api.segment.io"], ["^ajs_anonymous_id$"], motion="product", means="Customer data platform, instrumenting users across web and product."),
    S("rudderstack", "RudderStack", "product", ["cdn.rudderlabs.com"], motion="product"),
    S("amplitude", "Amplitude", "product", ["cdn.amplitude.com", "api2.amplitude.com", "api.amplitude.com"], cookies=["^AMP_"], motion="product", means="Product analytics on the marketing site, usually a self-serve funnel."),
    S("mixpanel", "Mixpanel", "product", ["cdn.mxpnl.com", "api-js.mixpanel.com"], cookies=["^mp_"], motion="product"),
    S("posthog", "PostHog", "product", ["posthog.com", "us.i.posthog.com", "eu.i.posthog.com"], cookies=["^ph_"], motion="product"),
    S("heap", "Heap", "product", ["cdn.heapanalytics.com", "heapanalytics.com"], cookies=["^_hp2_"], motion="product"),
    S("pendo", "Pendo", "product", ["cdn.pendo.io", "app.pendo.io", "data.pendo.io"], cookies=["^_pendo_"], motion="product", means="In-app guides & product analytics, investing in product-led onboarding."),
    # ── Session replay
    S("hotjar", "Hotjar", "replay", ["static.hotjar.com", "script.hotjar.com", "vars.hotjar.com"], cookies=["^_hj"]),
    S("clarity", "Microsoft Clarity", "replay", ["clarity.ms", "www.clarity.ms"], cookies=["^_clck$", "^_clsk$"]),
    S("fullstory", "FullStory", "replay", ["edge.fullstory.com", "rs.fullstory.com"], cookies=["^fs_uid$"]),
    S("logrocket", "LogRocket", "replay", ["cdn.logr-in.com", "cdn.lr-ingest.io", "r.lr-ingest.io"]),
    S("mouseflow", "Mouseflow", "replay", ["cdn.mouseflow.com"]),
    S("vwo", "VWO", "testing", ["dev.visualwebsiteoptimizer.com"], cookies=["^_vwo"]),
    S("optimizely", "Optimizely", "testing", ["cdn.optimizely.com", "logx.optimizely.com"]),
    # ── Chat
    S("drift", "Drift (Salesloft)", "chat", ["js.driftt.com", "drift.com"], motion="sales", means="Conversational marketing to book meetings from the site."),
    S("qualified", "Qualified (Piper)", "chat", ["js.qualified.com", "app.qualified.com"], motion="sales", means="Pipeline-generation chat for enterprise sales (often with an AI SDR)."),
    S("intercom", "Intercom", "chat", ["widget.intercom.io", "js.intercomcdn.com", "api-iam.intercom.io"], cookies=["^intercom-"]),
    S("hubspot-chat", "HubSpot Chat", "chat", ["js.usemessages.com"], motion="sales"),
    S("zendesk-widget", "Zendesk Messaging", "support", ["static.zdassets.com", "ekr.zdassets.com"]),
    S("crisp", "Crisp", "chat", ["client.crisp.chat"]),
    S("tidio", "Tidio", "chat", ["code.tidio.co"]),
    # ── Scheduling / routing
    S("chilipiper", "Chili Piper", "scheduling", ["js.chilipiper.com", "chilipiper.com"], motion="sales", means="Instant demo booking & lead routing from forms, a demo-led funnel."),
    S("revenuehero", "RevenueHero", "scheduling", ["assets.revenuehero.io", "app.revenuehero.io"], motion="sales", means="Inbound demo scheduling & routing."),
    S("default", "Default", "scheduling", ["import-cdn.default.com", "default.com"], [r"import-cdn\.default\.com"], motion="sales", means="Inbound lead routing & scheduling."),
    S("calendly", "Calendly", "scheduling", ["assets.calendly.com", "calendly.com"]),
    S("hubspot-meetings", "HubSpot Meetings", "scheduling", ["static.hsappstatic.net/MeetingsEmbed"], [r"meetings\.hubspot\.com"], motion="sales"),
    # ── Interactive demos
    S("navattic", "Navattic", "demo", ["js.navattic.com", "capture.navattic.com"], [r"navattic"], means="Self-guided interactive product demos, letting buyers try before talking to sales."),
    S("storylane", "Storylane", "demo", ["js.storylane.io", "app.storylane.io"]),
    S("arcade", "Arcade", "demo", ["demo.arcade.software", "app.arcade.software"]),
    S("walnut", "Walnut", "demo", ["teamwalnut.com"]),
    S("reprise", "Reprise", "demo", ["app.getreprise.com"]),
    S("supademo", "Supademo", "demo", ["app.supademo.com"]),
    # ── Consent
    S("onetrust", "OneTrust", "consent", ["cdn.cookielaw.org", "geolocation.onetrust.com"], cookies=["^OptanonConsent$"]),
    S("cookiebot", "Cookiebot", "consent", ["consent.cookiebot.com"], cookies=["^CookieConsent$"]),
    S("osano", "Osano", "consent", ["cmp.osano.com"]),
    S("cookieyes", "CookieYes", "consent", ["cdn-cookieyes.com"]),
    S("termly", "Termly", "consent", ["app.termly.io"]),
    S("usercentrics", "Usercentrics", "consent", ["app.usercentrics.eu", "web.cmp.usercentrics.eu"]),
    S("finsweet-consent", "Finsweet Cookie Consent", "consent", [], [r"cookie-consent.*finsweet|finsweet.*cookie"], html=[r"fs-cc="]),
    S("iubenda", "iubenda", "consent", ["cdn.iubenda.com"]),
    # ── CMS & hosting
    S("webflow", "Webflow", "cms", ["assets.website-files.com", "cdn.prod.website-files.com", "uploads-ssl.webflow.com"], html=[r"data-wf-site", r"Last Published:"]),
    S("wordpress", "WordPress", "cms", [], [r"/wp-content/", r"/wp-includes/"]),
    S("hubspot-cms", "HubSpot CMS", "cms", ["hubspotusercontent", "hs-sites.com"], html=[r"hs_cos_wrapper"]),
    S("framer", "Framer", "cms", ["framerusercontent.com", "events.framer.com"]),
    S("nextjs", "Next.js", "cms", [], [r"/_next/static/"]),
    S("vercel", "Vercel", "cms", ["vercel-insights.com", "vercel.live"], [r"/_vercel/"]),
    S("contentful", "Contentful", "cms", ["images.ctfassets.net"]),
    S("sanity", "Sanity", "cms", ["cdn.sanity.io"]),
    S("gatsby", "Gatsby", "cms", [], html=[r"___gatsby"]),
    S("cloudflare", "Cloudflare", "cms", ["cdnjs.cloudflare.com", "challenges.cloudflare.com", "static.cloudflareinsights.com"]),
    # ── Video
    S("wistia", "Wistia", "video", ["fast.wistia.com", "fast.wistia.net"]),
    S("vidyard", "Vidyard", "video", ["play.vidyard.com"], motion="sales", means="Video prospecting/sales video tooling."),
    S("vimeo", "Vimeo", "video", ["player.vimeo.com"]),
    S("youtube", "YouTube embeds", "video", ["www.youtube.com/embed", "www.youtube-nocookie.com"], [r"youtube(-nocookie)?\.com/embed"]),
    # ── Support & docs
    S("zendesk", "Zendesk", "support", ["zendesk.com"]),
    S("readme", "ReadMe", "support", ["readme.io"], motion="product"),
    S("gitbook", "GitBook", "support", ["gitbook.io"]),
    S("mintlify", "Mintlify", "support", ["mintlify.com", "mintlify.app"], motion="product"),
    S("statuspage", "Atlassian Statuspage", "support", ["statuspage.io"]),
    S("algolia", "Algolia DocSearch", "support", ["algolia.net", "algolianet.com"]),
    # ── Tag management
    S("gtm", "Google Tag Manager", "tag", ["www.googletagmanager.com"], [r"googletagmanager\.com/gtm\.js"], html=[r"GTM-[A-Z0-9]{4,}"]),
    S("segment-tags", "Tealium", "tag", ["tags.tiqcdn.com"]),
    # ── Partner & channel
    S("partnerstack", "PartnerStack", "partner", ["partnerlinks.io", "js.partnerstack.com", "partnerstack.com"], means="Running an affiliate/partner referral programme."),
    S("impartner", "Impartner PRM", "partner", ["impartner.com"], means="Partner relationship management, a formal channel programme."),
    S("crossbeam", "Crossbeam", "partner", ["crossbeam.com"], means="Account mapping with partners (co-selling)."),
    S("mindmatrix", "Mindmatrix", "partner", ["mindmatrix.net"], means="Channel/partner enablement platform, building a reseller programme."),
    S("allbound", "Allbound", "partner", ["allbound.com"]),
    # ── Events
    S("goldcast", "Goldcast", "events", ["goldcast.io"], means="Running B2B virtual events/webinars."),
    S("on24", "ON24", "events", ["on24.com"]),
    S("zoom-events", "Zoom Events/Webinars", "events", ["zoom.us/webinar", "events.zoom.us"]),
    # ── Call tracking
    S("callrail", "CallRail", "calltracking", ["cdn.callrail.com", "js.callrail.com"], motion="sales", means="Tracking phone calls back to campaigns, phone is a conversion path."),
    S("invoca", "Invoca", "calltracking", ["solutions.invocacdn.com"], motion="sales"),
    # ── Monitoring
    S("sentry", "Sentry", "monitoring", ["browser.sentry-cdn.com", "sentry.io", "ingest.sentry.io"]),
    S("datadog-rum", "Datadog RUM", "monitoring", ["datadoghq-browser-agent.com", "browser-intake-datadoghq.com"]),
    S("recaptcha", "reCAPTCHA", "monitoring", ["www.google.com/recaptcha", "www.gstatic.com/recaptcha"], [r"/recaptcha/"]),
    # ── Recruiting
    S("greenhouse", "Greenhouse", "hiring", ["boards.greenhouse.io", "boards-api.greenhouse.io", "job-boards.greenhouse.io"], html=[r"greenhouse\.io/(embed/)?job_board"]),
    S("lever", "Lever", "hiring", ["jobs.lever.co", "api.lever.co"]),
    S("ashby", "Ashby", "hiring", ["jobs.ashbyhq.com", "api.ashbyhq.com"]),
    S("workable", "Workable", "hiring", ["apply.workable.com"]),
    S("adobe-fonts", "Adobe Fonts (Typekit)", "cms", ["use.typekit.net", "p.typekit.net"]),
    # ── Self-serve
    S("stripe", "Stripe.js", "payments", ["js.stripe.com"], motion="product", means="Card payments on the site, a self-serve purchase path."),
    S("paddle", "Paddle", "payments", ["cdn.paddle.com"], motion="product"),
    S("chargebee", "Chargebee", "payments", ["js.chargebee.com"], motion="product"),
]

BY_ID = {s.id: s for s in SIGNATURES}
_COMPILED = [(s, [re.compile(u, re.I) for u in s.urls], [re.compile(c) for c in s.cookies],
              [re.compile(h, re.I) for h in s.html]) for s in SIGNATURES]


def detect(requests: list[str], hosts: set[str], cookies: list[str], html: str) -> dict[str, list[str]]:
    """→ {sig_id: [matching evidence strings]}"""
    found: dict[str, list[str]] = {}
    for s, urx, crx, hrx in _COMPILED:
        hits = []
        for h in s.hosts:
            if "/" in h:  # host+path hint
                m = next((u for u in requests if h in u), None)
                if m:
                    hits.append(m)
                continue
            m = next((x for x in hosts if x == h or x.endswith("." + h)), None)
            if m:
                hits.append(f"host:{m}")
        for r in urx:
            m = next((u for u in requests if r.search(u)), None)
            if m:
                hits.append(m)
        for r in crx:
            m = next((c for c in cookies if r.search(c)), None)
            if m:
                hits.append(f"cookie:{m}")
        for r in hrx:
            m = r.search(html or "")
            if m:
                hits.append(f"html:{m.group(0)[:60]}")
        if hits:
            found[s.id] = hits[:5]
    return found


# Tracking IDs (Module 2 + cross-domain linking)
ID_PATTERNS = {
    "ga4": (r"\bG-[A-Z0-9]{8,12}\b", "Google Analytics 4"),
    "gtm": (r"\bGTM-[A-Z0-9]{5,9}\b", "Google Tag Manager container"),
    "google_ads": (r"\bAW-\d{8,12}\b", "Google Ads account"),
    "ua": (r"\bUA-\d{4,10}-\d{1,4}\b", "Universal Analytics (legacy)"),
    "meta_pixel": (r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{12,17})['\"]", "Meta Pixel"),
    "linkedin_partner": (r"_linkedin_partner_id\s*=\s*['\"]?(\d{4,10})", "LinkedIn Insight partner ID"),
    "hubspot_portal": (r"js\.hs-scripts\.com/(\d{5,10})\.js|hsforms\.net/forms/[^\"']*portalId[\"':= ]+(\d{5,10})|//js\.hs-analytics\.net/analytics/\d+/(\d{5,10})\.js|hubspotemail\.net\b", "HubSpot portal"),
    "bing_uet": (r"bat\.bing\.com/action/0\?ti=(\d{5,10})|[\"']ti[\"']\s*:\s*[\"'](\d{5,10})[\"']", "Microsoft Ads UET tag"),
    "hotjar": (r"hjid\s*[:=]\s*(\d{5,9})", "Hotjar site"),
    "clarity": (r"clarity\.ms/tag/([a-z0-9]{8,12})", "Microsoft Clarity project"),
    "segment": (r"cdn\.segment\.com/analytics\.js/v1/([A-Za-z0-9]{20,40})", "Segment write key"),
    "sixsense": (r"6sc\.co/j/([a-f0-9-]{20,40})", "6sense token"),
}
ID_RX = {k: re.compile(v[0]) for k, v in ID_PATTERNS.items()}


def extract_ids(text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for k, rx in ID_RX.items():
        for m in rx.finditer(text or ""):
            val = next((g for g in m.groups() if g), None) if m.groups() else m.group(0)
            if val and not (k == "hubspot_portal" and not val.isdigit()):
                out.setdefault(k, set()).add(val)
    return out
