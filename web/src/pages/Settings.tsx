import { CheckCircle2, Circle, Clock, ExternalLink, Rss } from "lucide-react";
import { useState } from "react";
import { api, invalidate, setWorkspace, useApi } from "../lib/api";
import type { Run } from "../lib/types";
import { ago, host, path, until } from "../lib/format";
import { Button, Card, CardHeader, cx, EntityDot, PageHeader, useMeta } from "../components/ui";
import { useToast } from "../components/shell";

const ENGINE_LABEL: Record<string, string> = { perplexity: "Perplexity", openai: "ChatGPT (OpenAI)", gemini: "Gemini (Google)", google_aio: "Google AI Overviews (SerpAPI)", claude: "Claude (Anthropic)" };
const ENV: Record<string, string> = { perplexity: "PERPLEXITY_API_KEY", openai: "OPENAI_API_KEY", gemini: "GEMINI_API_KEY", google_aio: "SERPAPI_API_KEY", claude: "ANTHROPIC_API_KEY" };

export default function Settings() {
  const meta = useMeta();
  const { data: runs } = useApi<{ runs: Run[] }>("/api/runs?limit=25");
  return (
    <div>
      <PageHeader title="Settings" sub={<>Configuration lives in <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px] ring-1 ring-line">config/*.yaml</code>, version-controlled and reviewable. Secrets come from environment variables.</>} />

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Schedule" sub="config/settings.yaml → schedule" right={<Clock size={14} className="text-ink-3" />} />
          <div className="divide-y divide-line border-t border-line">
            {meta.schedule.map((s) => (
              <div key={s.job} className="flex items-center gap-4 px-5 py-3 text-[13px]">
                <span className="w-44 text-ink">{(s as any).label ?? s.job}</span>
                <code className="font-mono text-[12px] text-ink-2">{s.spec}</code>
                <span className="ml-auto text-[12px] text-ink-3">last {ago(s.last)}</span>
                <span className={cx("w-20 text-right text-[12px]", s.running ? "text-accent-ink" : "text-ink-2")}>{s.running ? "running" : `next ${until(s.next)}`}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title="Integrations" sub="Set keys in .env; restart to apply" />
          <div className="divide-y divide-line border-t border-line">
            {meta.engines.map((e) => <Row key={e.id} label={ENGINE_LABEL[e.id] ?? e.id} detail={`${e.model}${e.enabled ? "" : " · disabled in questions.yaml"}`} on={e.enabled && e.has_key} env={ENV[e.id]} />)}
            <Row label="AI analysis" detail={`So-what, Vs. us, weekly brief, accuracy grading${(meta as any).analysis_provider ? ` · using ${(meta as any).analysis_provider === "gemini" ? "Gemini" : "Claude"}` : ""}`} on={meta.analysis} env="GEMINI_API_KEY or ANTHROPIC_API_KEY" />
            <Row label="Slack digest" detail="Incoming webhook" on={meta.channels.slack} env="SLACK_WEBHOOK_URL" />
            <Row label="Email digest" detail={`To ${((meta as any).digest_to ?? []).join(", ") || "nobody yet"} · Google Workspace or any SMTP`} on={meta.channels.email} env="SMTP_USER, SMTP_PASS" />
            <Row label="Google ads library" detail="BigQuery public dataset (official)" on={false} env="GOOGLE_APPLICATION_CREDENTIALS" />
            <Row label="Meta ads library" detail="Ad Library API (official)" on={false} env="META_ADS_TOKEN" />
          </div>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader title="Watchlist" sub="config/watchlist.yaml" />
          <div className="divide-y divide-line border-t border-line">
            {meta.entities.filter((e) => !e.is_brand).map((e) => (
              <div key={e.id} className="grid gap-3 px-5 py-4 md:grid-cols-[200px_1fr_1fr]">
                <div className="flex items-start gap-2">
                  <EntityDot color={e.color} size={9} />
                  <div className="-mt-0.5"><div className="text-[13px] text-ink">{e.name}</div><div className="text-[11.5px] capitalize text-ink-3">{e.tier}</div></div>
                </div>
                <div className="space-y-1">
                  {e.pages.map((p) => (
                    <a key={p.url} href={p.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-[12px] text-ink-2 hover:text-ink">
                      <span className="w-16 shrink-0 text-[10.5px] uppercase tracking-wide text-ink-3">{p.kind}</span>
                      <span className="truncate">{host(p.url)}{path(p.url)}</span><ExternalLink size={10} className="shrink-0 opacity-50" />
                    </a>
                  ))}
                </div>
                <div className="space-y-1">
                  {e.feeds.map((f) => (
                    <div key={f.url} className="flex items-center gap-2 text-[12px] text-ink-2">
                      <Rss size={11} className="shrink-0 text-ink-3" /><span className="w-12 shrink-0 text-[10.5px] uppercase tracking-wide text-ink-3">{f.type}</span>
                      <span className="truncate">{host(f.url)}{path(f.url)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Workspaces />
        <Card>
          <CardHeader title="Target questions" sub={`config/questions.yaml · ${meta.questions.length} questions`} />
          <ol className="max-h-[420px] divide-y divide-line overflow-y-auto border-t border-line">
            {meta.questions.map((q, i) => (
              <li key={q.id} className="flex gap-3 px-5 py-2.5 text-[12.5px]">
                <span className="w-5 text-right text-ink-3 tnum">{i + 1}</span>
                <span className="flex-1 text-ink-2">{q.text}</span>
                <span className="text-[11px] text-ink-3">{q.category}</span>
              </li>
            ))}
          </ol>
        </Card>

        <Card>
          <CardHeader title="Run log" sub="Most recent collection jobs" />
          <div className="max-h-[420px] divide-y divide-line overflow-y-auto border-t border-line">
            {(runs?.runs ?? []).map((r) => (
              <div key={r.id} className="flex items-center gap-3 px-5 py-2.5 text-[12.5px]">
                <span className={cx("size-1.5 rounded-full", r.status === "ok" ? "bg-good" : r.status === "running" ? "bg-accent" : "bg-crit")} />
                <span className="w-14 capitalize text-ink">{r.job}</span>
                <span className="flex-1 truncate text-ink-3">{r.error ?? summarize(r.stats)}</span>
                <span className="text-[11.5px] text-ink-3">{ago(r.started_at)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function Workspaces() {
  const meta = useMeta();
  const toast = useToast();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [token, setTok] = useState<string | null>(null);
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<{ token: string }>("/api/workspaces", { method: "POST", body: JSON.stringify({ slug, name }) });
      setTok(r.token); setSlug(""); setName(""); invalidate();
    } catch (err) { toast({ title: "Couldn't create workspace", body: String((err as Error).message), tone: "err" }); }
  };
  return (
    <Card className="xl:col-span-2">
      <CardHeader title="Workspaces" sub={`Each workspace has its own watchlist, questions and database (${meta.backend}). Access is per-workspace token.`} />
      <div className="grid gap-6 border-t border-line p-6 lg:grid-cols-2">
        <div className="space-y-1">
          {meta.workspaces.map((w) => (
            <button key={w.slug} onClick={() => setWorkspace(w.slug)} className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-[13px] hover:bg-hover">
              <span className="text-ink">{w.name}</span><span className="text-ink-3">{w.slug === meta.workspace ? "current" : w.slug}</span>
            </button>
          ))}
        </div>
        <form onSubmit={create} className="space-y-2">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Workspace name (e.g. client or product line)" className="h-10 w-full rounded-full bg-sunken px-4 text-[13px] outline-none" />
          <div className="flex gap-2">
            <input value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))} placeholder="slug" className="h-10 flex-1 rounded-full bg-sunken px-4 text-[13px] outline-none" />
            <Button variant="primary" type="submit" disabled={!slug || !name}>Create</Button>
          </div>
          {token && <div className="rounded-xl bg-accent-soft p-3 text-[12px] text-ink">Access token (shown once): <code className="break-all font-mono">{token}</code></div>}
        </form>
      </div>
    </Card>
  );
}

function summarize(s: any): string {
  if (!s || typeof s !== "object") return "";
  return Object.entries(s).filter(([, v]) => typeof v !== "object").map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ");
}

function Row({ label, detail, on, env }: { label: string; detail: string; on: boolean; env: string }) {
  return (
    <div className="flex items-center gap-3 px-5 py-3">
      {on ? <CheckCircle2 size={15} className="text-good" /> : <Circle size={15} className="text-ink-3" />}
      <div className="flex-1"><div className="text-[13px] text-ink">{label}</div><div className="text-[11.5px] text-ink-3">{detail}</div></div>
      <code className={cx("rounded px-1.5 py-0.5 font-mono text-[10.5px] ring-1 ring-inset", on ? "text-good ring-good/25" : "text-ink-3 ring-line")}>{env}</code>
    </div>
  );
}
