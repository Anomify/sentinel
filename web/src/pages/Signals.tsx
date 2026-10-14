import { useMemo, useState } from "react";
import { Activity, Search } from "lucide-react";
import { useApi } from "../lib/api";
import type { SignalEvent } from "../lib/types";
import { EventDrawer, EventRow, moduleLabel } from "../components/signal";
import { Card, Chip, EntityDot, Empty, PageHeader, Segmented, Skeleton, useMeta } from "../components/ui";

const SEVS = ["critical", "high", "medium", "low"] as const;

export default function Signals() {
  const meta = useMeta();
  const [days, setDays] = useState(30);
  const { data } = useApi<SignalEvent[]>(`/api/events?days=${days}`);
  const [comp, setComp] = useState<string | null>(null);
  const [mod, setMod] = useState<string | null>(null);
  const [minSev, setMinSev] = useState<"all" | "high">("all");
  const [q, setQ] = useState("");
  const [unread, setUnread] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  const rows = useMemo(() => (data ?? []).filter((e) =>
    (!comp || e.competitor === comp) && (!mod || moduleLabel(meta, e.module) === mod) &&
    (minSev === "all" || e.severity === "critical" || e.severity === "high") && (!unread || !e.acknowledged) &&
    (!q || `${e.title} ${e.detail ?? ""} ${e.so_what ?? ""}`.toLowerCase().includes(q.toLowerCase()))), [data, comp, mod, minSev, q, unread, meta]);
  const groups = useMemo(() => {
    const g = new Map<string, SignalEvent[]>();
    for (const e of rows) {
      const k = new Date(e.detected_at).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
      g.set(k, [...(g.get(k) ?? []), e]);
    }
    return [...g.entries()];
  }, [rows]);
  const modules = useMemo(() => Array.from(new Set((data ?? []).map((e) => moduleLabel(meta, e.module)))).sort(), [data, meta]);
  const counts = useMemo(() => Object.fromEntries(SEVS.map((s) => [s, (data ?? []).filter((e) => e.severity === s).length])), [data]);

  return (
    <div>
      <PageHeader title="Signals" sub="Every change Sentinel detects across stack, tracking, DNS, certificates, staging, hiring, partners, ads, positioning and AI search — scored, labelled and evidenced."
        right={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: "7d" }, { value: 30, label: "30d" }, { value: 90, label: "90d" }, { value: 365, label: "1y" }]} />} />
      <Card className="mb-5 grid grid-cols-2 divide-line sm:grid-cols-4 sm:divide-x">
        {SEVS.map((s) => (
          <div key={s} className="px-6 py-4">
            <div className="eyebrow">{s}</div>
            <div className="mt-1.5 text-[26px] leading-none tracking-[-0.02em] tnum text-ink">{counts[s] ?? 0}</div>
          </div>
        ))}
      </Card>
      <Card className="overflow-hidden">
        <div className="space-y-3 border-b border-line p-5">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex h-9 min-w-56 flex-1 items-center gap-2 rounded-full bg-sunken px-4">
              <Search size={14} className="text-ink-3" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter signals…" className="flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3" />
            </div>
            <Segmented value={minSev} onChange={setMinSev} options={[{ value: "all", label: "All" }, { value: "high", label: "High+" }]} />
            <Chip active={unread} onClick={() => setUnread((v) => !v)}>Unreviewed</Chip>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Chip active={!comp} onClick={() => setComp(null)}>All competitors</Chip>
            {meta.entities.filter((e) => !e.is_brand).map((e) => (
              <Chip key={e.id} active={comp === e.id} onClick={() => setComp(comp === e.id ? null : e.id)}><EntityDot color={e.color} size={7} />{e.name}</Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Chip active={!mod} onClick={() => setMod(null)}>All modules</Chip>
            {modules.map((m) => <Chip key={m} active={mod === m} onClick={() => setMod(mod === m ? null : m)}>{m}</Chip>)}
          </div>
        </div>
        {!data ? <div className="space-y-3 p-6">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}</div>
          : rows.length === 0 ? (
            <Empty icon={<Activity size={16} />} title={data.length ? "Nothing matches these filters" : "No signals yet"}>
              {data.length ? "Widen the time range or clear filters." : "Each module records a baseline on its first run; changes alert from the second run."}
            </Empty>
          ) : groups.map(([label, items]) => (
            <div key={label}>
              <div className="sticky top-16 z-10 border-b border-line bg-elev/95 px-6 py-2 text-[11.5px] text-ink-3 backdrop-blur">{label}</div>
              <div className="divide-y divide-line">{items.map((e) => <EventRow key={e.id} e={e} onOpen={setOpen} active={open === e.id} />)}</div>
            </div>
          ))}
      </Card>
      <EventDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}
