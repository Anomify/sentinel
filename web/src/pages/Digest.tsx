import { useState } from "react";
import { Download, Monitor, Smartphone } from "lucide-react";
import { api, getToken, invalidate, useApi, workspace } from "../lib/api";
import { ago, day } from "../lib/format";
import { Button, Card, CardHeader, cx, Empty, PageHeader, Segmented, useMeta } from "../components/ui";
import { useToast } from "../components/shell";

interface DigestRow { id: number; created_at: string; period_start: string; period_end: string; headline: string; delivered: Record<string, string> }

export default function Digest() {
  const meta = useMeta();
  const { data } = useApi<DigestRow[]>("/api/digests");
  const [sel, setSel] = useState<number | "live">("live");
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const t = getToken();
  const src = sel === "live" ? `/api/digests/preview${t ? `?token=${t}` : ""}` : `/api/digests/${sel}/html${t ? `?token=${t}` : ""}`;
  const sched = meta.schedule.find((s) => s.job === "digest");
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const download = (id: number) => {
    const q = new URLSearchParams({ ws: workspace(), ...(t ? { token: t } : {}) });
    window.location.href = `/api/digests/${id}/pdf?${q}`;
  };
  const exportPdf = async () => {
    setBusy(true);
    try {
      let id = sel;
      if (id === "live") {
        const r = await api<{ digest_id: number }>("/api/digests?deliver=false", { method: "POST" });
        invalidate(); setSel(r.digest_id); id = r.digest_id;
      }
      download(id as number);
      toast({ title: "Exporting PDF", body: "The download starts in a few seconds.", tone: "info" });
    } catch (e) {
      toast({ title: "Couldn't export PDF", body: String((e as Error).message), tone: "err" });
    } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Weekly digest" sub="The weekly brief, written for a PMM heading into launch: what moved, why it matters, what to do. Export it as a PDF to share."
        right={<Button variant="primary" onClick={exportPdf} disabled={busy}><Download size={14} />{busy ? "Preparing…" : sel === "live" ? "Export PDF" : `Export digest #${sel} as PDF`}</Button>} />

      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader title="Export" sub={sched ? `A new digest is saved ${sched.spec}` : undefined} />
            <div className="space-y-2 px-5 pb-5 text-[12.5px]">
              <div className="flex items-center justify-between rounded-lg px-3 py-2">
                <span className="text-ink-2">AI-written brief</span>
                <span className={meta.analysis ? "text-good" : "text-ink-3"}>{meta.analysis ? ((meta as any).analysis_provider === "gemini" ? "Gemini" : "Claude") : "Template (add GEMINI_API_KEY)"}</span>
              </div>
              <div className="px-3 text-ink-3">Pick the live preview or a past digest, then export it as an A4 PDF.</div>
            </div>
          </Card>
          <Card className="overflow-hidden">
            <CardHeader title="History" />
            <div className="border-t border-line">
              <button onClick={() => setSel("live")} className={cx("flex w-full items-center gap-3 border-b border-line px-5 py-3 text-left", sel === "live" ? "bg-hover" : "hover:bg-hover/60")}>
                <span className="size-2 rounded-full bg-accent pulse-dot text-accent" />
                <div><div className="text-[13px] text-ink">Live preview</div><div className="text-[11.5px] text-ink-3">Built from current data</div></div>
              </button>
              {data?.length ? data.map((d) => (
                <button key={d.id} onClick={() => setSel(d.id)} className={cx("block w-full border-b border-line px-5 py-3 text-left last:border-0", sel === d.id ? "bg-hover" : "hover:bg-hover/60")}>
                  <div className="line-clamp-1 text-[13px] text-ink">{d.headline}</div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11.5px] text-ink-3">
                    <span>{day(d.period_start)}–{day(d.period_end)}</span>
                    <span className="ml-auto">{ago(d.created_at)}</span>
                  </div>
                </button>
              )) : <Empty title="No digests yet" />}
            </div>
          </Card>
        </div>

        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <div className="text-[13px] text-ink">{sel === "live" ? "Live preview" : `Digest #${sel}`}</div>
            <Segmented value={device} onChange={setDevice} options={[{ value: "desktop", label: <Monitor size={13} /> }, { value: "mobile", label: <Smartphone size={13} /> }]} />
          </div>
          <div className="grid place-items-center bg-sunken p-4 sm:p-6">
            <iframe key={src} title="Digest preview" src={src}
              className="h-[820px] rounded-xl bg-white shadow-2xl ring-1 ring-line transition-all duration-300"
              style={{ width: device === "mobile" ? 390 : "100%", maxWidth: 760 }} />
          </div>
        </Card>
      </div>
    </div>
  );
}
