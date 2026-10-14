import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import { AlertCircle, ArrowUpRight, Bot, CheckCircle2, Copy, Download, ExternalLink, FileText, Globe, Newspaper, Rss } from "lucide-react";
import { api, useApi } from "../lib/api";
import type { Change, Entity, Overview, Post, Share } from "../lib/types";
import { ago, day, host, path, pct } from "../lib/format";
import { LineChart, Sparkline } from "../components/charts";
import { ChangeDrawer, ChangeRow } from "../components/change";
import { Button, Card, CardHeader, cx, Drawer, Empty, fade, Monogram, PageHeader, Skeleton, useEntity, useMeta } from "../components/ui";
import { useToast } from "../components/shell";

export function CompetitorList() {
  const { data } = useApi<Overview>("/api/overview?days=30");
  const meta = useMeta();
  const tiers: Record<string, string> = { primary: "Primary", secondary: "Secondary", platform: "Cloud platform" };
  return (
    <div>
      <PageHeader title="Competitors" sub="Everyone on your watchlist, ranked by how much they've moved in the last 30 days." />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {(data?.competitors ?? meta.entities.filter((e) => !e.is_brand).map((e) => ({ ...e, changes: 0, posts: 0, critical: 0, heat: 0, latest: null, ai_share: null, last_checked: null, heat_delta: 0 }))).map((c, i) => {
          const e = meta.entities.find((x) => x.id === c.id)!;
          return (
            <motion.div key={c.id} {...fade} transition={{ ...fade.transition, delay: i * 0.04 }}>
              <Link to={`/competitors/${c.id}`} className="group block h-full">
                <Card className="relative h-full overflow-hidden p-5 transition-all group-hover:-translate-y-0.5 group-hover:ring-1 group-hover:ring-line-strong">
                  <div className="pointer-events-none absolute -right-16 -top-16 size-40 rounded-full opacity-[0.10] blur-2xl" style={{ background: c.color }} />
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <Monogram id={c.id} size={38} />
                      <div>
                        <div className="text-[15px] font-semibold text-ink">{c.name}</div>
                        <div className="text-[12px] text-ink-3">{tiers[c.tier] ?? c.tier} · {e.domains[0]}</div>
                      </div>
                    </div>
                    <ArrowUpRight size={16} className="text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                  <div className="mt-5 grid grid-cols-3 gap-2">
                    <Stat label="Signals" value={c.changes} hot={c.critical > 0} />
                    <Stat label="Posts" value={c.posts} />
                    <Stat label="AI share" value={pct(c.ai_share)} />
                  </div>
                  {data && <div className="mt-4"><Sparkline values={data.timeline.slice(-30).map((d) => Number(d[c.id]) || 0)} color={c.color} width={300} height={26} /></div>}
                  <div className="mt-4 border-t border-line pt-3 text-[12.5px]">
                    {c.latest ? (
                      <div className="line-clamp-1 text-ink-2"><span className="text-ink-3">Latest · </span>{c.latest.headline}</div>
                    ) : <div className="text-ink-3">No changes in the last 30 days</div>}
                  </div>
                </Card>
              </Link>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value, hot }: { label: string; value: React.ReactNode; hot?: boolean }) {
  return (
    <div className="rounded-lg bg-sunken px-3 py-2 ring-1 ring-inset ring-line">
      <div className="text-[10.5px] text-ink-3">{label}</div>
      <div className={cx("text-[16px] font-semibold tnum", hot ? "text-high" : "text-ink")}>{value}</div>
    </div>
  );
}

interface CompetitorDetail extends Entity {
  pages_status: { kind: string; url: string; changes: number; latest: { fetched_at: string; status: number; title: string; meta: string; signals: any; error: string | null } | null }[];
  changes: Change[]; posts: Post[]; ai: Share | null; ai_trend: { date: string; share: number | null }[];
}

export function CompetitorDetailPage() {
  const { id = "" } = useParams();
  const { data } = useApi<CompetitorDetail>(`/api/competitors/${id}`);
  const e = useEntity(id);
  const meta = useMeta();
  const [open, setOpen] = useState<number | null>(null);
  const [sp, setSp] = useSearchParams();
  const bc = sp.get("battlecard") === "1";

  if (!e) return <Empty title="Competitor not found" />;
  return (
    <div>
      <motion.div {...fade} className="relative mb-6 overflow-hidden rounded-2xl border border-line bg-elev p-6">
        <div className="pointer-events-none absolute inset-0 opacity-[0.16]" style={{ background: `radial-gradient(600px 220px at 0% 0%, ${e.color}, transparent 70%)` }} />
        <div className="relative flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Monogram id={id} size={52} />
            <div>
              <div className="eyebrow mb-1"><Link to="/competitors" className="hover:text-ink">Competitors</Link> / {e.tier}</div>
              <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em] text-ink">{e.name}</h1>
              <div className="mt-1 flex flex-wrap gap-3 text-[12.5px] text-ink-3">
                {e.domains.map((d) => <a key={d} href={`https://${d}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-ink"><Globe size={12} />{d}</a>)}
                <span>{e.pages.length} pages · {e.feeds.length} feeds</span>
              </div>
            </div>
          </div>
          <Button variant="primary" onClick={() => setSp({ battlecard: "1" })}><FileText size={14} />Live battlecard</Button>
        </div>
      </motion.div>

      {!data ? <Skeleton className="h-96 rounded-[14px]" /> : (
        <div className="grid gap-4 xl:grid-cols-3">
          <div className="space-y-4 xl:col-span-2">
            <Card>
              <CardHeader title="Live positioning" sub="What each monitored page says right now: hero, CTAs, prices, and message emphasis." />
              <div className="divide-y divide-line border-t border-line">
                {data.pages_status.map((p) => <PagePanel key={p.url} p={p} terms={meta.watch_terms} color={e.color} />)}
              </div>
            </Card>
            <Card className="overflow-hidden">
              <CardHeader title="Change history" sub={`${data.changes.length} signals recorded`} />
              {data.changes.length ? (
                <div className="divide-y divide-line border-t border-line">{data.changes.map((c) => <ChangeRow key={c.id} c={c} onOpen={setOpen} />)}</div>
              ) : <Empty title="No changes yet">The first scan sets a baseline. Changes appear here from the next scan.</Empty>}
            </Card>
          </div>
          <div className="space-y-4">
            <Card>
              <CardHeader title="AI search presence" sub="Share of tracked answers mentioning them" />
              <div className="px-5 pb-5">
                {data.ai ? (
                  <>
                    <div className="flex items-end gap-6">
                      <div><div className="text-[30px] font-semibold leading-none tnum text-ink">{pct(data.ai.share)}</div><div className="mt-1 text-[11.5px] text-ink-3">of answers</div></div>
                      <div><div className="text-[18px] font-semibold leading-none tnum text-ink">{data.ai.avg_rank ? `#${data.ai.avg_rank.toFixed(1)}` : "—"}</div><div className="mt-1 text-[11.5px] text-ink-3">avg. position</div></div>
                      <div><div className="text-[18px] font-semibold leading-none tnum text-ink">{data.ai.cited}</div><div className="mt-1 text-[11.5px] text-ink-3">citations</div></div>
                    </div>
                    {data.ai_trend.length > 1 && (
                      <div className="mt-4">
                        <LineChart height={140} series={[e]} fmtX={day} data={data.ai_trend.map((t) => ({ date: t.date, [e.id]: t.share ?? 0 }))} />
                      </div>
                    )}
                  </>
                ) : <Empty icon={<Bot size={18} />} title="No AI runs yet" />}
              </div>
            </Card>
            <Card className="overflow-hidden">
              <CardHeader title="Content" sub={`${data.posts.length} posts tracked`} right={<Rss size={14} className="text-ink-3" />} />
              <div className="max-h-[520px] divide-y divide-line overflow-y-auto border-t border-line">
                {data.posts.length ? data.posts.slice(0, 40).map((p) => (
                  <a key={p.id} href={p.url} target="_blank" rel="noreferrer" className="block px-5 py-3 hover:bg-hover/60">
                    <div className="text-[13px] font-medium leading-snug text-ink">{p.title}</div>
                    <div className="mt-0.5 text-[11.5px] text-ink-3">{p.published ? day(p.published) : `seen ${ago(p.first_seen)}`}</div>
                  </a>
                )) : <Empty icon={<Newspaper size={18} />} title="No posts yet" />}
              </div>
            </Card>
          </div>
        </div>
      )}
      <ChangeDrawer id={open} onClose={() => setOpen(null)} />
      <Battlecard id={id} open={bc} onClose={() => setSp({})} />
    </div>
  );
}

function PagePanel({ p, terms, color }: { p: CompetitorDetail["pages_status"][number]; terms: string[]; color: string }) {
  const s = p.latest, sig = s?.signals ?? {};
  const termRows = terms.map((t) => [t, sig.terms?.[t] ?? 0] as const).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const tmax = Math.max(1, ...termRows.map(([, v]) => v));
  return (
    <div className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[10.5px] font-medium uppercase tracking-wide text-ink-3 ring-1 ring-inset ring-line">{p.kind}</span>
          <a href={p.url} target="_blank" rel="noreferrer" className="truncate text-[12.5px] text-ink-2 hover:text-ink">{host(p.url)}{path(p.url)}</a>
          <ExternalLink size={11} className="text-ink-3 shrink-0" />
        </div>
        <div className="flex items-center gap-1.5 text-[11.5px] text-ink-3">
          {s?.error ? <><AlertCircle size={12} className="text-crit" />{s.error}</> : s ? <><CheckCircle2 size={12} className="text-good" />checked {ago(s.fetched_at)}</> : "not yet checked"}
          {p.changes > 0 && <span className="ml-2 rounded-full bg-accent-soft px-2 py-0.5 text-accent-ink">{p.changes} changes</span>}
        </div>
      </div>
      {s && !s.error && (
        <div className="mt-3 grid gap-4 md:grid-cols-[1fr_200px]">
          <div className="min-w-0">
            {sig.h1?.[0] && <div className="text-[17px] font-semibold leading-snug tracking-[-0.01em] text-ink">“{sig.h1[0]}”</div>}
            {s.meta && <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{s.meta}</p>}
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(sig.ctas ?? []).slice(0, 4).map((c: string) => <span key={c} className="rounded-md px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset" style={{ color, boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${color} 35%, transparent)` }}>{c}</span>)}
              {(sig.prices ?? []).slice(0, 6).map((pr: string) => <span key={pr} className="rounded-md bg-sunken px-2 py-0.5 font-mono text-[11px] text-ink ring-1 ring-inset ring-line">{pr}</span>)}
            </div>
          </div>
          {termRows.length > 0 && (
            <div>
              <div className="eyebrow mb-2">Message emphasis</div>
              <div className="space-y-1.5">
                {termRows.map(([t, v]) => (
                  <div key={t} className="flex items-center gap-2 text-[11.5px]">
                    <span className="w-24 truncate text-ink-2">{t}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-sunken"><div className="h-full rounded-full" style={{ width: `${(v / tmax) * 100}%`, background: color }} /></div>
                    <span className="w-5 text-right tnum text-ink-3">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Battlecard({ id, open, onClose }: { id: string; open: boolean; onClose: () => void }) {
  const [md, setMd] = useState<string>("");
  const toast = useToast();
  const e = useEntity(id);
  useEffect(() => { if (open) api<string>(`/api/battlecard/${id}`).then(setMd).catch(() => setMd("")); }, [open, id]);
  const copy = async () => { try { await navigator.clipboard.writeText(md); toast({ title: "Battlecard copied", body: "Markdown is on your clipboard." }); } catch { toast({ title: "Copy failed", tone: "err" }); } };
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    a.download = `${id}-battlecard.md`; a.click();
  };
  return (
    <Drawer open={open} onClose={onClose} width={680}>
      <div className="border-b border-line p-7 pr-14 glow">
        <div className="eyebrow mb-1">Live battlecard</div>
        <h2 className="text-[22px] font-semibold tracking-[-0.015em] text-ink">{e?.name}</h2>
        <p className="mt-1 text-[13px] text-ink-2">Regenerated from the latest snapshots on every scan, so it never goes stale. Paste it into your battlecard doc.</p>
        <div className="mt-4 flex gap-2">
          <Button variant="primary" size="sm" onClick={copy}><Copy size={13} />Copy markdown</Button>
          <Button variant="outline" size="sm" onClick={download}><Download size={13} />Download .md</Button>
        </div>
      </div>
      <div className="p-7">
        {md ? <MarkdownLite md={md} /> : <Skeleton className="h-64" />}
      </div>
    </Drawer>
  );
}

/** Tiny renderer for the battlecard's own, known markdown subset. */
function MarkdownLite({ md }: { md: string }) {
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|_[^_]+_)/g).map((t, i) => {
    if (t.startsWith("**")) return <strong key={i} className="font-semibold text-ink">{t.slice(2, -2)}</strong>;
    const m = t.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (m) return <a key={i} href={m[2]} target="_blank" rel="noreferrer" className="text-accent-ink hover:underline">{m[1]}</a>;
    if (/^_.+_$/.test(t)) return <em key={i} className="text-ink-3 not-italic">{t.slice(1, -1)}</em>;
    return t;
  });
  return (
    <div className="space-y-1.5 text-[13.5px] leading-relaxed text-ink-2">
      {md.split("\n").map((l, i) => {
        if (l.startsWith("# ")) return null;
        if (l.startsWith("## ")) return <h3 key={i} className="pt-4 text-[14px] font-semibold text-ink first:pt-0">{inline(l.slice(3))}</h3>;
        if (l.startsWith("- ")) return <div key={i} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-ink-3" /><span>{inline(l.slice(2))}</span></div>;
        if (!l.trim()) return null;
        return <p key={i}>{inline(l)}</p>;
      })}
    </div>
  );
}
