# Validation: Sentinel vs. the manual HiddenLayer deep dive

Sentinel ran a full scan of `hiddenlayer.com` on **14 October 2026**: every module, using passive, public sources only. It took **353 seconds**. This page checks the output against the findings referenced in the manual research brief.

| Manual finding (from the brief) | Sentinel (automated) | Module | Confidence |
|---|---|---|---|
| Server-side GTM on `atxgtm` | `atxgtm.hiddenlayer.com` classified as a **tracking** subdomain (Google Cloud), flagged as server-side tagging | 4 + 2 | likely |
| `ai-costs` subdomain → campaign coming | `ai-costs.hiddenlayer.com`, first certificate 12 Jun 2026, behind Cloudflare Access, screenshotted | 4 | confirmed |
| `hiddenlayer-stg` staging site | `hiddenlayer-stg.webflow.io` found. **Its robots.txt disallows crawling**, so Sentinel records that it exists but does not collect its pages (see "Differences" below) | 5 | confirmed |
| Mindmatrix → partner programme | **Mindmatrix authorised in SPF** (`spf.mindmatrix.net`), plus a partner programme page, reseller paths and partner logos (Tevora, BlueIvy, mnemonic, ASE) | 3 + 7 | confirmed / likely |
| `book_demo_form` conversion | GTM container `GTM-PZG4BT6S`: GA4 event **`book_demo_form`** fires on the HubSpot form listener `hs_form_submission` | 2 | confirmed |
| Warmly + HubSpot + demo-only → sales-led | **Sales-led**, from Warmly, LiveIntent, an identity-resolution pixel, HubSpot, a "Book a demo" CTA and no self-serve path | 1 | inferred |
| LinkedIn Ads question | **No LinkedIn Insight Tag** on the homepage or demo page, before or after consent. The LinkedIn Ad Library can't be automated (robots.txt), so a manual-check deep link is provided | 1 + 8 | confirmed (tag) |
| Internal hostnames | 36 hostnames found in certificate transparency, 22 of them recorded without being contacted: 16 internal-tooling names (vault, argocd, temporal, logging, splunk…), `intel` and `predator`, which **resolve to private IPs**, and 4 other names that aren't clearly public | 4 | confirmed |

Sentinel also found these, which the brief didn't list:

- Warmly, LiveIntent and Google Ads fire **before cookie consent**.
- DNS verifications for Anthropic, OpenAI, Cursor, Pendo, Docker and JetBrains; Okta-federated Microsoft 365.
- A `hackathon.` microsite titled "AWS Clash of Agents — Partners Edition", and a HubSpot-hosted `register.` page for API registration.
- An AWS Marketplace listing; **Series B $100M (Sep 2026)** and Series A $50M.
- 15 open roles, 87% of them go-to-market, including federal and UK solutions architects.

## Differences, and why

- **Staging pages are not diffed for HiddenLayer.** Webflow staging sites ship with `Disallow: /`. A manual reviewer can open them; Sentinel's guardrails won't crawl them. The pre-launch radar still works on any staging host that allows crawling, and on production sitemap diffs and publish stamps.
- **Call tracking.** No CallRail or Invoca script loaded on the pages captured. If the manual finding came from another page, add that URL to the competitor's `pages:` list.
- **"Mindmatrix verified".** Sentinel found Mindmatrix in the SPF record rather than as a TXT verification token. The conclusion is the same: a channel-enablement platform is sending email as them.

## Guardrail audit

Across the final scan of all six competitors, **114 hostnames were flagged record-only, and none of them appear in the fetch log**. 17 requests were declined by policy: robots.txt on staging sites, and LinkedIn's Ad Library. Every decision is shown on the Coverage page.

## Change-detection stability

Repeat runs of DNS, the stack/GTM capture and certificate transparency against HiddenLayer produced **zero spurious alerts**. Certificate-transparency coverage varies between runs (crt.sh is often overloaded), so known hosts are carried forward, and "new subdomain" alerts fire only for certificates issued in the last 30 days.
