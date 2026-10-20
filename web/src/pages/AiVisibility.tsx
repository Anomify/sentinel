import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import { AlertTriangle, Bot, ExternalLink, Link2, Play, Target, Trophy } from "lucide-react";
import { useApi } from "../lib/api";
import type { AiAnswer, Entity, Visibility } from "../lib/types";
import { day, host, pct } from "../lib/format";
import { BarList, LineChart } from "../components/charts";
import { Button, Card, CardHeader, Chip, cx, Delta, Drawer, Empty, EntityDot, EntityTag, fade, PageHeader, Segmented, Skeleton, useMeta, useSeries } from "../components/ui";
import { useJobs } from "../components/shell";

const ENGINE_LABEL: Record<string, string> = { perplexity: "Perplexity", openai: "ChatGPT", gemini: "Gemini", google_aio: "AI Overviews", claude: "Claude" };

export default function AiVisibility() {
  const meta = useMeta();
  const series = useSeries();
  const [run, setRun] = useState<string | null>(null);
  const { data } = useApi<Visibility>(`/api/visibility${run ? `?run_id=${run}` : ""}`);
  const [engine, setEngine] = useState<string>("all");
  const [sp, setSp] = useSearchParams();
  const qOpen = sp.get("q");
  const [cat, setCat] = useState<string | null>(null);
  const { start, running } = useJobs();
  const brand = meta.entities.find((e) => e.is_brand)!;

  const share = engine === "all" ? data?.share : data?.per_engine?.[engine];
  const brandShare = share?.find((s) => s.id === brand.id);
  const prev = data && data.trend.length > 1 ? Number(data.trend[data.trend.length - 2][brand.id]) : null;
  const leader = share ? [...share].sort((a, b) => b.share - a.share)[0] : null;
  const brandRankAmong = share ? [...share].sort((a, b) => b.share - a.share).findIndex((s) => s.id === brand.id) + 1 : 0;

  if (data && !data.latest) {
    const ready = meta.engines.filter((e) => e.enabled && e.has_key);
    return (
      <div>
        <PageHeader title="AI Visibility" sub="Track whether answer engines recommend you, or your competitors, for the questions buyers actually ask." />
        <Card><Empty icon={<Bot size={18} />} title={ready.length ? "No runs yet" : "Connect an answer engine"}
          action={ready.length ? <Button variant="primary" onClick={() => start("ai")}><Play size={14} />Run {meta.questions.length} questions now</Button> : undefined}>
          {ready.length ? `Ready to ask ${ready.map((e) => ENGINE_LABEL[e.id]).join(" and ")} your ${meta.questions.length} target questions.`
            : "Set PERPLEXITY_API_KEY and/or OPENAI_API_KEY in your environment, then restart Sentinel."}
        </Empty></Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="AI Visibility"
        sub={`How often ${brand.name} shows up when buyers ask AI search your ${meta.questions.length} target questions, and who shows up instead.`}
        right={<>
          {data && data.runs.length > 1 && (
            <select value={run ?? data.latest?.run_id} onChange={(e) => setRun(e.target.value)}
              className="h-8 rounded-lg bg-sunken px-2 text-[12px] text-ink-2 ring-1 ring-inset ring-line outline-none">
              {[...data.runs].reverse().map((r) => <option key={r.run_id} value={r.run_id}>Run of {day(r.run_at)}{r.complete ? "" : " (incomplete)"}</option>)}
            </select>
          )}
          {data && data.engines.length > 1 && <Segmented value={engine} onChange={setEngine} options={[{ value: "all", label: "All engines" }, ...data.engines.map((e) => ({ value: e, label: ENGINE_LABEL[e] ?? e }))]} />}
          <Button variant="outline" onClick={() => start("ai")} disabled={running.includes("ai")}><Play size={13} />Run now</Button>
        </>} />

      {!data || !share ? <Skeleton className="h-96 rounded-[14px]" /> : (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-3">
            <motion.div {...fade}>
              <Card className="h-full p-6">
                <div className="flex items-center gap-1.5 text-[12px] text-ink-3"><Target size={14} />Your share of voice</div>
                <div className="mt-3 flex items-end gap-3">
                  <div className="text-[52px] leading-none tracking-[-0.03em] tnum text-ink">{pct(brandShare?.share)}</div>
                  {prev != null && engine === "all" && !run && <div className="mb-2"><Delta value={Math.round(((brandShare?.share ?? 0) - prev) * 100)} suffix=" pts" /></div>}
                </div>
                <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
                  of AI answers mention {brand.name}{brandShare?.avg_rank ? <>, at average position <b className="text-ink tnum">#{brandShare.avg_rank.toFixed(1)}</b> among tracked vendors</> : null}.
                </p>
                {data.latest && (
                  <p className="mt-1.5 text-[12px] leading-relaxed text-ink-3">
                    Based on {data.latest.measured} answers from one run
                    {data.latest.errors ? `; ${data.latest.errors} requests failed` : ""}
                    {data.latest.no_answer ? `; ${data.latest.no_answer} showed no AI answer` : ""}
                    {data.latest.branded_excluded.length ? `; ${data.latest.branded_excluded.length} questions naming a vendor left out` : ""}.
                    {(data.latest.samples ?? 1) > 1 && data.spread?.[brand.id]
                      ? ` Asked ${data.latest.samples} times each: your share ranged ${pct(data.spread[brand.id].min)}–${pct(data.spread[brand.id].max)}, so smaller moves are noise.`
                      : " One sample per question: a move of a few points can be chance."}
                    {!data.latest.complete && <span className="text-high"> Incomplete run: not comparable with others.</span>}
                  </p>
                )}
                <div className="mt-5 grid grid-cols-3 gap-2 text-center">
                  <MiniStat label="Rank vs field" value={brandRankAmong ? `${brandRankAmong}/${share.length}` : "-"} />
                  <MiniStat label="Top-3 mentions" value={brandShare?.top3 ?? 0} />
                  <MiniStat label="Gaps" value={data.gaps.length} tone={data.gaps.length ? "warn" : undefined} />
                </div>
                {leader && leader.id !== brand.id && (
                  <div className="mt-4 flex items-center gap-2 rounded-lg bg-sunken px-3 py-2 text-[12px] text-ink-2 ring-1 ring-inset ring-line">
                    <Trophy size={13} className="text-med" />Leader: <EntityTag id={leader.id} /> at {pct(leader.share)}
                  </div>
                )}
              </Card>
            </motion.div>
            <Card className="lg:col-span-2">
              <CardHeader title="Share of voice over time" sub={`Your line is emphasized · ${data.trend.length} runs`} />
              <div className="px-5 pb-5">
                {data.trend.length > 1
                  ? <LineChart data={data.trend} series={series} emphasize={brand.id} fmtX={day} height={210} yMax={1} />
                  : <div className="grid h-[210px] place-items-center text-[13px] text-ink-3">The trend appears after your second run.</div>}
              </div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader title="Leaderboard" sub={engine === "all" ? "All engines combined" : ENGINE_LABEL[engine]} />
              <div className="px-5 pb-5">
                <BarList max={1} rows={[...share].sort((a, b) => b.share - a.share).map((s) => {
                  const e = meta.entities.find((x) => x.id === s.id)!;
                  return { id: s.id, label: e.is_brand ? `${e.name} (you)` : e.name, value: s.share, color: e.color, strong: e.is_brand, sub: s.avg_rank ? `avg #${s.avg_rank.toFixed(1)}` : undefined };
                })} />
              </div>
            </Card>
            <Card>
              <CardHeader title="Where you're missing" sub="Competitors are named, you aren't. Your AI-search to-do list." right={<AlertTriangle size={14} className="text-med" />} />
              <div className="max-h-[300px] overflow-y-auto border-t border-line">
                {data.gaps.length ? data.gaps.map((g) => (
                  <button key={g.id} onClick={() => setSp({ q: g.id })} className="block w-full border-b border-line px-5 py-3 text-left last:border-0 hover:bg-hover/60">
                    <div className="text-[13px] leading-snug text-ink">{g.text}</div>
                    <div className="mt-1.5 flex items-center gap-1">
                      {g.competitors.map((c) => <EntityDot key={c} color={meta.entities.find((e) => e.id === c)?.color ?? "#888"} size={8} ring />)}
                      <span className="ml-1 text-[11px] text-ink-3">{g.competitors.length} competitor{g.competitors.length > 1 ? "s" : ""} cited</span>
                    </div>
                  </button>
                )) : <Empty title="No gaps 🎉">You appear wherever a competitor does.</Empty>}
              </div>
            </Card>
            <Card>
              <CardHeader title="Most-cited sources" sub="Domains engines lean on. Earn coverage here." right={<Link2 size={14} className="text-ink-3" />} />
              <div className="px-5 pb-5">
                <BarList fmt={(v) => String(v)} rows={data.citations.slice(0, 8).map((c) => {
                  const own = meta.entities.find((e) => e.domains.some((d) => c.domain.endsWith(d)));
                  return { id: c.domain, label: c.domain, value: c.count, color: own?.color ?? "var(--ink-3)", strong: own?.is_brand };
                })} />
              </div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Source gaps" sub="Domains cited in answers that name a competitor but not you, where to earn coverage next" />
              <div className="px-5 pb-5">
                {data.source_gaps?.length ? <BarList fmt={(v) => String(v)} rows={data.source_gaps.slice(0, 8).map((c) => ({ id: c.domain, label: c.domain, value: c.count, color: "var(--ink)" }))} />
                  : <div className="py-6 text-center text-[13px] text-ink-3">No source gaps in this run.</div>}
              </div>
            </Card>
            <Card>
              <CardHeader title="Narrative accuracy" sub="How correctly answers describe you, graded by AI (Gemini or Claude) against your brand facts" />
              <div className="px-5 pb-5">
                {data.accuracy ? (
                  <>
                    <div className="flex items-end gap-3"><div className="text-[40px] leading-none tracking-[-0.03em] tnum text-ink">{Math.round(data.accuracy.score * 100)}%</div>
                      <div className="mb-1 text-[12.5px] text-ink-3">across {data.accuracy.n} answers that mention you</div></div>
                    <ul className="mt-4 space-y-1.5">{data.accuracy.issues.slice(0, 6).map((i, k) => <li key={k} className="text-[12.5px] leading-relaxed text-ink-2">• {i}</li>)}</ul>
                  </>
                ) : <div className="py-4 text-[13px] leading-relaxed text-ink-3">Add <code className="font-mono text-[12px]">facts:</code> under <code className="font-mono text-[12px]">brand</code> in watchlist.yaml and a GEMINI_API_KEY or ANTHROPIC_API_KEY to grade what AI search says about you.</div>}
              </div>
            </Card>
          </div>

          <Card className="overflow-hidden">
            <CardHeader title="Question matrix" sub="Position each vendor holds in each answer. Click a question to read the answers."
              right={<div className="hidden md:flex flex-wrap gap-1.5">
                <Chip active={!cat} onClick={() => setCat(null)}>All</Chip>
                {Array.from(new Set(meta.questions.map((q) => q.category))).map((c) => <Chip key={c} active={cat === c} onClick={() => setCat(cat === c ? null : c)}>{c}</Chip>)}
              </div>} />
            <div className="overflow-x-auto border-t border-line">
              <table className="w-full min-w-[820px] text-[12.5px]">
                <thead>
                  <tr className="border-b border-line text-left text-[11px] text-ink-3">
                    <th className="sticky left-0 z-10 bg-elev px-5 py-2.5 font-normal">Question</th>
                    {[brand, ...series.filter((s) => !s.is_brand)].map((e) => (
                      <th key={e.id} className={cx("px-2 py-2.5 text-center font-normal", e.is_brand && "bg-accent-soft")}>
                        <div className="flex flex-col items-center gap-1"><EntityDot color={e.color} size={8} /><span className="max-w-20 truncate">{e.is_brand ? "You" : e.name.replace(/\s*\(.*\)/, "")}</span></div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.matrix.filter((r) => !cat || r.category === cat).map((r) => (
                    <tr key={r.id} onClick={() => setSp({ q: r.id })} className="cursor-pointer border-b border-line last:border-0 hover:bg-hover/50">
                      <td className="sticky left-0 z-10 max-w-[360px] bg-elev px-5 py-2.5">
                        <div className="truncate text-ink">{r.text}</div>
                        <div className="text-[10.5px] text-ink-3">{r.category}</div>
                      </td>
                      {[brand, ...series.filter((s) => !s.is_brand)].map((e) => <RankCell key={e.id} e={e} cell={r.cells[e.id] ?? {}} engine={engine} />)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
      <AnswerDrawer qid={qOpen} runId={run} onClose={() => setSp({})} />
    </div>
  );
}

function MiniStat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "warn" }) {
  return (
    <div className="rounded-lg bg-sunken py-2 ring-1 ring-inset ring-line">
      <div className={cx("text-[16px] tnum", tone === "warn" ? "text-med" : "text-ink")}>{value}</div>
      <div className="text-[10.5px] text-ink-3">{label}</div>
    </div>
  );
}

function RankCell({ e, cell, engine }: { e: Entity; cell: Record<string, number | null>; engine: string }) {
  const entries = Object.entries(cell).filter(([k]) => engine === "all" || k === engine);
  const ranks = entries.map(([, v]) => v).filter((v): v is number => v != null);
  const best = ranks.length ? Math.min(...ranks) : null;
  const tip = entries.map(([k, v]) => `${ENGINE_LABEL[k] ?? k}: ${v ? `#${v}` : "not mentioned"}`).join(" · ");
  return (
    <td className={cx("px-2 py-2.5 text-center", e.is_brand && "bg-accent-soft/60")} title={tip}>
      {best ? (
        <span className="inline-flex h-6 min-w-9 items-center justify-center gap-0.5 rounded-md px-1.5 text-[11px] tnum text-ink ring-1 ring-inset"
          style={{ background: `color-mix(in oklab, ${e.color} ${best === 1 ? 32 : best <= 3 ? 20 : 10}%, transparent)`, boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${e.color} 40%, transparent)` }}>
          #{best}{entries.length > 1 && <span className="font-normal text-ink-3">·{ranks.length}/{entries.length}</span>}
        </span>
      ) : <span className="text-ink-3/60">·</span>}
    </td>
  );
}

function AnswerDrawer({ qid, runId, onClose }: { qid: string | null; runId: string | null; onClose: () => void }) {
  const meta = useMeta();
  const { data } = useApi<AiAnswer[]>(qid ? `/api/ai/answers?question_id=${qid}${runId ? `&run_id=${runId}` : ""}` : null);
  const [tab, setTab] = useState(0);
  const q = meta.questions.find((x) => x.id === qid);
  const re = useMemo(() => {
    const terms = meta.entities.flatMap((e) => [e.name.replace(/\s*\(.*\)/, ""), ...(e.aliases ?? [])].map((t) => [t, e] as const)).filter(([t]) => t.length > 2)
      .sort((a, b) => b[0].length - a[0].length);
    return { rx: new RegExp(`(${terms.map(([t]) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi"), map: new Map(terms.map(([t, e]) => [t.toLowerCase(), e])) };
  }, [meta]);
  const a = data?.[Math.min(tab, (data?.length ?? 1) - 1)];
  return (
    <Drawer open={!!qid} onClose={onClose} width={720}>
      <div className="border-b border-line p-7 pr-14 glow">
        <div className="eyebrow mb-1">{q?.category} · Target question</div>
        <h2 className="text-[20px] leading-snug tracking-[-0.01em] text-ink">{q?.text}</h2>
        {data && data.length > 1 && (
          <div className="mt-4"><Segmented value={tab} onChange={setTab} options={data.map((d, i) => ({ value: i, label: ENGINE_LABEL[d.engine] ?? d.engine }))} /></div>
        )}
      </div>
      {!a ? <div className="p-7"><Skeleton className="h-64" /></div> : (
        <div className="space-y-6 p-7">
          <div className="flex flex-wrap gap-2">
            {Object.entries(a.mentions).filter(([, m]) => m.mentioned).sort((x, y) => (x[1].rank ?? 99) - (y[1].rank ?? 99)).map(([id, m]) => (
              <span key={id} className="inline-flex items-center gap-1.5 rounded-full bg-sunken px-2.5 py-1 text-[12px] ring-1 ring-inset ring-line">
                <span className="tnum text-ink-3">#{m.rank}</span><EntityTag id={id} />
              </span>
            ))}
            {!a.mentions["__brand__"]?.mentioned && <span className="inline-flex items-center gap-1.5 rounded-full bg-crit/10 px-2.5 py-1 text-[12px] text-crit ring-1 ring-inset ring-crit/20"><AlertTriangle size={12} />You're not mentioned</span>}
          </div>
          <div>
            <div className="eyebrow mb-2">Answer · {a.model}</div>
            <div className="whitespace-pre-wrap rounded-xl bg-sunken p-5 text-[13.5px] leading-relaxed text-ink-2 ring-1 ring-inset ring-line">
              {a.error ? <span className="text-crit">{a.error}</span> : a.answer.split(re.rx).map((part, i) => {
                const e = re.map.get(part.toLowerCase());
                return e ? <mark key={i} className="rounded px-0.5 text-ink" style={{ background: `color-mix(in oklab, ${e.color} 28%, transparent)` }}>{part}</mark> : part;
              })}
            </div>
          </div>
          {a.citations?.length > 0 && (
            <div>
              <div className="eyebrow mb-2">Sources cited ({a.citations.length})</div>
              <div className="space-y-1">
                {a.citations.map((c, i) => {
                  const own = meta.entities.find((e) => e.domains.some((d) => host(c.url).endsWith(d)));
                  return (
                    <a key={i} href={c.url} target="_blank" rel="noreferrer" className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[12.5px] hover:bg-hover">
                      <span className="w-4 text-right text-[11px] text-ink-3 tnum">{i + 1}</span>
                      {own ? <EntityDot color={own.color} size={7} /> : <span className="size-[7px] rounded-full bg-line-strong" />}
                      <span className="truncate text-ink-2">{c.title || host(c.url)}</span>
                      <span className="ml-auto shrink-0 text-[11px] text-ink-3">{host(c.url)}</span>
                      <ExternalLink size={11} className="shrink-0 text-ink-3" />
                    </a>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}
