import { useMemo, useState } from "react";
import { ExternalLink, Search, X as Close } from "lucide-react";
import { useApi } from "../lib/api";
import { day } from "../lib/format";
import { StackedBars } from "../components/charts";
import { Card, CardHeader, Chip, cx, Empty, EntityDot, Monogram, PageHeader, Segmented, Skeleton, useMeta } from "../components/ui";

interface Item {
  id: string; competitor: string; channel: string; title: string; text: string; url: string; date: string | null;
  type: string; topics: string[]; engagement: Record<string, number> | null; first_seen: string; via: string;
}
interface Channel { platform: string; label: string; url: string; manual: string | null; how: string }
interface Data { items: Item[]; channels: Record<string, Channel[]>; search_key: boolean; x_api: boolean }

const CH: Record<string, string> = { blog: "Blog", linkedin: "LinkedIn", x: "X", youtube: "YouTube", medium: "Medium", bluesky: "Bluesky", hackernews: "Hacker News" };
const ORDER = ["blog", "linkedin", "x", "youtube", "medium", "bluesky", "hackernews"];
const PERIODS = [{ value: 7, label: "7d" }, { value: 30, label: "30d" }, { value: 90, label: "90d" }, { value: 365, label: "1y" }, { value: 0, label: "All" }];
const DAY = 864e5;

const when = (i: Item) => i.date ?? i.first_seen;
const isNew = (i: Item) => !!i.date && Date.now() - new Date(i.date).getTime() < 30 * DAY;
const eng = (i: Item) => !i.engagement ? 0 : Object.values(i.engagement).reduce((a, b) => a + (Number(b) || 0), 0);

export default function Messaging() {
  const meta = useMeta();
  const { data } = useApi<Data>("/api/messaging");
  const comps = meta.entities.filter((e) => !e.is_brand);
  const [who, setWho] = useState<Set<string>>(new Set());
  const [chan, setChan] = useState<Set<string>>(new Set());
  const [type, setType] = useState<string | null>(null);
  const [days, setDays] = useState<number>(90);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"newest" | "engagement">("newest");
  const toggle = (s: Set<string>, set: (x: Set<string>) => void, v: string) => { const n = new Set(s); n.has(v) ? n.delete(v) : n.add(v); set(n); };

  const inPeriod = (i: Item) => !days || (Date.now() - new Date(when(i)).getTime()) < days * DAY;
  const base = useMemo(() => (data?.items ?? []).filter(inPeriod), [data, days]);  // eslint-disable-line react-hooks/exhaustive-deps
  const items = useMemo(() => {
    const rx = q.trim().toLowerCase();
    const out = base.filter((i) => (!who.size || who.has(i.competitor)) && (!chan.size || chan.has(i.channel)) && (!type || i.type === type)
      && (!rx || `${i.title} ${i.text}`.toLowerCase().includes(rx)));
    return sort === "engagement" ? [...out].sort((a, b) => eng(b) - eng(a)) : out;
  }, [base, who, chan, type, q, sort]);

  // counts for the filter chips reflect the other active filters
  const count = (pred: (i: Item) => boolean) => base.filter(pred).length;
  const types = useMemo(() => [...new Set(base.map((i) => i.type))].filter((t) => !["Post", "Article", "Blog"].includes(t)).sort(), [base]);

  // weekly volume per company (last 12 weeks) for the chart
  const weekly = useMemo(() => {
    const weeks: Record<string, any> = {};
    const now = Date.now();
    for (let w = 11; w >= 0; w--) {
      const d = new Date(now - w * 7 * DAY); d.setHours(0, 0, 0, 0);
      weeks[w] = { date: d.toISOString().slice(0, 10) };
    }
    for (const i of data?.items ?? []) {
      if ((chan.size && !chan.has(i.channel)) || !i.date) continue;
      const w = Math.floor((now - new Date(i.date).getTime()) / (7 * DAY));
      if (w >= 0 && w < 12) weeks[w][i.competitor] = (weeks[w][i.competitor] ?? 0) + 1;
    }
    return Object.keys(weeks).map(Number).sort((a, b) => b - a).map((w) => weeks[w]);
  }, [data, chan]);

  const active = who.size + chan.size + (type ? 1 : 0) + (q ? 1 : 0);
  const reset = () => { setWho(new Set()); setChan(new Set()); setType(null); setQ(""); };

  return (
    <div>
      <PageHeader eyebrow="Messaging" title="Messaging" sub="Everything each company publishes, on its blog and its social channels, in one feed. Filter by company, channel, content type and period, or search the text." />
      {!data ? <Skeleton className="h-[600px] rounded-2xl" /> : (
        <div className="space-y-5">
          <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
            <Card className="p-6">
              <div className="mb-1 flex items-baseline justify-between">
                <div className="text-[14px] text-ink">Publishing volume</div>
                <div className="text-[12px] text-ink-3">posts per week, last 12 weeks{chan.size ? ` · ${[...chan].map((c) => CH[c]).join(", ")}` : ""}</div>
              </div>
              <StackedBars data={weekly} series={who.size ? comps.filter((c) => who.has(c.id)) : comps} height={170} fmtDate={(d) => day(d)} />
            </Card>
            <Card className="overflow-hidden">
              <CardHeader title="Channels" sub="How each account is read" />
              <div className="max-h-[260px] divide-y divide-line overflow-y-auto border-t border-line">
                {comps.map((c) => (
                  <div key={c.id} className="flex items-start gap-3 px-5 py-2.5">
                    <EntityDot color={c.color} size={7} />
                    <div className="min-w-0 flex-1">
                      <div className="text-[12.5px] text-ink">{c.name}{c.tier === "self" ? " (us)" : ""}</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {(data.channels[c.id] ?? []).filter((x) => ["linkedin", "x", "youtube", "medium", "bluesky"].includes(x.platform)).map((x) => (
                          <a key={x.platform} href={x.manual ?? x.url} target="_blank" rel="noreferrer" title={x.how}
                            className={cx("rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset", x.how === "needs search key" ? "text-ink-3 ring-line" : "text-ink-2 ring-line hover:text-ink")}>
                            {CH[x.platform] ?? x.label}{x.how === "needs search key" ? " · not yet" : ""}
                          </a>))}
                        {!(data.channels[c.id] ?? []).length && <span className="text-[11px] text-ink-3">No accounts found</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {!data.search_key && (
                <div className="border-t border-line bg-sunken px-5 py-3 text-[11.5px] leading-relaxed text-ink-2">
                  LinkedIn and X posts need a search API key. Add <code className="font-mono">BRAVE_SEARCH_API_KEY</code> (free tier) or <code className="font-mono">SERPAPI_API_KEY</code> to .env{data.x_api ? "" : ", or X_BEARER_TOKEN for X"}.
                </div>
              )}
            </Card>
          </div>

          <Card className="overflow-hidden">
            <div className="space-y-3 border-b border-line px-5 py-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative min-w-[240px] flex-1">
                  <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-3" />
                  <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search titles and text, e.g. agentic, MCP, red teaming"
                    className="h-9 w-full rounded-full bg-sunken pl-9 pr-4 text-[13px] outline-none" />
                </div>
                <Segmented value={days} onChange={setDays} options={PERIODS} />
                <Segmented value={sort} onChange={setSort} options={[{ value: "newest", label: "Newest" }, { value: "engagement", label: "Engagement" }]} />
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 w-16 text-[11px] uppercase tracking-wide text-ink-3">Company</span>
                {comps.map((c) => {
                  const n = count((i) => i.competitor === c.id && (!chan.size || chan.has(i.channel)));
                  return <Chip key={c.id} active={who.has(c.id)} onClick={() => toggle(who, setWho, c.id)}>
                    <EntityDot color={c.color} size={6} /><span className="ml-1.5">{c.name}{c.tier === "self" ? " (us)" : ""}</span><span className="ml-1.5 text-ink-3">{n}</span>
                  </Chip>;
                })}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 w-16 text-[11px] uppercase tracking-wide text-ink-3">Channel</span>
                {ORDER.map((ch) => {
                  const n = count((i) => i.channel === ch && (!who.size || who.has(i.competitor)));
                  return <Chip key={ch} active={chan.has(ch)} onClick={() => toggle(chan, setChan, ch)}>{CH[ch]}<span className="ml-1.5 text-ink-3">{n}</span></Chip>;
                })}
              </div>
              {types.length > 1 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="mr-1 w-16 text-[11px] uppercase tracking-wide text-ink-3">Type</span>
                  {types.map((t) => <Chip key={t} active={type === t} onClick={() => setType(type === t ? null : t)}>{t}</Chip>)}
                </div>
              )}
            </div>
            <div className="flex items-center justify-between px-5 py-2.5 text-[12px] text-ink-3">
              <span>{items.length} {items.length === 1 ? "item" : "items"}{days ? ` in the last ${days} days` : ""}</span>
              {active > 0 && <button onClick={reset} className="inline-flex items-center gap-1 hover:text-ink"><Close size={12} />Clear filters</button>}
            </div>
            <div className="divide-y divide-line border-t border-line">
              {items.slice(0, 300).map((i) => {
                const e = comps.find((c) => c.id === i.competitor);
                return (
                  <a key={i.id} href={i.url} target="_blank" rel="noreferrer" className="group grid grid-cols-[auto_1fr_auto] gap-4 px-5 py-3.5 hover:bg-hover/60">
                    <Monogram id={i.competitor} size={28} />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-x-2 text-[11.5px] text-ink-3">
                        <span className="text-ink-2">{e?.name ?? i.competitor}</span><span>·</span><span>{CH[i.channel] ?? i.channel}</span>
                        {i.type && !["Post", "Article", "Blog"].includes(i.type) && <><span>·</span><span>{i.type}</span></>}
                        {i.via === "search" && <><span>·</span><span title="Found through a search engine index">via search</span></>}
                        {isNew(i) && <Chip className="ml-1">new</Chip>}
                      </div>
                      <div className="mt-0.5 text-[13.5px] leading-snug text-ink">{i.title}</div>
                      {i.text && i.text !== i.title && <div className="mt-1 line-clamp-2 text-[12.5px] leading-relaxed text-ink-3">{i.text}</div>}
                      {i.engagement && eng(i) > 0 && (
                        <div className="mt-1 text-[11.5px] text-ink-3">{Object.entries(i.engagement).filter(([, v]) => Number(v) > 0).map(([k, v]) => `${v} ${k.replace(/_count$/, "").replace(/_/g, " ")}`).join(" · ")}</div>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1 text-[11.5px] text-ink-3">
                      <span className="whitespace-nowrap">{i.date ? day(i.date) : "date not shown"}</span>
                      <ExternalLink size={12} className="opacity-0 transition-opacity group-hover:opacity-60" />
                    </div>
                  </a>
                );
              })}
              {!items.length && <Empty title="Nothing matches these filters">Try a longer period or clear the filters.</Empty>}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
