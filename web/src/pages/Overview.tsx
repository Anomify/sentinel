import { useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { Activity, ArrowRight } from "lucide-react";
import { useApi } from "../lib/api";
import type { Overview as OV } from "../lib/types";
import { ago, day, greeting, pct } from "../lib/format";
import { BarList, Sparkline, StackedBars } from "../components/charts";
import { EventDrawer, EventRow } from "../components/signal";
import { Card, CardHeader, cx, Delta, Empty, fade, Monogram, PageHeader, Segmented, Skeleton, Stat, useMeta, useSeries } from "../components/ui";
import { useJobs } from "../components/shell";

const SEV_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

export default function Overview() {
  const [days, setDays] = useState(7);
  const { data } = useApi<OV>(`/api/overview?days=${days}`);
  const meta = useMeta();
  const series = useSeries().filter((s) => !s.is_brand);
  const [open, setOpen] = useState<number | null>(null);
  const { start } = useJobs();
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  const lead = data?.competitors[0];
  const top = data ? Object.entries(data.launch).sort((a, b) => b[1].probability - a[1].probability)[0] : null;
  const headline = !data ? "" : data.kpis.critical
    ? `${data.kpis.critical} high-impact move${data.kpis.critical > 1 ? "s" : ""} this ${days === 7 ? "week" : `${days} days`}.`
    : data.kpis.changes ? "Steady — nothing high-impact." : data.kpis.facts ? "Baseline recorded. Watching for changes." : "All quiet.";

  return (
    <div>
      <PageHeader eyebrow={today} title={<>{greeting()}.<br /><span className="text-ink-3">{headline}</span></>}
        right={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: "7 days" }, { value: 30, label: "30 days" }, { value: 90, label: "90 days" }]} />} />
      {!data ? <Skel /> : (
        <div className="space-y-5">
          <motion.div {...fade}>
            <Card className="grid grid-cols-2 divide-line lg:grid-cols-4 lg:divide-x">
              <Stat className="p-6" label="Signals" value={data.kpis.changes} sub={data.kpis.changes || data.kpis.changes_prev
                ? <span className="inline-flex items-center gap-1.5"><Delta value={data.kpis.changes - data.kpis.changes_prev} neutral /> vs prior period</span>
                : `Baseline · ${data.kpis.facts.toLocaleString()} facts on file`} />
              <Stat className="p-6" label="High-impact" value={<span className={data.kpis.critical ? "text-crit" : ""}>{data.kpis.critical}</span>} sub={lead ? `Most active: ${lead.name}` : "—"} />
              <Stat className="p-6" label="Launch risk" value={pct(data.kpis.launch_max)} sub={top && top[1].probability > 0 ? `${meta.entities.find((e) => e.id === top[0])?.name} · ${top[1].horizon}` : "No launch signals"} />
              <Stat className="p-6" label="AI share of voice" value={pct(data.kpis.ai_share)}
                sub={data.kpis.ai_share != null ? <span className="inline-flex items-center gap-1.5">{data.kpis.ai_share_prev != null && <Delta value={Math.round((data.kpis.ai_share - data.kpis.ai_share_prev) * 100)} suffix=" pts" />}{data.kpis.ai_gaps} gaps</span> : <Link to="/ai" className="hover:text-ink">Connect engines →</Link>} />
            </Card>
          </motion.div>

          <div className="grid gap-5 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Competitive activity" sub="Every module, weighted by severity. Click a legend item to isolate it." />
              <div className="px-6 pb-6"><StackedBars data={data.timeline} series={series} fmtDate={day} height={240} /></div>
            </Card>
            <Card>
              <CardHeader title="Who's moving" sub={`Last ${days} days`} />
              <div className="px-3 pb-3">
                {data.competitors.map((c, i) => (
                  <Link key={c.id} to={`/deep-dives/${c.id}`} className="group flex items-center gap-3 rounded-xl px-3 py-2.5 hover:bg-hover">
                    <span className="w-3 text-[11px] text-ink-3 tnum">{i + 1}</span>
                    <Monogram id={c.id} size={28} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13.5px] text-ink">{c.name}</div>
                      <div className="text-[11.5px] text-ink-3 tnum">{c.changes} signals{c.critical ? <span className="text-high"> · {c.critical} high</span> : null}{c.launch >= 0.3 ? ` · launch ${pct(c.launch)}` : ""}</div>
                    </div>
                    <Sparkline values={data.timeline.slice(-14).map((d) => Number(d[c.id]) || 0)} color={c.color} width={56} height={20} />
                  </Link>
                ))}
              </div>
            </Card>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <Card className="overflow-hidden xl:col-span-2">
              <CardHeader title="Top signals" sub="Highest impact first"
                right={<Link to="/signals" className="inline-flex items-center gap-1 text-[12.5px] text-ink-3 hover:text-ink">All signals <ArrowRight size={12} /></Link>} />
              {data.top_events.length ? (
                <div className="divide-y divide-line border-t border-line">
                  {[...data.top_events].sort((a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9)).slice(0, 7).map((e) => <EventRow key={e.id} e={e} onOpen={setOpen} />)}
                </div>
              ) : (
                <Empty icon={<Activity size={16} />} title="No signals yet" action={<button onClick={() => start("subdomains")} className="text-[13px] text-ink underline-offset-4 hover:underline">Run certificate transparency →</button>}>
                  The first run of each module records a baseline. Alerts begin with the second run.
                </Empty>
              )}
            </Card>
            <div className="space-y-5">
              <Card>
                <CardHeader title="Signals by module" />
                <div className="px-6 pb-6">
                  {Object.keys(data.by_module).length ? (
                    <BarList fmt={(v) => String(v)} rows={Object.entries(data.by_module).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ id: k, label: k, value: v, color: "var(--ink)" }))} />
                  ) : <div className="py-6 text-center text-[13px] text-ink-3">—</div>}
                </div>
              </Card>
              <Card>
                <CardHeader title="AI share of voice" right={<Link to="/ai" className="text-[12.5px] text-ink-3 hover:text-ink">Details</Link>} />
                <div className="px-6 pb-6">
                  {data.share.length ? (
                    <BarList max={1} rows={[...data.share].sort((a, b) => b.share - a.share).map((s) => {
                      const e = meta.entities.find((x) => x.id === s.id)!;
                      return { id: s.id, label: e.is_brand ? `${e.name} (you)` : e.name, value: s.share, color: e.color, strong: e.is_brand };
                    })} />
                  ) : <div className="py-4 text-[13px] leading-relaxed text-ink-3">Add a Perplexity, OpenAI, Gemini or SerpAPI key to start tracking your 20 questions.</div>}
                </div>
              </Card>
            </div>
          </div>

          {data.recent_posts.length > 0 && (
            <Card className="overflow-hidden">
              <CardHeader title="Fresh from competitor blogs" right={<Link to="/positioning" className="text-[12.5px] text-ink-3 hover:text-ink">Content engine</Link>} />
              <div className="grid border-t border-line sm:grid-cols-2 xl:grid-cols-4">
                {data.recent_posts.slice(0, 4).map((p, i) => (
                  <a key={p.id} href={p.url} target="_blank" rel="noreferrer" className={cx("group flex flex-col gap-3 p-6 hover:bg-hover/60", i < 3 && "xl:border-r", "border-line")}>
                    <div className="flex items-center gap-2"><Monogram id={p.competitor} size={20} /><span className="text-[11.5px] text-ink-3">{ago(p.published || p.first_seen)}</span></div>
                    <div className="line-clamp-3 text-[14px] leading-snug text-ink">{p.title}</div>
                  </a>
                ))}
              </div>
            </Card>
          )}
          {data.last_run && <div className="pt-2 text-center text-[11.5px] text-ink-3">Last collection · {data.last_run.job} · {ago(data.last_run.finished_at)}</div>}
        </div>
      )}
      <EventDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function Skel() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-[120px] rounded-2xl" />
      <div className="grid gap-5 xl:grid-cols-3"><Skeleton className="h-[340px] rounded-2xl xl:col-span-2" /><Skeleton className="h-[340px] rounded-2xl" /></div>
    </div>
  );
}
