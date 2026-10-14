import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, Lock } from "lucide-react";
import { useApi } from "../lib/api";
import type { Fact, Launch } from "../lib/types";
import { ago, day, pct } from "../lib/format";
import { BarList, LineChart } from "../components/charts";
import { Card, CardHeader, Chip, Confidence, cx, Empty, EntityDot, Monogram, PageHeader, Skeleton, Thumb, useEntity, useMeta, useSeries } from "../components/ui";

const comps = (meta: ReturnType<typeof useMeta>) => meta.entities.filter((e) => !e.is_brand);

/* ── GTM stack ──────────────────────────────────────────────────────────────── */
export function StackPage() {
  const meta = useMeta();
  const { data } = useApi<any>("/api/stack");
  const [cat, setCat] = useState<string | null>(null);
  const cs = comps(meta);
  return (
    <div>
      <PageHeader eyebrow="Modules 1 & 2" title="GTM stack" sub="What every competitor actually runs — captured from a headless browser before and after cookie consent — plus what their tag manager says they optimise for." />
      {!data ? <Skeleton className="h-96 rounded-2xl" /> : (
        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.rows.map((r: any) => {
              const e = meta.entities.find((x) => x.id === r.id)!;
              return (
                <Card key={r.id} className="p-6">
                  <div className="flex items-center gap-3"><Monogram id={r.id} size={28} /><span className="text-[14px] text-ink">{e.name}</span>
                    {r.motion && <span className="ml-auto rounded-full bg-sunken px-2.5 py-0.5 text-[12px] text-ink-2">{r.motion.label}</span>}</div>
                  <div className="mt-5 grid grid-cols-3 gap-3 text-[12px] text-ink-3">
                    <div><div className="text-[22px] leading-none text-ink tnum">{Object.keys(r.tools).length}</div><div className="mt-1">tools</div></div>
                    <div><div className="text-[22px] leading-none text-ink tnum">{r.third_party}</div><div className="mt-1">3rd-party hosts</div></div>
                    <div><div className="text-[22px] leading-none text-ink tnum">{r.conversions.length}</div><div className="mt-1">conversions</div></div>
                  </div>
                  {r.conversions.length > 0 && <div className="mt-4 truncate text-[12.5px] text-ink-2">Optimises for: {r.conversions.slice(0, 4).join(", ")}</div>}
                  {r.sgtm.length > 0 && <div className="mt-1 truncate text-[12.5px] text-ink-2">Server-side tagging: {r.sgtm.join(", ")}</div>}
                  {r.motion && <div className="mt-3 line-clamp-2 text-[12px] leading-relaxed text-ink-3">{r.motion.value.reasons?.join(" · ")}</div>}
                </Card>
              );
            })}
          </div>
          <Card className="overflow-hidden">
            <CardHeader title="Stack matrix" sub="● confirmed · ◐ likely · red dot = fires before cookie consent" />
            <div className="flex flex-wrap gap-1.5 px-6 pb-5"><Chip active={!cat} onClick={() => setCat(null)}>All</Chip>
              {data.categories.map((c: any) => <Chip key={c.id} active={cat === c.id} onClick={() => setCat(cat === c.id ? null : c.id)}>{c.label}</Chip>)}</div>
            <div className="overflow-x-auto border-t border-line">
              <table className="w-full min-w-[760px] text-[12.5px]">
                <thead><tr className="border-b border-line text-left text-ink-3">
                  <th className="sticky left-0 bg-elev px-6 py-3">Tool</th>
                  {cs.map((c) => <th key={c.id} className="px-3 py-3 text-center"><div className="flex flex-col items-center gap-1.5"><EntityDot color={c.color} size={7} /><span className="max-w-[90px] truncate">{c.name.replace(/\s*\(.*\)/, "")}</span></div></th>)}
                </tr></thead>
                <tbody>
                  {data.categories.filter((c: any) => !cat || c.id === cat).map((c: any) => (
                    <FragmentRows key={c.id} c={c} rows={data.rows} cs={cs} />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

function FragmentRows({ c, rows, cs }: { c: any; rows: any[]; cs: any[] }) {
  const label = (tid: string) => rows.map((r) => r.tools[tid]?.label).find(Boolean) ?? tid;
  return (
    <>
      <tr><td colSpan={cs.length + 1} className="bg-sunken/60 px-6 py-2 text-[11px] uppercase tracking-[.1em] text-ink-3">{c.label}</td></tr>
      {c.tools.map((tid: string) => (
        <tr key={tid} className="border-b border-line last:border-0">
          <td className="sticky left-0 bg-elev px-6 py-2.5 text-ink">{label(tid)}</td>
          {cs.map((co) => {
            const t = rows.find((r) => r.id === co.id)?.tools[tid];
            return (
              <td key={co.id} className="px-3 py-2.5 text-center" title={t ? `since ${day(t.first_seen)} · ${t.phases?.join(", ")}` : ""}>
                {t ? <span className="relative inline-block">
                  <span className={cx("inline-block size-2.5 rounded-full", t.confidence === "confirmed" ? "bg-ink" : "border border-ink bg-[linear-gradient(90deg,var(--ink)_50%,transparent_50%)]")} />
                  {t.pre_consent && <span className="absolute -right-1.5 -top-1 size-1.5 rounded-full bg-crit" />}
                </span> : <span className="text-line-strong">·</span>}
              </td>
            );
          })}
        </tr>
      ))}
    </>
  );
}

/* ── Infrastructure: DNS & email + subdomains ───────────────────────────────── */
export function InfrastructurePage() {
  const meta = useMeta();
  const cs = comps(meta);
  const [sel, setSel] = useState(cs[0]?.id ?? "");
  const { data: dns } = useApi<Fact[]>(sel ? `/api/facts?competitor=${sel}&module=dns` : null);
  const { data: subs } = useApi<Fact[]>(sel ? `/api/facts?competitor=${sel}&module=subdomains&kind=subdomain` : null);
  const verifs = useMemo(() => {
    const by = new Map<string, Fact & { n: number }>();
    for (const f of (dns ?? []).filter((f) => f.kind === "verification")) {
      const cur = by.get(f.label);
      by.set(f.label, cur ? { ...cur, n: cur.n + 1, first_seen: cur.first_seen > f.first_seen ? cur.first_seen : f.first_seen } : { ...f, n: 1 });
    }
    return [...by.values()].sort((a, b) => b.first_seen.localeCompare(a.first_seen) || a.label.localeCompare(b.label));
  }, [dns]);
  const senders = (dns ?? []).filter((f) => f.kind === "email_sender");
  const mail = (dns ?? []).filter((f) => ["mx", "dmarc", "dkim", "ns"].includes(f.kind));
  const groups = useMemo(() => {
    const g: Record<string, Fact[]> = {};
    for (const s of subs ?? []) {
      const k = s.value.private || s.value.internal ? "Internal (recorded only)" : s.value.kind === "campaign / product" ? "Campaign / product" : s.value.kind === "environment" ? "Environments" : s.value.kind === "tracking" ? "Tracking" : "Infrastructure";
      (g[k] ??= []).push(s);
    }
    return Object.entries(g).sort((a, b) => ["Campaign / product", "Tracking", "Environments", "Infrastructure", "Internal (recorded only)"].indexOf(a[0]) - ["Campaign / product", "Tracking", "Environments", "Infrastructure", "Internal (recorded only)"].indexOf(b[0]));
  }, [subs]);
  return (
    <div>
      <PageHeader eyebrow="Modules 3 & 4" title="Infrastructure" sub="DNS verifications decoded into tools (the early-warning signal almost nobody watches), email senders, and every hostname that has received a public TLS certificate." />
      <div className="mb-6 flex flex-wrap gap-1.5">{cs.map((c) => <Chip key={c.id} active={sel === c.id} onClick={() => setSel(c.id)}><EntityDot color={c.color} size={7} />{c.name}</Chip>)}</div>
      {!dns || !subs ? <Skeleton className="h-96 rounded-2xl" /> : (
        <div className="grid gap-5 xl:grid-cols-[1fr_1.3fr]">
          <div className="space-y-5">
            <Card className="overflow-hidden">
              <CardHeader title="Tool verifications" sub="TXT records, newest first" right={<span className="text-[12px] text-ink-3 tnum">{verifs.length}</span>} />
              <div className="divide-y divide-line border-t border-line">
                {verifs.map((v) => (
                  <div key={v.id} className="flex items-start justify-between gap-4 px-6 py-3">
                    <div className="min-w-0"><div className="text-[13.5px] text-ink">{v.label}{v.n > 1 && <span className="ml-1.5 text-ink-3">×{v.n}</span>}</div>{v.value.means && <div className="mt-0.5 text-[12px] leading-relaxed text-ink-3">{v.value.means}</div>}</div>
                    <span className="shrink-0 text-[11.5px] text-ink-3">{v.value.category}</span>
                  </div>
                ))}
                {!verifs.length && <Empty title="No verifications found" />}
              </div>
            </Card>
            <Card className="overflow-hidden">
              <CardHeader title="Who sends email as them" sub="SPF includes" />
              <div className="flex flex-wrap gap-1.5 px-6 pb-6">{senders.map((s) => <span key={s.id} className="rounded-full bg-sunken px-3 py-1 text-[12.5px] text-ink-2">{s.label}</span>)}</div>
              <div className="divide-y divide-line border-t border-line">
                {mail.map((m) => <div key={m.id} className="flex justify-between gap-4 px-6 py-2.5 text-[12.5px]"><span className="text-ink-3">{m.kind.toUpperCase()}</span><span className="truncate text-ink-2">{m.label}</span></div>)}
              </div>
            </Card>
          </div>
          <Card className="overflow-hidden">
            <CardHeader title="Hostnames from certificate transparency" sub={`${subs.length} hosts · screenshots on first sight and on change`} />
            {groups.map(([g, list]) => (
              <div key={g}>
                <div className="border-y border-line bg-sunken/60 px-6 py-2 text-[11px] uppercase tracking-[.1em] text-ink-3">{g} · {list.length}</div>
                <div className="divide-y divide-line">
                  {list.map((s) => (
                    <div key={s.id} className="flex items-center gap-4 px-6 py-3">
                      {s.value.screenshot ? <Thumb name={s.value.screenshot} className="h-10 w-16 shrink-0" /> : <div className="grid h-10 w-16 shrink-0 place-items-center rounded-lg bg-sunken text-ink-3">{s.value.private || s.value.internal ? <Lock size={13} /> : null}</div>}
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13.5px] text-ink">{s.key}</div>
                        <div className="truncate text-[12px] text-ink-3">{[s.value.hosting, s.value.title, s.value.note].filter(Boolean).join(" · ")}</div>
                      </div>
                      <span className="hidden shrink-0 text-[11.5px] text-ink-3 sm:block">{s.value.first_cert ? `cert ${s.value.first_cert}` : `seen ${day(s.first_seen)}`}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {!subs.length && <Empty title="No hostnames yet">Run certificate transparency.</Empty>}
          </Card>
        </div>
      )}
    </div>
  );
}

/* ── Launch radar ───────────────────────────────────────────────────────────── */
export function RadarPage() {
  const { data } = useApi<{ competitors: any[] }>("/api/radar");
  return (
    <div>
      <PageHeader eyebrow="Module 5" title="Launch radar" sub="Weak signals combined into one probability: new campaign subdomains, pages on staging, new repos, first-of-their-kind hires, new verifications and conversion events — decayed over time. Inferred, never certain." />
      {!data ? <Skeleton className="h-96 rounded-2xl" /> : (
        <div className="space-y-5">{data.competitors.map((r) => <RadarCard key={r.id} r={r} />)}</div>
      )}
    </div>
  );
}

function RadarCard({ r }: { r: any }) {
  const e = useEntity(r.id)!;
  const l: Launch = r.launch;
  const p = l.probability || 0;
  return (
    <Card className="overflow-hidden">
      <div className="grid gap-6 p-6 lg:grid-cols-[220px_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2.5"><Monogram id={r.id} size={26} /><span className="text-[14px] text-ink">{e.name}</span></div>
          <div className="mt-5 text-[44px] leading-none tracking-[-0.04em] tnum text-ink">{Math.round(p * 100)}<span className="text-[20px] text-ink-3">%</span></div>
          <div className="mt-2 text-[12.5px] text-ink-3">launch probability{p >= 0.3 ? ` · within ${l.horizon}` : ""}</div>
          <div className="mt-4 h-1 rounded-full bg-sunken"><div className="h-1 rounded-full bg-ink" style={{ width: `${Math.max(2, p * 100)}%` }} /></div>
        </div>
        <div>
          <div className="eyebrow mb-3">Contributing signals</div>
          {l.signals?.length ? l.signals.slice(0, 6).map((s, i) => (
            <div key={i} className="flex items-start gap-3 py-1.5 text-[12.5px]">
              <span className="w-10 shrink-0 text-ink-3 tnum">+{Math.round(s.weight * 100)}</span>
              <span className="min-w-0 text-ink-2"><span className="text-ink">{s.signal}</span> · {s.title}</span>
            </div>
          )) : <div className="text-[12.5px] text-ink-3">No launch signals in the last 45 days.</div>}
        </div>
        <div className="space-y-4 text-[12.5px]">
          <div><div className="eyebrow mb-2">Staging</div>
            {r.staging.length ? r.staging.map((s: any) => <div key={s.host} className="text-ink-2">{s.host}<span className="text-ink-3">{s.crawl ? " · robots.txt disallows crawling — existence only" : ""}</span></div>) : <div className="text-ink-3">None found</div>}
            {r.staging_pages.length > 0 && <div className="mt-1 text-ink">{r.staging_pages.length} pre-launch pages: {r.staging_pages.slice(0, 4).map((p: any) => p.path).join(", ")}</div>}
          </div>
          <div><div className="eyebrow mb-2">Campaign subdomains</div>
            <div className="text-ink-2">{[...new Set(r.campaign_subdomains.map((s: any) => s.host.split(".")[0]))].slice(0, 8).join(", ") || "—"}</div></div>
          <div><div className="eyebrow mb-2">Release cadence</div>
            <div className="text-ink-2">{r.publishes.length ? `${r.publishes.length} publish${r.publishes.length === 1 ? "" : "es"} recorded · last ${r.publishes[r.publishes.length - 1].replace("T", " ")}` : "Not yet observed"}</div></div>
          {r.repos.length > 0 && <div><div className="eyebrow mb-2">Repos</div><div className="text-ink-2">{r.repos.slice(0, 4).map((x: any) => x.name.split("/")[1]).join(", ")}</div></div>}
        </div>
      </div>
    </Card>
  );
}

/* ── Hiring ─────────────────────────────────────────────────────────────────── */
const FN_ORDER = ["Sales", "Sales engineering", "Marketing", "Partnerships", "DevRel", "Customer success", "Engineering", "ML / Research", "Security", "Product & design", "G&A", "Other"];
const FN_COLORS: Record<string, string> = { "Sales": "#2a78d6", "Sales engineering": "#eb6834", "Marketing": "#1baf7a", "Partnerships": "#eda100", "DevRel": "#e87ba4", "Engineering": "#008300", "ML / Research": "#6250d6" };

export function HiringPage() {
  const meta = useMeta();
  const { data } = useApi<any>("/api/hiring");
  const [sel, setSel] = useState<string | null>(null);
  const rows = data?.competitors ?? [];
  const cur = rows.find((r: any) => r.id === (sel ?? rows.find((x: any) => x.open)?.id ?? rows[0]?.id));
  const fnSeries = Object.keys(FN_COLORS).map((f) => ({ id: f, name: f, color: FN_COLORS[f], is_brand: false } as any));
  return (
    <div>
      <PageHeader eyebrow="Module 6" title="Hiring" sub="Public Greenhouse, Lever and Ashby boards. Every role tagged by function, seniority and region, with the tech stack pulled from descriptions. Firsts — first partner manager, first EMEA role — are the strategic tells." />
      {!data ? <Skeleton className="h-96 rounded-2xl" /> : (
        <div className="space-y-5">
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-[12.5px]">
              <thead><tr className="border-b border-line text-left text-ink-3"><th className="px-6 py-3">Competitor</th><th className="px-3 py-3 text-right">Open</th>
                {FN_ORDER.slice(0, 8).map((f) => <th key={f} className="px-3 py-3 text-right">{f}</th>)}</tr></thead>
              <tbody>
                {rows.map((r: any) => (
                  <tr key={r.id} onClick={() => setSel(r.id)} className={cx("cursor-pointer border-b border-line last:border-0 hover:bg-hover/60", cur?.id === r.id && "bg-hover/60")}>
                    <td className="px-6 py-3"><span className="inline-flex items-center gap-2 text-ink"><EntityDot color={meta.entities.find((e) => e.id === r.id)?.color ?? "#999"} size={7} />{meta.entities.find((e) => e.id === r.id)?.name}</span>
                      {!r.boards.length && <span className="ml-2 text-ink-3">no public board</span>}</td>
                    <td className="px-3 py-3 text-right text-ink tnum">{r.open || "—"}</td>
                    {FN_ORDER.slice(0, 8).map((f) => <td key={f} className="px-3 py-3 text-right tnum text-ink-2">{r.functions[f] || ""}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          {cur && (
            <div className="grid gap-5 xl:grid-cols-3">
              <Card className="xl:col-span-2">
                <CardHeader title={`Roles posted per month · ${meta.entities.find((e) => e.id === cur.id)?.name}`} sub="By first-published date, from the job-board APIs" />
                <div className="px-6 pb-6">
                  {cur.posted.length > 1 ? <LineChart data={cur.posted.map((p: any) => ({ date: p.month, ...p }))} series={fnSeries.filter((s) => cur.posted.some((p: any) => p[s.id]))} fmtX={(d) => d} fmtY={(v) => String(Math.round(v))} height={220} />
                    : <div className="grid h-[220px] place-items-center text-[13px] text-ink-3">Trend appears as postings accumulate.</div>}
                </div>
              </Card>
              <Card>
                <CardHeader title="Mix" />
                <div className="space-y-6 px-6 pb-6">
                  <BarList fmt={(v) => String(v)} rows={Object.entries(cur.regions).map(([k, v]) => ({ id: k, label: k, value: v as number, color: "var(--ink)" }))} />
                  <BarList fmt={(v) => String(v)} rows={Object.entries(cur.seniority).map(([k, v]) => ({ id: k, label: k, value: v as number, color: "var(--ink-3)" }))} />
                  {cur.tech.length > 0 && <div className="flex flex-wrap gap-1.5">{cur.tech.map(([t, n]: [string, number]) => <span key={t} className="rounded-full bg-sunken px-2.5 py-0.5 text-[11.5px] text-ink-2">{t} <span className="text-ink-3">{n}</span></span>)}</div>}
                </div>
              </Card>
              <Card className="overflow-hidden xl:col-span-3">
                <CardHeader title="Open roles" sub={cur.boards.join(" · ")} />
                <div className="divide-y divide-line border-t border-line">
                  {cur.jobs.map((j: any) => (
                    <a key={j.url} href={j.url} target="_blank" rel="noreferrer" className="grid grid-cols-[1fr_auto] gap-4 px-6 py-3 hover:bg-hover/60 md:grid-cols-[1.4fr_.8fr_.7fr_.8fr_auto]">
                      <span className="truncate text-[13.5px] text-ink">{j.title}</span>
                      <span className="hidden text-[12.5px] text-ink-2 md:block">{j.function}</span>
                      <span className="hidden text-[12.5px] text-ink-3 md:block">{j.seniority}</span>
                      <span className="hidden truncate text-[12.5px] text-ink-3 md:block">{j.location || j.region}</span>
                      <span className="text-[11.5px] text-ink-3">{j.posted ? day(j.posted) : ""}</span>
                    </a>
                  ))}
                  {!cur.jobs.length && <Empty title="No open roles found">If they use an ATS we didn't detect, set <code>ats:</code> in watchlist.yaml.</Empty>}
                </div>
              </Card>
            </div>
          )}
          {data.firsts.length > 0 && (
            <Card className="overflow-hidden">
              <CardHeader title="Firsts" sub="First-of-their-kind roles" />
              <div className="divide-y divide-line border-t border-line">{data.firsts.map((f: any) => <div key={f.id} className="flex justify-between gap-4 px-6 py-3 text-[13px]"><span className="text-ink">{f.title}</span><span className="text-ink-3">{ago(f.detected_at)}</span></div>)}</div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Partners & money ───────────────────────────────────────────────────────── */
export function MoneyPage() {
  const meta = useMeta();
  const cs = comps(meta);
  return (
    <div>
      <PageHeader eyebrow="Modules 7 & 8" title="Partners, money & ads" sub="Funding rounds, investors and growth claims from coverage; partner programmes and marketplace listings over time; ad channels cross-checked against detected pixels." />
      <div className="space-y-5">{cs.map((c) => <MoneyCard key={c.id} id={c.id} />)}</div>
    </div>
  );
}

function MoneyCard({ id }: { id: string }) {
  const e = useEntity(id)!;
  const { data } = useApi<Fact[]>(`/api/facts?competitor=${id}&module=money`);
  const { data: ads } = useApi<Fact[]>(`/api/facts?competitor=${id}&module=ads`);
  if (!data) return <Skeleton className="h-40 rounded-2xl" />;
  const k = (kind: string) => data.filter((f) => f.kind === kind);
  const funding = k("funding").sort((a, b) => (b.value.date ?? "").localeCompare(a.value.date ?? ""));
  return (
    <Card className="p-6">
      <div className="mb-5 flex items-center gap-2.5"><Monogram id={id} size={26} /><span className="text-[15px] text-ink">{e.name}</span>
        <Link to={`/competitors/${id}`} className="ml-auto text-[12.5px] text-ink-3 hover:text-ink">All facts</Link></div>
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <div><div className="eyebrow mb-2">Funding</div>
          {funding.length ? funding.slice(0, 4).map((f) => <div key={f.id} className="mb-2"><div className="text-[14px] text-ink">{f.label}</div><div className="text-[12px] text-ink-3">{f.value.date?.slice(0, 10)}{f.value.investors?.length ? ` · ${f.value.investors.join(", ")}` : ""} · <Confidence c={f.confidence} /></div></div>) : <div className="text-[12.5px] text-ink-3">None found in coverage</div>}
          {k("arr_claim").map((a) => <div key={a.id} className="mt-2 text-[12.5px] text-ink-2">{a.label}</div>)}
        </div>
        <div><div className="eyebrow mb-2">Partner programme</div>
          <div className="text-[13px] text-ink-2">{k("partner_program").map((p) => p.label).join(" · ") || "—"}</div>
          {k("partner").length > 0 && <div className="mt-2 text-[12.5px] text-ink-3">{k("partner").length} partners: {k("partner").slice(0, 8).map((p) => p.label).join(", ")}</div>}
        </div>
        <div><div className="eyebrow mb-2">Marketplaces</div>
          {k("marketplace").length ? k("marketplace").map((m) => <a key={m.id} href={m.value.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[13px] text-ink-2 hover:text-ink">{m.label}<ExternalLink size={10} /></a>) : <div className="text-[12.5px] text-ink-3">None linked</div>}
        </div>
        <div><div className="eyebrow mb-2">Ad channels</div>
          {(ads ?? []).filter((a) => a.kind === "ad_channel").map((a) => (
            <div key={a.id} className="mb-2"><div className="text-[13px] text-ink">{a.label} <span className="text-ink-3">· {a.value.status}</span></div>
              {a.value.verify_url && <a href={a.value.verify_url} target="_blank" rel="noreferrer" className="text-[12px] text-ink-3 hover:text-ink">Verify in ad library →</a>}</div>
          ))}
          {!(ads ?? []).some((a) => a.kind === "ad_channel") && <div className="text-[12.5px] text-ink-3">No ad pixels detected</div>}
        </div>
      </div>
      {k("press").length > 0 && (
        <div className="mt-6 border-t border-line pt-4">
          <div className="eyebrow mb-2">Latest coverage</div>
          {k("press").sort((a, b) => (b.value.published ?? "").localeCompare(a.value.published ?? "")).slice(0, 4).map((p) => (
            <a key={p.id} href={p.key} target="_blank" rel="noreferrer" className="flex justify-between gap-4 py-1 text-[12.5px] hover:text-ink"><span className="truncate text-ink-2">{p.label}</span><span className="shrink-0 text-ink-3">{p.value.published?.slice(0, 10)}</span></a>
          ))}
        </div>
      )}
    </Card>
  );
}

/* ── Positioning & content ──────────────────────────────────────────────────── */
export function PositioningPage() {
  const meta = useMeta();
  const series = useSeries();
  const { data } = useApi<{ competitors: any[] }>("/api/positioning");
  const { data: posts } = useApi<any[]>("/api/posts?days=90");
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      <PageHeader eyebrow="Module 9" title="Positioning & content" sub="Who they sell to (the buyer hierarchy), which industries and use cases they lead with, and how their content engine is running — tracked from copy and feeds over time." />
      {!data ? <Skeleton className="h-96 rounded-2xl" /> : (
        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.competitors.map((r) => {
              const e = meta.entities.find((x) => x.id === r.id)!;
              const pers = Object.entries(r.personas) as [string, number][];
              return (
                <Card key={r.id} className="p-6">
                  <div className="flex items-center gap-2.5"><Monogram id={r.id} size={26} /><span className="text-[14px] text-ink">{e.name}</span></div>
                  {r.hero && <div className="mt-4 text-[16px] leading-snug tracking-[-0.01em] text-ink">“{r.hero}”</div>}
                  <div className="eyebrow mb-2 mt-5">Buyer hierarchy</div>
                  {pers.length ? <ol className="space-y-1">{pers.slice(0, 4).map(([k, v], i) => <li key={k} className="flex justify-between text-[12.5px]"><span className="text-ink-2"><span className="mr-2 text-ink-3 tnum">{i + 1}</span>{k}</span><span className="text-ink-3 tnum">{v}</span></li>)}</ol> : <div className="text-[12.5px] text-ink-3">—</div>}
                  <div className="eyebrow mb-2 mt-5">Leads with</div>
                  <div className="flex flex-wrap gap-1.5">{Object.keys(r.use_cases).slice(0, 5).map((u) => <span key={u} className="rounded-full bg-sunken px-2.5 py-0.5 text-[11.5px] text-ink-2">{u}</span>)}</div>
                  {Object.keys(r.industries).length > 0 && <div className="mt-3 text-[12px] text-ink-3">Industries: {Object.keys(r.industries).slice(0, 4).join(", ")}</div>}
                  <div className="eyebrow mb-2 mt-5">Content, last 12 months</div>
                  <div className="text-[12.5px] text-ink-2">{r.cadence.length ? r.cadence.reduce((a: number, m: any) => a + Object.entries(m).filter(([k]) => k !== "month").reduce((x, [, v]) => x + (v as number), 0), 0) + " pieces · " + topTypes(r.cadence) : "—"}</div>
                </Card>
              );
            })}
          </div>
          <Card className="overflow-hidden">
            <CardHeader title="Content feed" sub="Last 90 days" />
            <div className="divide-y divide-line border-t border-line">
              {(posts ?? []).slice(0, 40).map((p) => (
                <a key={p.id} href={p.url} target="_blank" rel="noreferrer" onMouseEnter={() => setOpen(p.id)} className="grid grid-cols-[auto_1fr_auto] items-center gap-4 px-6 py-3 hover:bg-hover/60">
                  <EntityDot color={series.find((s) => s.id === p.competitor)?.color ?? "#999"} size={7} />
                  <span className={cx("truncate text-[13.5px]", open === p.id ? "text-ink" : "text-ink")}>{p.title}</span>
                  <span className="text-[11.5px] text-ink-3">{p.ctype ?? "Blog"} · {day(p.published || p.first_seen)}</span>
                </a>
              ))}
              {!(posts ?? []).length && <Empty title="No posts in the last 90 days" />}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

function topTypes(cad: any[]): string {
  const t: Record<string, number> = {};
  for (const m of cad) for (const [k, v] of Object.entries(m)) if (k !== "month") t[k] = (t[k] ?? 0) + (v as number);
  return Object.entries(t).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${k} ${v}`).join(", ");
}

export { pct };
