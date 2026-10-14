import { Check, ExternalLink, Lightbulb, Sparkles, Target } from "lucide-react";
import { api, invalidate, useApi } from "../lib/api";
import type { Change, ChangeDetail } from "../lib/types";
import { ago, host, path } from "../lib/format";
import { Button, cx, Drawer, EntityTag, Monogram, SeverityBadge, Skeleton, useEntity } from "./ui";
import { useToast } from "./shell";

const CAT_LABEL: Record<string, string> = {
  pricing: "Pricing", messaging: "Messaging", product: "Product", positioning: "Positioning", proof: "Proof", hiring: "Hiring", cosmetic: "Cosmetic",
};
export const catLabel = (c: string) => CAT_LABEL[c] ?? c;

export function ChangeRow({ c, onOpen, active, dense }: { c: Change; onOpen: (id: number) => void; active?: boolean; dense?: boolean }) {
  const e = useEntity(c.competitor);
  return (
    <button onClick={() => onOpen(c.id)}
      className={cx("group relative flex w-full items-start gap-3.5 px-5 text-left transition-colors focus-ring",
        dense ? "py-3" : "py-3.5", active ? "bg-hover" : "hover:bg-hover/60", c.acknowledged ? "opacity-60" : "")}>
      <span className="absolute left-0 top-3 bottom-3 w-[2px] rounded-full" style={{ background: active ? e?.color : "transparent" }} />
      <Monogram id={c.competitor} size={30} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-ink-3">
          <span className="font-medium text-ink-2">{e?.name}</span>
          <span>·</span><span>{catLabel(c.category)}</span>
          <span>·</span><span className="truncate max-w-48">{path(c.url)}</span>
        </div>
        <div className="mt-0.5 text-[13.5px] font-medium leading-snug text-ink">{c.headline}</div>
        {!dense && (c.so_what || c.summary) && <div className="mt-1 text-[12.5px] leading-relaxed text-ink-2 line-clamp-2">{c.so_what || c.summary}</div>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5">
        <SeverityBadge s={c.severity} compact />
        <span className="text-[11px] text-ink-3 tnum">{ago(c.detected_at)}</span>
      </div>
    </button>
  );
}

function SignalChips({ signals }: { signals: Record<string, any> }) {
  const out: React.ReactNode[] = [];
  const pill = (k: string, tone: "add" | "del" | "neutral", text: React.ReactNode) => (
    <span key={k} className={cx("inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] ring-1 ring-inset",
      tone === "add" ? "bg-good/10 text-good ring-good/20" : tone === "del" ? "bg-crit/10 text-crit ring-crit/20 line-through decoration-crit/50" : "bg-sunken text-ink-2 ring-line")}>
      {text}
    </span>
  );
  for (const k of ["prices", "h1", "ctas", "headings"]) {
    const v = signals[k];
    if (!v) continue;
    v.removed?.forEach((s: string, i: number) => out.push(pill(`${k}-r${i}`, "del", s)));
    v.added?.forEach((s: string, i: number) => out.push(pill(`${k}-a${i}`, "add", s)));
  }
  if (signals.terms) {
    for (const [t, v] of Object.entries<any>(signals.terms)) {
      out.push(pill(`t-${t}`, v.to > v.from ? "add" : "del", <><span className="font-medium">{t}</span><span className="opacity-70 tnum">{v.from}→{v.to}</span></>));
    }
  }
  if (!out.length) return null;
  return <div className="flex flex-wrap gap-1.5">{out}</div>;
}

export function ChangeDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: c } = useApi<ChangeDetail>(id ? `/api/changes/${id}` : null);
  const toast = useToast();
  const ack = async () => {
    if (!c) return;
    await api(`/api/changes/${c.id}/ack?value=${!c.acknowledged}`, { method: "POST" });
    toast({ title: c.acknowledged ? "Marked as unread" : "Marked as reviewed" });
    invalidate();
  };
  const ready = c && c.id === id;
  return (
    <Drawer open={id != null} onClose={onClose} width={720}>
      {!ready ? (
        <div className="p-8 space-y-4"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-4 w-3/4" /><Skeleton className="h-40 w-full" /></div>
      ) : (
        <div>
          <div className="border-b border-line p-7 pr-14 glow">
            <div className="flex items-center gap-2.5">
              <EntityTag id={c.competitor} />
              <span className="text-ink-3">·</span>
              <SeverityBadge s={c.severity} />
              <span className="rounded-md bg-sunken px-2 py-0.5 text-[11px] text-ink-2 ring-1 ring-inset ring-line">{catLabel(c.category)}</span>
            </div>
            <h2 className="mt-3 text-[22px] font-semibold leading-tight tracking-[-0.015em] text-ink">{c.headline}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-3">
              <a href={c.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-ink">
                {host(c.url)}{path(c.url)} <ExternalLink size={11} />
              </a>
              <span>Detected {ago(c.detected_at)}</span>
              <span className="tnum">{Math.round(c.change_ratio * 100)}% of page changed</span>
            </div>
            <div className="mt-5 flex gap-2">
              <Button variant="outline" size="sm" onClick={ack}><Check size={13} />{c.acknowledged ? "Mark unread" : "Mark reviewed"}</Button>
              <Button variant="ghost" size="sm" onClick={() => window.open(c.url, "_blank")}><ExternalLink size={13} />Open page</Button>
            </div>
          </div>

          <div className="space-y-6 p-7">
            <div className="grid gap-3 sm:grid-cols-2">
              <Insight icon={<Sparkles size={14} />} title="What changed" body={c.summary} />
              {c.so_what && <Insight icon={<Lightbulb size={14} />} title="Why it matters" body={c.so_what} accent />}
              {c.action && <Insight icon={<Target size={14} />} title="Recommended action" body={c.action} className="sm:col-span-2" />}
            </div>

            {Object.keys(c.signals || {}).length > 0 && (
              <section>
                <div className="eyebrow mb-2.5">Structured signals</div>
                <SignalChips signals={c.signals} />
                {(c.signals.title || c.signals.meta) && (
                  <div className="mt-3 space-y-2 text-[12.5px]">
                    {["title", "meta"].filter((k) => c.signals[k]).map((k) => (
                      <div key={k} className="rounded-lg bg-sunken p-3 ring-1 ring-inset ring-line">
                        <div className="eyebrow mb-1">{k === "meta" ? "Meta description" : "Page title"}</div>
                        <div className="text-crit/90 line-through decoration-crit/40">{c.signals[k].from || "—"}</div>
                        <div className="text-good mt-0.5">{c.signals[k].to || "—"}</div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            <section>
              <div className="mb-2.5 flex items-center justify-between">
                <div className="eyebrow">Page diff</div>
                <div className="flex gap-3 text-[11.5px] text-ink-3">
                  <span className="inline-flex items-center gap-1"><span className="size-2 rounded-sm bg-good/60" />{c.added.length} added</span>
                  <span className="inline-flex items-center gap-1"><span className="size-2 rounded-sm bg-crit/60" />{c.removed.length} removed</span>
                </div>
              </div>
              <div className="overflow-hidden rounded-xl ring-1 ring-line bg-sunken font-mono text-[12px] leading-[1.65]">
                {c.diff.length === 0 && <div className="p-4 text-ink-3 font-sans">Snapshot text not available.</div>}
                {c.diff.map((l, i) => l.t === "gap" ? (
                  <div key={i} className="border-y border-line bg-bg/40 px-4 py-1 text-center text-[11px] text-ink-3 font-sans">⋯ {l.s} ⋯</div>
                ) : (
                  <div key={i} className={cx("flex gap-3 px-4 py-[1px]",
                    l.t === "add" && "bg-good/[0.09] text-ink", l.t === "del" && "bg-crit/[0.08] text-ink-2", l.t === "eq" && "text-ink-3")}>
                    <span className={cx("w-3 shrink-0 select-none", l.t === "add" ? "text-good" : l.t === "del" ? "text-crit" : "text-transparent")}>{l.t === "add" ? "+" : l.t === "del" ? "−" : " "}</span>
                    <span className="whitespace-pre-wrap break-words">{l.s}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
    </Drawer>
  );
}

function Insight({ icon, title, body, accent, className }: { icon: React.ReactNode; title: string; body: string; accent?: boolean; className?: string }) {
  return (
    <div className={cx("rounded-xl p-4 ring-1 ring-inset", accent ? "bg-accent-soft ring-accent/20" : "bg-sunken ring-line", className)}>
      <div className={cx("mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium", accent ? "text-accent-ink" : "text-ink-3")}>{icon}{title}</div>
      <p className="text-[13.5px] leading-relaxed text-ink">{body}</p>
    </div>
  );
}
