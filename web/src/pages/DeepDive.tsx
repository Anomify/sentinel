import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import { ArrowRight, Check, Copy, Download, Loader2, RefreshCw, Search } from "lucide-react";
import { api, invalidate, useApi } from "../lib/api";
import type { DeepDive as DD, Finding } from "../lib/types";
import { ago } from "../lib/format";
import { Button, Card, Confidence, cx, Empty, EntityDot, EvidenceList, fade, Monogram, PageHeader, Skeleton, Thumb, useEntity, useMeta } from "../components/ui";
import { useToast } from "../components/shell";

const STEPS = ["dns", "subdomains", "stack", "pages", "feeds", "radar", "product", "social", "hiring", "money", "ads", "deepdive"];
const STEP_LABEL: Record<string, string> = { dns: "DNS & email", subdomains: "Certificates & subdomains", stack: "Stack & tag manager", pages: "Pages & positioning",
  feeds: "Content", radar: "Pre-launch radar", product: "Product launches", social: "Social media", hiring: "Hiring", money: "Partners & money", ads: "Ads", deepdive: "Writing the deep dive" };
type Scan = { step: string | null; label?: string; index?: number; total?: number; done?: boolean; finished?: string };

/* ── list + "analyse a domain" ──────────────────────────────────────────────── */
export function DeepDives() {
  const meta = useMeta();
  const [sp] = useSearchParams();
  const [domain, setDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const toast = useToast();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!domain.trim()) return;
    setBusy(true);
    try {
      const r = await api<{ id: string }>("/api/targets", { method: "POST", body: JSON.stringify({ domain }) });
      invalidate();
      nav(`/deep-dives/${r.id}`);
    } catch (err) {
      toast({ title: "Couldn't start analysis", body: String((err as Error).message), tone: "err" });
    } finally {
      setBusy(false);
    }
  };
  const comps = meta.entities.filter((e) => !e.is_brand);
  return (
    <div>
      <PageHeader eyebrow="Intelligence layer" title="Deep dives" sub="Enter a domain. Sentinel runs every public-source method, stack, tracking, DNS, certificates, staging, hiring, partners, ads, positioning, and writes the teardown, with a recommended response for each finding. It stays current on every scan." />
      <motion.form {...fade} onSubmit={submit} className="card mb-8 flex items-center gap-3 p-2 pl-5">
        <Search size={16} strokeWidth={1.6} className="text-ink-3" />
        <input autoFocus={sp.get("new") === "1"} value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="competitor.com"
          className="h-11 flex-1 bg-transparent text-[17px] tracking-[-0.01em] text-ink outline-none placeholder:text-ink-3" />
        <Button variant="primary" type="submit" disabled={busy || !domain.trim()}>{busy ? <Loader2 size={14} className="animate-spin" /> : null}Analyse<ArrowRight size={14} /></Button>
      </motion.form>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {comps.map((c, i) => <DiveCard key={c.id} id={c.id} i={i} />)}
      </div>
    </div>
  );
}

function DiveCard({ id, i }: { id: string; i: number }) {
  const e = useEntity(id)!;
  const { data } = useApi<any>(`/api/competitors/${id}`);
  const facts = data ? Object.values(data.modules as Record<string, number>).reduce((a, b) => a + b, 0) : null;
  return (
    <motion.div {...fade} transition={{ ...fade.transition, delay: i * 0.03 }}>
      <Link to={`/deep-dives/${id}`} className="card group block p-6 transition-colors hover:border-line-strong">
        <div className="flex items-center gap-3">
          <Monogram id={id} size={36} />
          <div className="min-w-0">
            <div className="truncate text-[15px] text-ink">{e.name}</div>
            <div className="text-[12px] text-ink-3">{e.domains[0]}</div>
          </div>
          <ArrowRight size={15} className="ml-auto text-ink-3 transition-transform group-hover:translate-x-0.5" />
        </div>
        <div className="mt-6 flex items-end justify-between text-[12px] text-ink-3">
          <div><div className="text-[22px] leading-none tracking-[-0.02em] text-ink tnum">{facts ?? "-"}</div><div className="mt-1.5">facts on file</div></div>
          <div className="text-right">{data?.report_at ? `Updated ${ago(data.report_at)}` : data?.scan?.step && !data.scan.done ? "Scanning…" : "Not yet generated"}</div>
        </div>
      </Link>
    </motion.div>
  );
}

/* ── the report ─────────────────────────────────────────────────────────────── */
export function DeepDive() {
  const { id = "" } = useParams();
  const e = useEntity(id);
  const toast = useToast();
  const { data: scan } = useApi<Scan>(`/api/scan/${id}`, { poll: 2000 });
  const scanning = !!scan?.step && !scan.done;
  const { data, reload } = useApi<DD>(scanning ? null : `/api/deepdive/${id}`);
  const [active, setActive] = useState<string>("");
  useEffect(() => { if (scan?.done) { invalidate(); reload(); } }, [scan?.done]); // eslint-disable-line

  const regenerate = async () => {
    await api(`/api/scan/${id}`, { method: "POST" });
    toast({ title: "Full rescan started", body: "Every module runs again, then the deep dive is rewritten.", tone: "info" });
    invalidate();
  };
  const copy = async () => {
    const md = await api<string>(`/api/deepdive/${id}/markdown`);
    try { await navigator.clipboard.writeText(md); toast({ title: "Copied as Markdown" }); } catch { toast({ title: "Copy failed", tone: "err" }); }
  };
  const download = async () => {
    const md = await api<string>(`/api/deepdive/${id}/markdown`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    a.download = `${id}-deep-dive.md`;
    a.click();
  };
  if (!e) return <Empty title="Unknown competitor" />;
  return (
    <div>
      <motion.div {...fade} className="mb-10">
        <div className="eyebrow mb-4"><Link to="/competitors" className="hover:text-ink">Competitors</Link> / {e.domains[0]}</div>
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div className="flex items-center gap-4">
            <Monogram id={id} size={52} />
            <div>
              <h1 className="text-[38px] leading-none tracking-[-0.03em] text-ink">{e.name}</h1>
              <div className="mt-2.5 text-[13px] text-ink-3">{data ? `Generated ${ago(data.generated_at)} · passive public sources only` : "-"}</div>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={copy} disabled={!data}><Copy size={13} />Copy</Button>
            <Button variant="outline" size="sm" onClick={download} disabled={!data}><Download size={13} />Markdown</Button>
            <Button variant="primary" size="sm" onClick={regenerate} disabled={scanning}><RefreshCw size={13} className={scanning ? "animate-spin" : ""} />Rescan</Button>
          </div>
        </div>
      </motion.div>

      {scanning && <ScanProgress scan={scan!} />}
      {!scanning && !data && <Skeleton className="h-[480px] rounded-2xl" />}
      {!scanning && data && (
        <>
          <Card className="mb-10 grid grid-cols-2 divide-line sm:grid-cols-3 lg:grid-cols-6 lg:divide-x">
            {data.summary.map((s) => (
              <div key={s.label} className="px-5 py-4">
                <div className="eyebrow">{s.label}</div>
                <div className="mt-1.5 truncate text-[17px] tracking-[-0.01em] text-ink">{s.value}</div>
              </div>
            ))}
          </Card>
          <div className="grid gap-12 lg:grid-cols-[200px_1fr]">
            <nav className="hidden lg:block">
              <div className="sticky top-24 space-y-0.5">
                {data.sections.map((s) => (
                  <a key={s.id} href={`#${s.id}`} onClick={() => setActive(s.id)}
                    className={cx("flex items-center justify-between rounded-lg px-3 py-1.5 text-[13px] transition-colors", active === s.id ? "bg-elev text-ink ring-1 ring-line" : "text-ink-3 hover:text-ink")}>
                    {s.title}<span className="text-[11px] tnum">{s.findings.length}</span>
                  </a>
                ))}
                <div className="mt-6 space-y-1.5 px-3 text-[11.5px] text-ink-3">
                  {(["confirmed", "likely", "inferred"] as const).map((c) => <div key={c} className="flex items-center justify-between"><Confidence c={c} /><span className="tnum">{data.counts[c] ?? 0}</span></div>)}
                </div>
              </div>
            </nav>
            <article className="min-w-0 max-w-[820px] space-y-14">
              {data.sections.map((s) => (
                <section key={s.id} id={s.id} className="scroll-mt-24">
                  <h2 className="mb-6 border-b border-line pb-3 text-[22px] tracking-[-0.02em] text-ink">{s.title}</h2>
                  <div className="space-y-8">{s.findings.map((f) => <FindingBlock key={f.id} f={f} asOf={data.profile_as_of} />)}</div>
                </section>
              ))}
            </article>
          </div>
        </>
      )}
    </div>
  );
}

/** "Vs. us" depends on what Sentinel knows about Hyperfence: say who wrote it and how current that knowledge is. */
function vsUsSource(by: string | undefined, asOf: string | null | undefined) {
  const who = by === "claude" ? "AI suggestion (Claude)" : by === "gemini" ? "AI suggestion (Gemini)" : by ? "AI suggestion" : "Rule of thumb";
  if (!asOf) return { who, note: "Hyperfence profile undated", stale: true };
  const days = Math.floor((Date.now() - new Date(asOf).getTime()) / 86400000);
  return { who, note: `from the Hyperfence profile as of ${asOf}${days > 90 ? ", now out of date" : ""}`, stale: days > 90 };
}

function FindingBlock({ f, asOf }: { f: Finding; asOf?: string | null }) {
  const [open, setOpen] = useState(false);
  const shot = f.data?.screenshot;
  return (
    <div className="group">
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-[16.5px] leading-snug tracking-[-0.01em] text-ink">{f.title}</h3>
        <div className="shrink-0 pt-1"><Confidence c={f.confidence} /></div>
      </div>
      {f.detail && <p className="mt-2 text-[14px] leading-relaxed text-ink-2">{f.detail}</p>}
      {shot && <Thumb name={shot} className="mt-4 aspect-[16/9] w-full max-w-md" />}
      {f.vs_us && (
        <div className="mt-4 border-l-2 border-accent pl-4">
          <div className="text-[11.5px] text-accent-ink">Vs. us · {vsUsSource(f.vs_us_by, asOf).who}
            <span className={vsUsSource(f.vs_us_by, asOf).stale ? "text-high" : "text-ink-3"}> · {vsUsSource(f.vs_us_by, asOf).note}</span></div>
          <p className="mt-1 text-[14px] leading-relaxed text-ink">{f.vs_us}</p>
        </div>
      )}
      {f.evidence.length > 0 && (
        <div className="mt-3">
          <button onClick={() => setOpen((o) => !o)} className="text-[11.5px] text-ink-3 hover:text-ink">
            {open ? "Hide" : "Show"} evidence ({f.evidence.length}){f.first_seen ? ` · first seen ${new Date(f.first_seen).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}` : ""}
          </button>
          {open && <div className="mt-2 rounded-xl bg-sunken/70 p-3"><EvidenceList items={f.evidence} /></div>}
        </div>
      )}
    </div>
  );
}

function ScanProgress({ scan }: { scan: Scan }) {
  const idx = scan.index ?? 0;
  const pctDone = Math.round((idx / (scan.total || STEPS.length)) * 100);
  const steps = useMemo(() => STEPS, []);
  return (
    <motion.div {...fade} className="card mx-auto max-w-xl p-8">
      <div className="flex items-center gap-3">
        <Loader2 size={16} className="animate-spin text-ink-3" />
        <div className="text-[15px] text-ink">Building the deep dive…</div>
        <div className="ml-auto text-[13px] text-ink-3 tnum">{pctDone}%</div>
      </div>
      <div className="mt-5 h-1 overflow-hidden rounded-full bg-sunken">
        <motion.div className="h-full rounded-full bg-ink" animate={{ width: `${Math.max(4, pctDone)}%` }} transition={{ duration: 0.6 }} />
      </div>
      <ol className="mt-6 space-y-2">
        {steps.map((s, i) => (
          <li key={s} className={cx("flex items-center gap-3 text-[13px]", i < idx ? "text-ink-2" : i === idx ? "text-ink" : "text-ink-3")}>
            <span className="grid size-4 place-items-center">
              {i < idx ? <Check size={13} className="text-good" /> : i === idx ? <EntityDot color="var(--ink)" size={6} /> : <EntityDot color="var(--line-strong)" size={5} />}
            </span>
            {STEP_LABEL[s]}
          </li>
        ))}
      </ol>
      <p className="mt-6 text-[12px] leading-relaxed text-ink-3">Passive and public only: robots.txt is respected, hosts are rate-limited, and internal hostnames are recorded without being contacted. A full scan typically takes 3–8 minutes.</p>
    </motion.div>
  );
}
