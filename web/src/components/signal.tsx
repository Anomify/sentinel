import { Check, ExternalLink } from "lucide-react";
import { api, invalidate, useApi } from "../lib/api";
import type { SignalEvent } from "../lib/types";
import { ago, host, path } from "../lib/format";
import { Button, Confidence, cx, Drawer, EntityTag, EvidenceList, Monogram, SeverityBadge, Skeleton, Thumb, useEntity, useMeta } from "./ui";
import { useToast } from "./shell";

export function moduleLabel(meta: { modules: Record<string, string> }, m: string) {
  return meta.modules?.[m] ?? m;
}

export function EventRow({ e, onOpen, active, showCompetitor = true }: { e: SignalEvent; onOpen: (id: number) => void; active?: boolean; showCompetitor?: boolean }) {
  const ent = useEntity(e.competitor);
  const meta = useMeta();
  return (
    <button onClick={() => onOpen(e.id)}
      className={cx("group flex w-full items-start gap-4 px-6 py-4 text-left transition-colors focus-ring", active ? "bg-hover" : "hover:bg-hover/70", e.acknowledged ? "opacity-55" : "")}>
      {showCompetitor && <Monogram id={e.competitor} size={30} />}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-ink-3">
          {showCompetitor && <span className="text-ink-2">{ent?.name}</span>}
          {showCompetitor && <span>·</span>}
          <span>{moduleLabel(meta, e.module)}</span>
          <span>·</span>
          <Confidence c={e.confidence} />
        </div>
        <div className="mt-1 text-[14px] leading-snug text-ink">{e.title}</div>
        {(e.so_what || e.detail) && <div className="mt-1 line-clamp-2 text-[12.5px] leading-relaxed text-ink-2">{e.so_what || e.detail}</div>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5 pt-0.5">
        <SeverityBadge s={e.severity} />
        <span className="text-[11px] text-ink-3 tnum">{ago(e.detected_at)}</span>
      </div>
    </button>
  );
}

export function EventDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: e } = useApi<SignalEvent>(id ? `/api/events/${id}` : null);
  const meta = useMeta();
  const toast = useToast();
  const ready = e && e.id === id;
  const ack = async () => {
    if (!e) return;
    await api(`/api/events/${e.id}/ack?value=${!e.acknowledged}`, { method: "POST" });
    toast({ title: e.acknowledged ? "Marked unread" : "Marked reviewed" });
    invalidate();
  };
  const c = e?.change;
  const shot = c?.after?.screenshot || e?.evidence?.find((x) => x.screenshot)?.screenshot;
  return (
    <Drawer open={id != null} onClose={onClose} width={740}>
      {!ready ? (
        <div className="space-y-4 p-10"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-4 w-3/4" /><Skeleton className="h-48 w-full" /></div>
      ) : (
        <div>
          <div className="border-b border-line px-9 pb-7 pt-9 pr-16">
            <div className="flex flex-wrap items-center gap-3 text-[12px]">
              <EntityTag id={e.competitor} />
              <span className="text-ink-3">{moduleLabel(meta, e.module)}</span>
              <SeverityBadge s={e.severity} />
              <Confidence c={e.confidence} />
            </div>
            <h2 className="mt-4 text-[24px] leading-tight tracking-[-0.02em] text-ink">{e.title}</h2>
            <div className="mt-2 text-[12.5px] text-ink-3">Detected {ago(e.detected_at)} · {new Date(e.detected_at).toLocaleString()}</div>
            <div className="mt-5 flex gap-2">
              <Button variant="outline" size="sm" onClick={ack}><Check size={13} />{e.acknowledged ? "Mark unread" : "Mark reviewed"}</Button>
              {e.evidence?.[0]?.url && <Button variant="ghost" size="sm" onClick={() => window.open(e.evidence[0].url!, "_blank")}><ExternalLink size={13} />Open source</Button>}
            </div>
          </div>
          <div className="space-y-8 px-9 py-8">
            {(e.so_what || c?.so_what) && (
              <section>
                <div className="eyebrow mb-2">Why it matters</div>
                <p className="text-[15px] leading-relaxed text-ink">{e.so_what || c?.so_what}</p>
              </section>
            )}
            {(c?.action || e.data?.action) && (
              <section className="rounded-2xl bg-accent-soft px-5 py-4">
                <div className="mb-1 text-[11.5px] text-accent-ink">Vs. us — recommended response</div>
                <p className="text-[14px] leading-relaxed text-ink">{c?.action || e.data?.action}</p>
              </section>
            )}
            {(e.detail || c?.summary) && (
              <section>
                <div className="eyebrow mb-2">Detail</div>
                <p className="text-[13.5px] leading-relaxed text-ink-2">{c?.summary || e.detail}</p>
              </section>
            )}
            {shot && <Thumb name={shot} className="aspect-[16/10] w-full" />}
            {c && <PageDiff c={c} />}
            {!c && e.data && Object.keys(e.data).filter((k) => !["kind", "key"].includes(k)).length > 0 && (
              <section>
                <div className="eyebrow mb-2">Data</div>
                <div className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-1.5 text-[12.5px]">
                  {Object.entries(e.data).filter(([k, v]) => !["kind", "key"].includes(k) && v != null && v !== "").slice(0, 14).map(([k, v]) => (
                    <div key={k} className="contents"><span className="text-ink-3">{k.replace(/_/g, " ")}</span><span className="break-words text-ink-2">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span></div>
                  ))}
                </div>
              </section>
            )}
            <section>
              <div className="eyebrow mb-3">Evidence trail</div>
              <EvidenceList items={e.evidence || []} />
            </section>
          </div>
        </div>
      )}
    </Drawer>
  );
}

function PageDiff({ c }: { c: NonNullable<SignalEvent["change"]> }) {
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <div className="eyebrow">Page diff · <a href={c.url} target="_blank" rel="noreferrer" className="normal-case tracking-normal hover:text-ink">{host(c.url)}{path(c.url)}</a></div>
        <div className="text-[11.5px] text-ink-3 tnum">+{c.added.length} · −{c.removed.length} · {Math.round(c.change_ratio * 100)}%</div>
      </div>
      <div className="overflow-hidden rounded-2xl border border-line bg-[#fbfbfa] font-mono text-[12px] leading-[1.7]">
        {c.diff.length === 0 && <div className="p-4 font-sans text-ink-3">Snapshot text not available.</div>}
        {c.diff.map((l, i) => l.t === "gap" ? (
          <div key={i} className="border-y border-line px-4 py-1 text-center font-sans text-[11px] text-ink-3">{l.s}</div>
        ) : (
          <div key={i} className={cx("flex gap-3 px-4", l.t === "add" && "bg-good/[0.07] text-ink", l.t === "del" && "bg-crit/[0.06] text-ink-2 line-through decoration-crit/30", l.t === "eq" && "text-ink-3")}>
            <span className={cx("w-3 shrink-0 select-none", l.t === "add" ? "text-good" : l.t === "del" ? "text-crit" : "text-transparent")}>{l.t === "add" ? "+" : l.t === "del" ? "−" : " "}</span>
            <span className="whitespace-pre-wrap break-words">{l.s}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
