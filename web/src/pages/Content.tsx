import { useMemo, useState } from "react";
import { ExternalLink, Newspaper, Search } from "lucide-react";
import { useApi } from "../lib/api";
import type { Post } from "../lib/types";
import { ago, day } from "../lib/format";
import { Card, CardHeader, Chip, cx, EntityDot, Empty, Monogram, PageHeader, Segmented, Skeleton, useEntity, useMeta } from "../components/ui";

export default function Content() {
  const meta = useMeta();
  const [days, setDays] = useState(30);
  const { data } = useApi<Post[]>(`/api/posts?days=${days}`);
  const [comp, setComp] = useState<string | null>(null);
  const [topic, setTopic] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [hover, setHover] = useState<string | null>(null);
  const comps = meta.entities.filter((e) => !e.is_brand);

  const rows = useMemo(() => (data ?? []).filter((p) =>
    (!comp || p.competitor === comp) && (!topic || p.topics?.includes(topic)) &&
    (!q || `${p.title} ${p.summary}`.toLowerCase().includes(q.toLowerCase()))), [data, comp, topic, q]);

  // competitor × topic matrix (sequential single hue = magnitude)
  const matrix = useMemo(() => {
    const m: Record<string, Record<string, number>> = {};
    for (const p of data ?? []) for (const t of p.topics ?? []) { m[p.competitor] ??= {}; m[p.competitor][t] = (m[p.competitor][t] ?? 0) + 1; }
    return m;
  }, [data]);
  const topics = meta.watch_terms.filter((t) => comps.some((c) => matrix[c.id]?.[t]));
  const mmax = Math.max(1, ...Object.values(matrix).flatMap((r) => Object.values(r)));

  return (
    <div>
      <PageHeader title="Content" sub="Every new competitor blog post and announcement, tagged by the themes you care about."
        right={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: "7d" }, { value: 30, label: "30d" }, { value: 90, label: "90d" }, { value: 3650, label: "All" }]} />} />

      <Card className="mb-4">
        <CardHeader title="Narrative heatmap" sub="Which themes each competitor is publishing about. Click a cell to filter." />
        <div className="overflow-x-auto px-5 pb-5">
          {!data ? <Skeleton className="h-40" /> : topics.length === 0 ? <div className="py-6 text-center text-[13px] text-ink-3">No tagged posts in this window.</div> : (
            <table className="w-full border-separate" style={{ borderSpacing: 3 }}>
              <thead>
                <tr><th />{topics.map((t) => <th key={t} className="px-1 pb-1 text-left align-bottom text-[11px] font-normal text-ink-3 whitespace-nowrap">{t}</th>)}</tr>
              </thead>
              <tbody>
                {comps.map((c) => (
                  <tr key={c.id}>
                    <td className="pr-3 text-[12px] text-ink-2 whitespace-nowrap"><span className="inline-flex items-center gap-1.5"><EntityDot color={c.color} size={7} />{c.name}</span></td>
                    {topics.map((t) => {
                      const v = matrix[c.id]?.[t] ?? 0, k = `${c.id}|${t}`;
                      return (
                        <td key={t} className="relative p-0">
                          <button onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)}
                            onClick={() => { setComp(c.id); setTopic(t); }}
                            aria-label={`${c.name}, ${t}: ${v} posts`}
                            className={cx("h-8 w-full min-w-12 rounded-[5px] text-[11px] tnum transition-transform hover:scale-[1.06] focus-ring", v ? "text-white" : "text-ink-3")}
                            style={{ background: v ? `color-mix(in oklab, var(--accent) ${18 + (v / mmax) * 82}%, var(--bg-sunken))` : "var(--bg-sunken)" }}>
                            {v || ""}
                          </button>
                          {hover === k && <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-md bg-elev px-2 py-1 text-[11px] text-ink shadow-lg ring-1 ring-line-strong">{c.name} · {t}: <b>{v}</b></div>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-line p-4">
          <div className="flex h-8 items-center gap-2 rounded-lg bg-sunken px-3 ring-1 ring-inset ring-line focus-within:ring-accent/40">
            <Search size={14} className="text-ink-3" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search posts…" className="flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3" />
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Chip active={!comp} onClick={() => setComp(null)}>All</Chip>
            {comps.map((e) => <Chip key={e.id} active={comp === e.id} onClick={() => setComp(comp === e.id ? null : e.id)}><EntityDot color={e.color} size={7} />{e.name}</Chip>)}
            {topic && <Chip active onClick={() => setTopic(null)}>#{topic} ✕</Chip>}
          </div>
        </div>
        {!data ? <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}</div>
          : rows.length === 0 ? <Empty icon={<Newspaper size={18} />} title="No posts match">Run a feed sync or widen the time range.</Empty>
          : <div className="divide-y divide-line">{rows.map((p) => <PostRow key={p.id} p={p} onTopic={setTopic} />)}</div>}
      </Card>
    </div>
  );
}

function PostRow({ p, onTopic }: { p: Post; onTopic: (t: string) => void }) {
  const e = useEntity(p.competitor);
  return (
    <div className="group flex gap-4 px-5 py-4 hover:bg-hover/50">
      <Monogram id={p.competitor} size={30} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[11.5px] text-ink-3">
          <span className="font-medium text-ink-2">{e?.name}</span><span>·</span>
          <span>{p.published ? day(p.published) : `seen ${ago(p.first_seen)}`}</span>
        </div>
        <a href={p.url} target="_blank" rel="noreferrer" className="mt-0.5 inline-flex items-start gap-1.5 text-[14px] font-medium leading-snug text-ink hover:text-accent-ink">
          {p.title}<ExternalLink size={12} className="mt-1 shrink-0 opacity-0 group-hover:opacity-60" />
        </a>
        {p.summary && <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2 line-clamp-2">{p.summary}</p>}
        {p.topics?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {p.topics.map((t) => <button key={t} onClick={() => onTopic(t)} className="rounded bg-sunken px-1.5 py-0.5 text-[10.5px] text-ink-3 ring-1 ring-inset ring-line hover:text-ink">#{t}</button>)}
          </div>
        )}
      </div>
    </div>
  );
}
