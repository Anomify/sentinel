import { ShieldCheck } from "lucide-react";
import { useApi } from "../lib/api";
import { ago } from "../lib/format";
import { Card, CardHeader, cx, EntityDot, PageHeader, Skeleton, useMeta } from "../components/ui";

const STATUS: Record<string, { label: string; cls: string }> = {
  covered: { label: "Covered", cls: "bg-ink" },
  partial: { label: "Partial", cls: "border border-ink bg-[linear-gradient(90deg,var(--ink)_50%,transparent_50%)]" },
  "no data": { label: "Ran · nothing found", cls: "border border-ink-3" },
  "needs setup": { label: "Needs API key", cls: "border border-dashed border-ink-3" },
  "not run": { label: "Not run yet", cls: "bg-line-strong" },
};

export default function Coverage() {
  const meta = useMeta();
  const { data } = useApi<any>("/api/coverage");
  const { data: g } = useApi<any>("/api/guard?limit=120");
  return (
    <div>
      <PageHeader eyebrow="Method tracker" title="Coverage" sub="Which intelligence methods have produced evidence for each competitor — and the guardrails every collector runs under." />
      {!data ? <Skeleton className="h-96 rounded-2xl" /> : (
        <Card className="mb-5 overflow-x-auto">
          <table className="w-full min-w-[980px] text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left align-bottom text-ink-3">
                <th className="px-6 py-4">Method</th>
                <th className="px-3 py-4">Replaces</th>
                {data.rows.map((r: any) => (
                  <th key={r.competitor} className="px-3 py-4 text-center">
                    <div className="flex flex-col items-center gap-1.5"><EntityDot color={meta.entities.find((e) => e.id === r.competitor)?.color ?? "#999"} size={7} /><span className="max-w-[88px] truncate">{r.name.replace(/\s*\(.*\)/, "")}</span></div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.methods.map((m: any) => (
                <tr key={m.id} className="border-b border-line last:border-0">
                  <td className="px-6 py-3"><div className="text-ink">{m.label}</div><div className="text-[11.5px] text-ink-3">{m.source}</div></td>
                  <td className="px-3 py-3 text-ink-3">{m.replaces}</td>
                  {data.rows.map((r: any) => {
                    const c = r.cells[m.id];
                    const s = STATUS[c.status] ?? STATUS["not run"];
                    return (
                      <td key={r.competitor} className="px-3 py-3 text-center" title={`${s.label}${c.facts ? ` · ${c.facts} facts` : ""}${c.last ? ` · ${ago(c.last)}` : ""}${c.blocked ? ` · ${c.blocked} requests declined by guardrails` : ""}`}>
                        <div className="flex flex-col items-center gap-1">
                          <span className={cx("inline-block size-2.5 rounded-full", s.cls)} />
                          <span className="text-[10.5px] text-ink-3 tnum">{c.facts || ""}</span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex flex-wrap gap-5 border-t border-line px-6 py-3 text-[11.5px] text-ink-3">
            {Object.entries(STATUS).map(([k, v]) => <span key={k} className="inline-flex items-center gap-2"><span className={cx("inline-block size-2.5 rounded-full", v.cls)} />{v.label}</span>)}
          </div>
        </Card>
      )}
      <div className="grid gap-5 xl:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardHeader title="Guardrails" sub="Passive, public sources only — enforced in code, not just policy" right={<ShieldCheck size={16} strokeWidth={1.6} className="text-ink-3" />} />
          <div className="divide-y divide-line border-t border-line">
            {(g?.policy ?? meta.policy).map((p: any) => (
              <div key={p.title} className="px-6 py-3.5"><div className="text-[13.5px] text-ink">{p.title}</div><div className="mt-0.5 text-[12.5px] leading-relaxed text-ink-3">{p.detail}</div></div>
            ))}
          </div>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader title="Audit log" sub={g ? `${g.stats.allowed ?? 0} allowed · ${g.stats.blocked ?? 0} declined by policy` : "—"} />
          <div className="max-h-[520px] divide-y divide-line overflow-y-auto border-t border-line">
            {(g?.log ?? []).map((r: any) => (
              <div key={r.id} className="grid grid-cols-[64px_1fr_auto] items-center gap-3 px-6 py-2 text-[12px]">
                <span className={r.action === "blocked" ? "text-high" : "text-ink-3"}>{r.action === "blocked" ? "declined" : "fetched"}</span>
                <span className="truncate text-ink-2" title={r.url}>{r.host}<span className="text-ink-3"> · {r.reason}</span></span>
                <span className="text-ink-3 tnum">{ago(r.ts)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
