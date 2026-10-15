import { useState } from "react";
import { CheckCircle2, Circle, Eye, Hash, Mail, Monitor, Send, Smartphone } from "lucide-react";
import { getToken, useApi } from "../lib/api";
import { ago, day } from "../lib/format";
import { Button, Card, CardHeader, cx, Empty, PageHeader, Segmented, useMeta } from "../components/ui";
import { useJobs } from "../components/shell";

interface DigestRow { id: number; created_at: string; period_start: string; period_end: string; headline: string; delivered: Record<string, string> }

export default function Digest() {
  const meta = useMeta();
  const { data } = useApi<DigestRow[]>("/api/digests");
  const [sel, setSel] = useState<number | "live">("live");
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const { start, running } = useJobs();
  const t = getToken();
  const src = sel === "live" ? `/api/digests/preview${t ? `?token=${t}` : ""}` : `/api/digests/${sel}/html${t ? `?token=${t}` : ""}`;
  const anyChannel = meta.channels.slack || meta.channels.email;
  const sched = meta.schedule.find((s) => s.job === "digest");

  return (
    <div>
      <PageHeader title="Weekly digest" sub="The brief that lands in your inbox and Slack, written for a PMM heading into launch: what moved, why it matters, what to do."
        right={<>
          <Button variant="outline" onClick={() => start("digest", { deliver: false })} disabled={running.includes("digest")}><Eye size={14} />Generate preview</Button>
          <Button variant="primary" onClick={() => start("digest")} disabled={running.includes("digest") || !anyChannel}><Send size={14} />Send now</Button>
        </>} />

      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader title="Delivery" sub={sched ? `Scheduled ${sched.spec}` : undefined} />
            <div className="space-y-2 px-5 pb-5">
              <Channel icon={<Hash size={14} />} label="Slack" on={meta.channels.slack} hint="SLACK_WEBHOOK_URL" />
              <Channel icon={<Mail size={14} />} label="Email" on={meta.channels.email} hint="SMTP_HOST + DIGEST_TO" />
              <div className="flex items-center justify-between rounded-lg px-3 py-2 text-[12.5px]">
                <span className="text-ink-2">AI-written brief</span>
                <span className={meta.analysis ? "text-good" : "text-ink-3"}>{meta.analysis ? ((meta as any).analysis_provider === "gemini" ? "Gemini" : "Claude") : "Template (add GEMINI_API_KEY)"}</span>
              </div>
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
                    {Object.entries(d.delivered || {}).map(([k, v]) => <span key={k} className={v === "sent" ? "text-good" : "text-crit"}>{k} {v === "sent" ? "✓" : "✕"}</span>)}
                    {!Object.keys(d.delivered || {}).length && <span>not sent</span>}
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

function Channel({ icon, label, on, hint }: { icon: React.ReactNode; label: string; on: boolean; hint: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg bg-sunken px-3 py-2.5 ring-1 ring-inset ring-line">
      <span className="text-ink-2">{icon}</span>
      <div className="flex-1">
        <div className="text-[13px] text-ink">{label}</div>
        {!on && <div className="font-mono text-[10.5px] text-ink-3">set {hint}</div>}
      </div>
      {on ? <CheckCircle2 size={15} className="text-good" /> : <Circle size={15} className="text-ink-3" />}
    </div>
  );
}
