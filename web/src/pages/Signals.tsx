import { useMemo, useState } from "react";
import { Activity, Search } from "lucide-react";
import { useApi } from "../lib/api";
import type { Change } from "../lib/types";
import { ChangeDrawer, ChangeRow, catLabel } from "../components/change";
import { Card, Chip, EntityDot, Empty, PageHeader, Segmented, Skeleton, useMeta } from "../components/ui";

const SEVS = ["critical", "high", "medium", "low"] as const;

export default function Signals() {
  const meta = useMeta();
  const [days, setDays] = useState(30);
  const { data } = useApi<Change[]>(`/api/changes?days=${days}`);
  const [comp, setComp] = useState<string | null>(null);
  const [minSev, setMinSev] = useState<"all" | "high">("all");
  const [cat, setCat] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [hideReviewed, setHideReviewed] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  const rows = useMemo(() => (data ?? []).filter((c) =>
    c.severity !== "noise" &&
    (!comp || c.competitor === comp) &&
    (minSev === "all" || c.severity === "critical" || c.severity === "high") &&
    (!cat || c.category === cat) &&
    (!hideReviewed || !c.acknowledged) &&
    (!q || `${c.headline} ${c.summary} ${c.so_what ?? ""} ${c.url}`.toLowerCase().includes(q.toLowerCase()))), [data, comp, minSev, cat, q, hideReviewed]);

  const groups = useMemo(() => {
    const g = new Map<string, Change[]>();
    for (const c of rows) {
      const k = new Date(c.detected_at).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
      g.set(k, [...(g.get(k) ?? []), c]);
    }
    return [...g.entries()];
  }, [rows]);

  const cats = useMemo(() => Array.from(new Set((data ?? []).map((c) => c.category))), [data]);
  const counts = useMemo(() => Object.fromEntries(SEVS.map((s) => [s, (data ?? []).filter((c) => c.severity === s).length])), [data]);

  return (
    <div>
      <PageHeader title="Signals" sub="Every meaningful change to competitor homepages, product and pricing pages, scored for impact and explained."
        right={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: "7d" }, { value: 30, label: "30d" }, { value: 90, label: "90d" }, { value: 365, label: "1y" }]} />} />

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {SEVS.map((s) => (
          <Card key={s} className="px-4 py-3">
            <div className="flex items-center gap-1.5 text-[11.5px] capitalize text-ink-3">
              <span className={`size-1.5 rounded-full ${s === "critical" ? "bg-crit" : s === "high" ? "bg-high" : s === "medium" ? "bg-med" : "bg-low"}`} />{s}
            </div>
            <div className="mt-1 text-[22px] font-semibold tnum text-ink">{counts[s] ?? 0}</div>
          </Card>
        ))}
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-line p-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex h-8 min-w-56 flex-1 items-center gap-2 rounded-lg bg-sunken px-3 ring-1 ring-inset ring-line focus-within:ring-accent/40">
              <Search size={14} className="text-ink-3" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter signals…" className="flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3" />
            </div>
            <Segmented value={minSev} onChange={setMinSev} options={[{ value: "all", label: "All" }, { value: "high", label: "High+" }]} />
            <Chip active={hideReviewed} onClick={() => setHideReviewed((v) => !v)}>Unreviewed only</Chip>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Chip active={!comp} onClick={() => setComp(null)}>All competitors</Chip>
            {meta.entities.filter((e) => !e.is_brand).map((e) => (
              <Chip key={e.id} active={comp === e.id} onClick={() => setComp(comp === e.id ? null : e.id)}><EntityDot color={e.color} size={7} />{e.name}</Chip>
            ))}
            <span className="mx-1 w-px self-stretch bg-line" />
            {cats.map((c) => <Chip key={c} active={cat === c} onClick={() => setCat(cat === c ? null : c)}>{catLabel(c)}</Chip>)}
          </div>
        </div>
        {!data ? (
          <div className="space-y-3 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : rows.length === 0 ? (
          <Empty icon={<Activity size={18} />} title={data.length ? "Nothing matches these filters" : "No signals yet"}>
            {data.length ? "Try widening the time range or clearing filters." : "Sentinel records a baseline on the first scan and reports changes from then on."}
          </Empty>
        ) : (
          groups.map(([label, items]) => (
            <div key={label}>
              <div className="sticky top-14 z-10 border-b border-line bg-elev/90 px-5 py-2 text-[11.5px] font-medium text-ink-3 backdrop-blur">{label}</div>
              <div className="divide-y divide-line">{items.map((c) => <ChangeRow key={c.id} c={c} onOpen={setOpen} active={open === c.id} />)}</div>
            </div>
          ))
        )}
      </Card>
      <ChangeDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}
