import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { motion } from "motion/react";
import { ArrowRight, ExternalLink, FileSearch } from "lucide-react";
import { useApi } from "../lib/api";
import type { Fact, Overview } from "../lib/types";
import { ago, day, pct } from "../lib/format";
import { Sparkline } from "../components/charts";
import { EventDrawer, EventRow } from "../components/signal";
import { Button, Card, Chip, Confidence, cx, Empty, EvidenceList, fade, Monogram, PageHeader, Skeleton, Tabs, Thumb, useEntity, useMeta } from "../components/ui";

export function CompetitorList() {
  const { data } = useApi<Overview>("/api/overview?days=30");
  const meta = useMeta();
  const comps = meta.entities.filter((e) => !e.is_brand);
  return (
    <div>
      <PageHeader title="Competitors" sub="Your watchlist, ranked by how much each competitor moved in the last 30 days. Add any domain from Deep dives."
        right={<Link to="/deep-dives?new=1"><Button variant="primary" size="sm">Add a domain</Button></Link>} />
      <Card className="overflow-hidden">
        <div className="hidden grid-cols-[1.6fr_.8fr_.8fr_.8fr_1fr_120px] gap-4 border-b border-line px-6 py-3 text-[11px] uppercase tracking-[.1em] text-ink-3 md:grid">
          <span>Competitor</span><span>Signals</span><span>Launch</span><span>AI share</span><span>Latest</span><span>30 days</span>
        </div>
        <div className="divide-y divide-line">
          {(data?.competitors ?? comps.map((c) => ({ id: c.id, name: c.name, changes: 0, critical: 0, launch: 0, ai_share: null, latest: null, color: c.color }))).map((c: any, i: number) => (
            <motion.div key={c.id} {...fade} transition={{ ...fade.transition, delay: i * 0.03 }}>
              <Link to={`/competitors/${c.id}`} className="grid grid-cols-[1fr_auto] items-center gap-4 px-6 py-4 hover:bg-hover/60 md:grid-cols-[1.6fr_.8fr_.8fr_.8fr_1fr_120px]">
                <div className="flex min-w-0 items-center gap-3">
                  <Monogram id={c.id} size={32} />
                  <div className="min-w-0"><div className="truncate text-[14px] text-ink">{c.name}</div><div className="text-[12px] text-ink-3">{meta.entities.find((e) => e.id === c.id)?.domains[0]}</div></div>
                </div>
                <div className="hidden text-[14px] text-ink tnum md:block">{c.changes}{c.critical ? <span className="ml-1.5 text-[12px] text-high">{c.critical} high</span> : null}</div>
                <div className="hidden text-[14px] text-ink tnum md:block">{pct(c.launch)}</div>
                <div className="hidden text-[14px] text-ink tnum md:block">{pct(c.ai_share)}</div>
                <div className="hidden truncate text-[12.5px] text-ink-2 md:block">{c.latest?.title ?? "—"}</div>
                <div className="flex items-center justify-end gap-3">
                  {data && <Sparkline values={data.timeline.slice(-30).map((d) => Number(d[c.id]) || 0)} color={c.color} width={80} height={20} />}
                  <ArrowRight size={14} className="text-ink-3" />
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      </Card>
    </div>
  );
}

type TabId = "signals" | "stack" | "tracking" | "dns" | "subdomains" | "radar" | "hiring" | "money" | "ads" | "pages";
const TABS: { id: TabId; label: string; module?: string }[] = [
  { id: "signals", label: "Signals" }, { id: "stack", label: "Stack", module: "stack" }, { id: "tracking", label: "Tracking", module: "gtm" },
  { id: "dns", label: "DNS & email", module: "dns" }, { id: "subdomains", label: "Subdomains", module: "subdomains" },
  { id: "radar", label: "Pre-launch", module: "radar" }, { id: "hiring", label: "Hiring", module: "hiring" },
  { id: "money", label: "Partners & money", module: "money" }, { id: "ads", label: "Ads", module: "ads" }, { id: "pages", label: "Pages" },
];
const KIND_LABEL: Record<string, string> = {
  tool: "Tools", conversion_path: "Conversion paths", motion: "Motion", third_party: "Third-party domains", cookies: "Cookies",
  container: "GTM containers", tracking_id: "Tracking IDs", conversion: "Conversion events", gtm_tag: "GTM tags", sgtm: "Server-side tagging", funnel: "Funnel reading",
  verification: "TXT verifications", email_sender: "Email senders (SPF)", mx: "Mail routing", dmarc: "DMARC", dkim: "DKIM selectors", spf: "SPF", ns: "Nameservers", txt: "Raw TXT records",
  subdomain: "Hostnames", wildcard: "Wildcard certificates", page_id: "IDs on subdomains",
  staging_site: "Staging sites", staging_page: "Pre-launch pages", publish: "Publishes", repo: "Public repos", site_page: "Production pages",
  job: "Open roles", board: "Job boards", partner: "Partners", marketplace: "Marketplaces", partner_program: "Partner programme", funding: "Funding",
  arr_claim: "Growth claims", m_and_a: "M&A", press: "Press", ad_channel: "Ad channels", ad_creative: "Creatives",
};
const KIND_ORDER = Object.keys(KIND_LABEL);
const HIDE_KINDS = new Set(["txt", "page_id", "site_page", "spf"]);

export function CompetitorDetailPage() {
  const { id = "" } = useParams();
  const e = useEntity(id);
  const [picked, setTab] = useState<TabId | null>(null);
  const { data } = useApi<any>(`/api/competitors/${id}`);
  const tab: TabId = picked ?? (data && !data.events.length ? "stack" : "signals");
  if (!e) return <Empty title="Competitor not found" />;
  const counts: Record<string, number> = data?.modules ?? {};
  return (
    <div>
      <motion.div {...fade} className="mb-8 flex flex-wrap items-end justify-between gap-5">
        <div className="flex items-center gap-4">
          <Monogram id={id} size={52} />
          <div>
            <div className="eyebrow mb-2"><Link to="/competitors" className="hover:text-ink">Competitors</Link> / {e.tier}</div>
            <h1 className="text-[34px] leading-none tracking-[-0.03em] text-ink">{e.name}</h1>
            <a href={`https://${e.domains[0]}`} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink">{e.domains[0]}<ExternalLink size={11} /></a>
          </div>
        </div>
        <Link to={`/deep-dives/${id}`}><Button variant="primary" size="sm"><FileSearch size={13} />Open deep dive</Button></Link>
      </motion.div>
      <Tabs value={tab} onChange={setTab} tabs={TABS.map((t) => ({ id: t.id, label: t.label, count: t.module ? (counts[t.module] ?? 0) + (t.module === "gtm" ? counts["gtm_links"] ?? 0 : 0) : undefined }))} />
      <div className="pt-6">
        {!data ? <Skeleton className="h-80 rounded-2xl" /> :
          tab === "signals" ? <SignalsTab events={data.events} /> :
          tab === "pages" ? <PagesTab pages={data.pages_status} /> :
          <ModuleTab competitor={id} module={TABS.find((t) => t.id === tab)!.module!} />}
      </div>
    </div>
  );
}

function SignalsTab({ events }: { events: any[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!events.length) return <Card><Empty title="No signals yet">Modules alert from their second run onward.</Empty></Card>;
  return (
    <Card className="overflow-hidden">
      <div className="divide-y divide-line">{events.map((ev) => <EventRow key={ev.id} e={ev} onOpen={setOpen} showCompetitor={false} />)}</div>
      <EventDrawer id={open} onClose={() => setOpen(null)} />
    </Card>
  );
}

function PagesTab({ pages }: { pages: any[] }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {pages.map((p) => {
        const s = p.latest, sig = s?.signals ?? {};
        return (
          <Card key={p.url} className="overflow-hidden">
            <Thumb name={s?.screenshot} className="aspect-[16/9] w-full rounded-none border-0 border-b" />
            <div className="p-5">
              <div className="flex items-center justify-between gap-3 text-[12px] text-ink-3">
                <span className="uppercase tracking-[.1em]">{p.kind}</span><span>{s ? `checked ${ago(s.fetched_at)}` : "not yet checked"}</span>
              </div>
              {sig.h1?.[0] && <div className="mt-2 text-[17px] leading-snug tracking-[-0.01em] text-ink">“{sig.h1[0]}”</div>}
              {s?.meta && <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{s.meta}</p>}
              <div className="mt-3 flex flex-wrap gap-1.5">
                {(sig.ctas ?? []).slice(0, 4).map((c: string) => <span key={c} className="rounded-full bg-sunken px-2.5 py-0.5 text-[11.5px] text-ink-2">{c}</span>)}
                {(sig.prices ?? []).slice(0, 4).map((c: string) => <span key={c} className="rounded-full bg-sunken px-2.5 py-0.5 font-mono text-[11px] text-ink-2">{c}</span>)}
              </div>
              <a href={p.url} target="_blank" rel="noreferrer" className="mt-3 block truncate text-[12px] text-ink-3 hover:text-ink">{p.url}</a>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

export function ModuleTab({ competitor, module }: { competitor: string; module: string }) {
  const { data } = useApi<Fact[]>(`/api/facts?competitor=${competitor}&module=${module}`);
  const { data: links } = useApi<Fact[]>(module === "gtm" ? `/api/facts?competitor=${competitor}&module=gtm_links` : null);
  const [showRaw, setShowRaw] = useState(false);
  const all = useMemo(() => [...(data ?? []), ...(links ?? [])], [data, links]);
  const kinds = useMemo(() => {
    const g = new Map<string, Fact[]>();
    for (const f of all) g.set(f.kind, [...(g.get(f.kind) ?? []), f]);
    return [...g.entries()].filter(([k]) => showRaw || !HIDE_KINDS.has(k)).sort((a, b) => KIND_ORDER.indexOf(a[0]) - KIND_ORDER.indexOf(b[0]));
  }, [all, showRaw]);
  if (!data) return <Skeleton className="h-64 rounded-2xl" />;
  if (!all.length) return <Card><Empty title="Nothing collected yet">Run this module from the Run menu, or rescan from the deep dive.</Empty></Card>;
  return (
    <div className="space-y-5">
      <div className="flex justify-end"><Chip active={showRaw} onClick={() => setShowRaw((v) => !v)}>Show raw records</Chip></div>
      {kinds.map(([kind, fs]) => <KindCard key={kind} kind={kind} facts={fs} />)}
    </div>
  );
}

function KindCard({ kind, facts }: { kind: string; facts: Fact[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const [all, setAll] = useState(false);
  const shown = all ? facts : facts.slice(0, 12);
  return (
    <Card className="overflow-hidden">
      <div className="flex items-baseline justify-between px-6 pb-3 pt-5">
        <h3 className="text-[14px] text-ink">{KIND_LABEL[kind] ?? kind}</h3>
        <span className="text-[12px] text-ink-3 tnum">{facts.length}</span>
      </div>
      <div className="divide-y divide-line border-t border-line">
        {shown.map((f) => (
          <div key={f.id}>
            <button onClick={() => setOpen(open === f.id ? null : f.id)} className="grid w-full grid-cols-[1fr_auto] items-center gap-4 px-6 py-3 text-left hover:bg-hover/60">
              <div className="min-w-0">
                <div className="truncate text-[13.5px] text-ink">{f.label}</div>
                <div className="truncate text-[12px] text-ink-3">{summary(f)}</div>
              </div>
              <div className="flex items-center gap-4"><Confidence c={f.confidence} /><span className="hidden w-24 text-right text-[11.5px] text-ink-3 sm:block">since {day(f.first_seen)}</span></div>
            </button>
            {open === f.id && (
              <div className="space-y-3 bg-sunken/50 px-6 py-4">
                {f.value?.screenshot && <Thumb name={f.value.screenshot} className="aspect-[16/9] w-full max-w-sm" />}
                <div className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-1 text-[12px]">
                  {Object.entries(f.value || {}).filter(([k, v]) => v != null && v !== "" && k !== "screenshot").slice(0, 16).map(([k, v]) => (
                    <div key={k} className="contents"><span className="text-ink-3">{k.replace(/_/g, " ")}</span><span className="break-words text-ink-2">{Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)}</span></div>
                  ))}
                </div>
                <EvidenceList items={f.evidence || []} />
              </div>
            )}
          </div>
        ))}
      </div>
      {facts.length > 12 && <button onClick={() => setAll((a) => !a)} className="w-full border-t border-line py-3 text-[12.5px] text-ink-3 hover:text-ink">{all ? "Show fewer" : `Show all ${facts.length}`}</button>}
    </Card>
  );
}

function summary(f: Fact): string {
  const v = f.value || {};
  switch (f.kind) {
    case "tool": return `${v.category_label ?? ""}${v.phases ? " · " + v.phases.join(", ") : ""}${v.fires_before_consent ? " · fires before consent" : ""}`;
    case "subdomain": return [v.kind, v.hosting, v.title, v.private ? "private IP · not contacted" : v.internal ? "internal tooling · not contacted" : null, v.first_cert ? `cert ${v.first_cert}` : null].filter(Boolean).join(" · ");
    case "job": return [v.function, v.seniority, v.location || v.region].filter(Boolean).join(" · ");
    case "verification": return [v.category, v.means].filter(Boolean).join(" · ");
    case "conversion": return `${v.platform ?? ""}${v.fires_on?.length ? " · fires on " + v.fires_on.join(", ") : ""}`;
    case "motion": return (v.reasons ?? []).join(" · ");
    case "funding": return [v.date?.slice(0, 10), v.investors?.join(", ")].filter(Boolean).join(" · ");
    case "ad_channel": return `${v.status} · ${v.reading ?? ""}`;
    case "repo": return [v.language, v.stars != null ? `${v.stars}★` : null, v.pushed_at ? `pushed ${v.pushed_at.slice(0, 10)}` : null].filter(Boolean).join(" · ");
    case "press": return [v.source, v.published?.slice(0, 10)].filter(Boolean).join(" · ");
    case "email_sender": return v.include ?? "";
    case "staging_site": return v.crawl ?? v.url ?? "";
    default: return Object.entries(v).filter(([, x]) => typeof x === "string" || typeof x === "number").slice(0, 2).map(([k, x]) => `${k.replace(/_/g, " ")}: ${x}`).join(" · ");
  }
}

export { cx };
