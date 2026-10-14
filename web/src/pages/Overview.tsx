import { useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { Activity, ArrowRight, Bot, DollarSign, Flame, Newspaper, Radar } from "lucide-react";
import { useApi } from "../lib/api";
import type { Overview as OV } from "../lib/types";
import { ago, day, greeting, pct } from "../lib/format";
import { BarList, Ring, Sparkline, StackedBars } from "../components/charts";
import { ChangeDrawer, ChangeRow } from "../components/change";
import { Card, CardHeader, cx, Delta, Empty, fade, Monogram, PageHeader, Segmented, Skeleton, useMeta, useSeries } from "../components/ui";
import { useJobs } from "../components/shell";

export default function Overview() {
  const [days, setDays] = useState(7);
  const { data } = useApi<OV>(`/api/overview?days=${days}`);
  const meta = useMeta();
  const series = useSeries().filter((s) => !s.is_brand);
  const [open, setOpen] = useState<number | null>(null);
  const { start } = useJobs();

  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  const headline = data
    ? data.kpis.critical
      ? `${data.kpis.critical} high-impact move${data.kpis.critical > 1 ? "s" : ""} in the last ${days} days`
      : data.kpis.changes ? "Steady week — nothing high-impact" : "All quiet on the competitive front"
    : "Loading…";

  return (
    <div>
      <PageHeader eyebrow={today} title={<>{greeting()}. <span className="text-ink-3">{headline}.</span></>}
        right={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: "7d" }, { value: 30, label: "30d" }, { value: 90, label: "90d" }]} />} />

      {!data ? <OverviewSkeleton /> : (
        <div className="space-y-4">
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi i={0} icon={<Activity size={14} />} label="Signals detected" value={data.kpis.changes}
              foot={<><Delta value={data.kpis.changes - data.kpis.changes_prev} neutral /> <span className="text-ink-3">vs prior {days}d</span></>} />
            <Kpi i={1} icon={<Flame size={14} />} label="High-impact" value={data.kpis.critical} tone={data.kpis.critical ? "crit" : undefined}
              foot={<span className="inline-flex items-center gap-1 text-ink-3"><DollarSign size={12} />{data.kpis.pricing} pricing move{data.kpis.pricing === 1 ? "" : "s"}</span>} />
            <Kpi i={2} icon={<Newspaper size={14} />} label="New content" value={data.kpis.posts}
              foot={<span className="text-ink-3">across {data.kpis.feeds} feeds</span>} />
            <motion.div {...fade} transition={{ ...fade.transition, delay: 0.15 }}>
              <Card glow className="h-full p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-1.5 text-[12px] text-ink-3"><Bot size={14} />AI share of voice</div>
                    <div className="mt-2 text-[28px] font-semibold leading-none tracking-[-0.02em] tnum text-ink">{pct(data.kpis.ai_share)}</div>
                  </div>
                  {data.kpis.ai_share != null && <div className="relative"><Ring value={data.kpis.ai_share} /><span className="absolute inset-0 grid place-items-center"><Radar size={16} className="text-accent-ink" /></span></div>}
                </div>
                <div className="mt-3 flex items-center gap-2 text-[12px]">
                  {data.kpis.ai_share != null && data.kpis.ai_share_prev != null
                    ? <><Delta value={Math.round((data.kpis.ai_share - data.kpis.ai_share_prev) * 100)} suffix=" pts" /><span className="text-ink-3">· {data.kpis.ai_gaps} gaps</span></>
                    : <Link to="/ai" className="text-accent-ink hover:underline">Set up AI tracking →</Link>}
                </div>
              </Card>
            </motion.div>
          </div>

          {/* Activity + threat board */}
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Competitive activity" sub="Weighted by severity: a pricing change outweighs a blog post. Click a legend item to isolate it." />
              <div className="px-5 pb-5">
                <StackedBars data={data.timeline} series={series} fmtDate={day} height={262} />
              </div>
            </Card>
            <Card>
              <CardHeader title="Threat board" sub={`Who's moving most · last ${days}d`} />
              <div className="px-2 pb-2">
                {data.competitors.map((c, i) => {
                  const spark = data.timeline.slice(-14).map((d) => Number(d[c.id]) || 0);
                  return (
                    <Link key={c.id} to={`/competitors/${c.id}`} className="group flex items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-hover">
                      <span className="w-4 text-[11px] text-ink-3 tnum">{i + 1}</span>
                      <Monogram id={c.id} size={28} />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-medium text-ink">{c.name}</div>
                        <div className="text-[11.5px] text-ink-3 tnum">
                          {c.changes} signal{c.changes === 1 ? "" : "s"} · {c.posts} post{c.posts === 1 ? "" : "s"}
                          {c.critical > 0 && <span className="text-high"> · {c.critical} high</span>}
                        </div>
                      </div>
                      <Sparkline values={spark} color={c.color} width={64} height={22} />
                    </Link>
                  );
                })}
              </div>
            </Card>
          </div>

          {/* Signals + AI share */}
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2 overflow-hidden">
              <CardHeader title="Top signals" sub="Highest-severity changes first"
                right={<Link to="/signals" className="inline-flex items-center gap-1 text-[12px] text-ink-3 hover:text-ink">View all <ArrowRight size={12} /></Link>} />
              {data.top_changes.length ? (
                <div className="divide-y divide-line border-t border-line">
                  {[...data.top_changes].sort((a, b) => sevRank(a.severity) - sevRank(b.severity)).slice(0, 6).map((c) => <ChangeRow key={c.id} c={c} onOpen={setOpen} />)}
                </div>
              ) : (
                <Empty icon={<Activity size={18} />} title="No changes detected yet"
                  action={<button onClick={() => start("pages")} className="text-[13px] text-accent-ink hover:underline">Run a page scan →</button>}>
                  The first scan records a baseline; changes show up from the second scan onward.
                </Empty>
              )}
            </Card>
            <Card>
              <CardHeader title="AI search share of voice" sub="Share of answers that mention each vendor"
                right={<Link to="/ai" className="inline-flex items-center gap-1 text-[12px] text-ink-3 hover:text-ink">Details <ArrowRight size={12} /></Link>} />
              <div className="px-5 pb-5">
                {data.share.length ? (
                  <BarList max={1} rows={[...data.share].sort((a, b) => b.share - a.share).map((s) => {
                    const e = meta.entities.find((x) => x.id === s.id)!;
                    return { id: s.id, label: e.is_brand ? `${e.name} (you)` : e.name, value: s.share, color: e.color, strong: e.is_brand,
                      sub: s.avg_rank ? `#${s.avg_rank.toFixed(1)}` : undefined };
                  })} />
                ) : <Empty icon={<Bot size={18} />} title="No AI runs yet">Add a Perplexity or OpenAI key, then run AI visibility.</Empty>}
              </div>
            </Card>
          </div>

          {/* Content */}
          <Card className="overflow-hidden">
            <CardHeader title="Fresh from competitor blogs"
              right={<Link to="/content" className="inline-flex items-center gap-1 text-[12px] text-ink-3 hover:text-ink">All content <ArrowRight size={12} /></Link>} />
            {data.recent_posts.length ? (
              <div className="grid border-t border-line sm:grid-cols-2 xl:grid-cols-4">
                {data.recent_posts.slice(0, 8).map((p, i) => (
                  <a key={p.id} href={p.url} target="_blank" rel="noreferrer"
                    className={cx("group flex flex-col gap-2 p-5 hover:bg-hover/60 border-line", i % 4 !== 3 && "xl:border-r", "border-b")}>
                    <div className="flex items-center gap-2"><Monogram id={p.competitor} size={20} /><span className="text-[11.5px] text-ink-3">{ago(p.published || p.first_seen)}</span></div>
                    <div className="text-[13.5px] font-medium leading-snug text-ink group-hover:text-accent-ink line-clamp-2">{p.title}</div>
                    {p.topics?.length > 0 && <div className="mt-auto flex flex-wrap gap-1">{p.topics.slice(0, 3).map((t) => <span key={t} className="rounded bg-sunken px-1.5 py-0.5 text-[10.5px] text-ink-3 ring-1 ring-inset ring-line">{t}</span>)}</div>}
                  </a>
                ))}
              </div>
            ) : <Empty icon={<Newspaper size={18} />} title="No new posts this period" />}
          </Card>
          {data.last_run && <div className="pt-1 text-center text-[11.5px] text-ink-3">Last collection: {data.last_run.job} · {ago(data.last_run.finished_at)} · <SeverityDot ok={data.last_run.status === "ok"} /></div>}
        </div>
      )}
      <ChangeDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

const sevRank = (s: string) => ["critical", "high", "medium", "low", "noise"].indexOf(s);

function SeverityDot({ ok }: { ok: boolean }) {
  return <span className={ok ? "text-good" : "text-crit"}>{ok ? "healthy" : "error"}</span>;
}

function Kpi({ icon, label, value, foot, tone, i }: { icon: React.ReactNode; label: string; value: number; foot: React.ReactNode; tone?: "crit"; i: number }) {
  return (
    <motion.div {...fade} transition={{ ...fade.transition, delay: i * 0.05 }}>
      <Card className="h-full p-4">
        <div className="flex items-center gap-1.5 text-[12px] text-ink-3">{icon}{label}</div>
        <div className={cx("mt-2 text-[28px] font-semibold leading-none tracking-[-0.02em] tnum", tone === "crit" && value ? "text-crit" : "text-ink")}>{value}</div>
        <div className="mt-3 flex items-center gap-1.5 text-[12px]">{foot}</div>
      </Card>
    </motion.div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[112px] rounded-[14px]" />)}</div>
      <div className="grid gap-4 xl:grid-cols-3"><Skeleton className="h-[300px] rounded-[14px] xl:col-span-2" /><Skeleton className="h-[300px] rounded-[14px]" /></div>
    </div>
  );
}

