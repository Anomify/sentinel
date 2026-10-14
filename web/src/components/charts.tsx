import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import type { Entity } from "../lib/types";
import { cx, EntityDot } from "./ui";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const niceMax = (v: number) => {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
};

/** Path for a bar with 4px rounded top corners anchored to the baseline. */
function barPath(x: number, y: number, w: number, h: number, r = 4) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

export function Tooltip({ x, y, children, containerW }: { x: number; y: number; children: ReactNode; containerW: number }) {
  const left = Math.min(Math.max(x, 90), containerW - 90);
  return (
    <div className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded-lg bg-elev/95 backdrop-blur px-3 py-2 text-[12px] shadow-xl ring-1 ring-line-strong min-w-36"
      style={{ left, top: y - 10 }}>
      {children}
    </div>
  );
}

export function Legend({ series, active, onToggle }: { series: Entity[]; active?: Set<string>; onToggle?: (id: string) => void }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5">
      {series.map((s) => (
        <button key={s.id} onClick={() => onToggle?.(s.id)} disabled={!onToggle}
          className={cx("inline-flex items-center gap-1.5 text-[12px] transition-opacity", active && !active.has(s.id) ? "opacity-35" : "text-ink-2")}>
          <EntityDot color={s.color} size={8} />
          <span className="text-ink-2">{s.is_brand ? `${s.name} (you)` : s.name}</span>
        </button>
      ))}
    </div>
  );
}

/* ── Stacked activity bars ──────────────────────────────────────────────────── */
export function StackedBars({ data, series, height = 180, fmtDate }: {
  data: ({ date: string } & Record<string, any>)[]; series: Entity[]; height?: number; fmtDate: (d: string) => string;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [on, setOn] = useState<Set<string>>(() => new Set(series.map((s) => s.id)));
  const vis = series.filter((s) => on.has(s.id));
  const pad = { l: 28, r: 4, t: 8, b: 22 };
  const totals = data.map((d) => vis.reduce((a, s) => a + (Number(d[s.id]) || 0), 0));
  const max = niceMax(Math.max(1, ...totals));
  const iw = Math.max(0, W - pad.l - pad.r), ih = height - pad.t - pad.b;
  const step = data.length ? iw / data.length : 0;
  const bw = Math.max(2, Math.min(18, step * 0.62));
  const y = (v: number) => pad.t + ih - (v / max) * ih;
  const ticks = [0, max / 2, max];
  const toggle = (id: string) => setOn((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n.size ? n : p; });

  return (
    <div>
      <div ref={ref} className="relative" style={{ height }} onMouseLeave={() => setHover(null)}>
        {W > 0 && (
          <svg width={W} height={height} role="img" aria-label="Competitor activity by day">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeDasharray={t ? "2 4" : undefined} />
                <text x={pad.l - 8} y={y(t) + 3.5} textAnchor="end" className="fill-ink-3 text-[10px] tnum">{Math.round(t)}</text>
              </g>
            ))}
            {data.map((d, i) => {
              let acc = 0;
              const cx0 = pad.l + i * step + (step - bw) / 2;
              const segs = vis.map((s) => ({ s, v: Number(d[s.id]) || 0 })).filter((x) => x.v > 0);
              return (
                <g key={d.date} opacity={hover == null || hover === i ? 1 : 0.4} style={{ transition: "opacity .15s" }}>
                  {segs.map(({ s, v }, k) => {
                    const y0 = y(acc), y1 = y(acc + v);
                    acc += v;
                    const top = k === segs.length - 1;
                    const h = Math.max(0, y0 - y1 - (k ? 2 : 0)); // 2px surface gap between segments
                    return top
                      ? <motion.path key={s.id} d={barPath(cx0, y1, bw, h)} fill={s.color} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.008 }} />
                      : <motion.rect key={s.id} x={cx0} y={y1} width={bw} height={h} fill={s.color} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.008 }} />;
                  })}
                  {/* hit target wider than the mark */}
                  <rect x={pad.l + i * step} y={pad.t} width={step} height={ih} fill="transparent" onMouseEnter={() => setHover(i)} />
                </g>
              );
            })}
            {data.map((d, i) => (i % Math.ceil(data.length / 7) === 0 || i === data.length - 1) && (
              <text key={d.date} x={pad.l + i * step + step / 2} y={height - 6} textAnchor="middle" className="fill-ink-3 text-[10px]">{fmtDate(d.date)}</text>
            ))}
          </svg>
        )}
        {hover != null && data[hover] && (
          <Tooltip x={pad.l + hover * step + step / 2} y={y(totals[hover])} containerW={W}>
            <div className=" text-ink mb-1">{fmtDate(data[hover].date)}</div>
            {vis.filter((s) => Number(data[hover][s.id]) > 0).map((s) => (
              <div key={s.id} className="flex items-center justify-between gap-4 text-ink-2">
                <span className="inline-flex items-center gap-1.5"><EntityDot color={s.color} size={7} />{s.name}</span>
                <span className="tnum text-ink">{Number(data[hover][s.id]).toFixed(1).replace(/\.0$/, "")}</span>
              </div>
            ))}
            {totals[hover] === 0 && <div className="text-ink-3">No activity</div>}
          </Tooltip>
        )}
      </div>
      <div className="mt-3"><Legend series={series} active={on} onToggle={toggle} /></div>
    </div>
  );
}

/* ── Multi-series line chart with crosshair ─────────────────────────────────── */
export function LineChart({ data, series, height = 220, emphasize, fmtX, fmtY = (v) => `${Math.round(v * 100)}%`, yMax }: {
  data: ({ date: string } & Record<string, any>)[]; series: Entity[]; height?: number; emphasize?: string;
  fmtX: (d: string) => string; fmtY?: (v: number) => string; yMax?: number;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [on, setOn] = useState<Set<string>>(() => new Set(series.map((s) => s.id)));
  const pad = { l: 36, r: 12, t: 12, b: 22 };
  const iw = Math.max(0, W - pad.l - pad.r), ih = height - pad.t - pad.b;
  const max = yMax ?? niceMax(Math.max(0.01, ...data.flatMap((d) => series.map((s) => Number(d[s.id]) || 0))));
  const x = (i: number) => pad.l + (data.length > 1 ? (i / (data.length - 1)) * iw : iw / 2);
  const y = (v: number) => pad.t + ih - (v / max) * ih;
  const vis = series.filter((s) => on.has(s.id));
  const toggle = (id: string) => setOn((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n.size ? n : p; });

  const paths = useMemo(() => vis.map((s) => ({
    s, d: data.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(Number(p[s.id]) || 0)}`).join(""),
  })), [data, vis, W, max]); // eslint-disable-line

  const onMove = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const px = e.clientX - r.left;
    if (data.length < 1) return;
    const i = Math.round(((px - pad.l) / Math.max(1, iw)) * (data.length - 1));
    setHover(Math.max(0, Math.min(data.length - 1, i)));
  };

  return (
    <div>
      <div ref={ref} className="relative" style={{ height }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {W > 0 && (
          <svg width={W} height={height} role="img" aria-label="Share of AI answers over time">
            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <g key={f}>
                <line x1={pad.l} x2={W - pad.r} y1={y(max * f)} y2={y(max * f)} stroke="var(--line)" strokeDasharray={f ? "2 4" : undefined} />
                <text x={pad.l - 8} y={y(max * f) + 3.5} textAnchor="end" className="fill-ink-3 text-[10px] tnum">{fmtY(max * f)}</text>
              </g>
            ))}
            {data.map((d, i) => (i % Math.ceil(data.length / 6) === 0 || i === data.length - 1) && (
              <text key={d.date + i} x={x(i)} y={height - 6} textAnchor="middle" className="fill-ink-3 text-[10px]">{fmtX(d.date)}</text>
            ))}
            {hover != null && <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="var(--line-strong)" />}
            {paths.map(({ s, d }) => {
              const em = emphasize === s.id;
              return (
                <motion.path key={s.id} d={d} fill="none" stroke={s.color} strokeWidth={em ? 2.75 : 2}
                  strokeLinejoin="round" strokeLinecap="round"
                  opacity={emphasize && !em ? 0.55 : 1}
                  initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
              );
            })}
            {emphasize && on.has(emphasize) && data.length > 0 && (() => {
              const s = series.find((z) => z.id === emphasize)!;
              const i = data.length - 1, v = Number(data[i][s.id]) || 0;
              return <g>
                <circle cx={x(i)} cy={y(v)} r={5} fill={s.color} stroke="var(--bg-elev)" strokeWidth={2} />
              </g>;
            })()}
            {hover != null && vis.map((s) => (
              <circle key={s.id} cx={x(hover)} cy={y(Number(data[hover][s.id]) || 0)} r={4.5} fill={s.color} stroke="var(--bg-elev)" strokeWidth={2} />
            ))}
          </svg>
        )}
        {hover != null && data[hover] && (
          <Tooltip x={x(hover)} y={pad.t + 8} containerW={W}>
            <div className=" text-ink mb-1">{fmtX(data[hover].date)}</div>
            {[...vis].sort((a, b) => (Number(data[hover][b.id]) || 0) - (Number(data[hover][a.id]) || 0)).map((s) => (
              <div key={s.id} className={cx("flex items-center justify-between gap-4", s.id === emphasize ? "text-ink" : "text-ink-2")}>
                <span className="inline-flex items-center gap-1.5"><EntityDot color={s.color} size={7} />{s.is_brand ? `${s.name} (you)` : s.name}</span>
                <span className="tnum text-ink">{fmtY(Number(data[hover][s.id]) || 0)}</span>
              </div>
            ))}
          </Tooltip>
        )}
      </div>
      <div className="mt-3"><Legend series={series} active={on} onToggle={toggle} /></div>
    </div>
  );
}

/* ── Sparkline ──────────────────────────────────────────────────────────────── */
export function Sparkline({ values, color, width = 96, height = 28 }: { values: number[]; color: string; width?: number; height?: number }) {
  if (!values.length) return null;
  const max = Math.max(1, ...values);
  const step = width / Math.max(1, values.length);
  const bw = Math.max(1.5, step - 1.5);
  return (
    <svg width={width} height={height} aria-hidden>
      {values.map((v, i) => {
        const h = v ? Math.max(2, (v / max) * (height - 2)) : 1;
        return <rect key={i} x={i * step} y={height - h} width={bw} height={h} rx={1} fill={v ? color : "var(--line-strong)"} opacity={v ? 0.9 : 1} />;
      })}
    </svg>
  );
}

/* ── Horizontal bar list (share of voice etc.) ──────────────────────────────── */
export function BarList({ rows, fmt = (v) => `${Math.round(v * 100)}%`, max: maxIn }: {
  rows: { id: string; label: ReactNode; value: number; color: string; sub?: ReactNode; strong?: boolean }[];
  fmt?: (v: number) => string; max?: number;
}) {
  const max = maxIn ?? Math.max(0.0001, ...rows.map((r) => r.value));
  return (
    <div className="space-y-2.5">
      {rows.map((r, i) => (
        <div key={r.id} className="group">
          <div className="flex items-baseline justify-between gap-3 text-[12.5px] mb-1">
            <span className={cx("truncate", r.strong ? "text-ink" : "text-ink-2")}>{r.label}</span>
            <span className="flex items-baseline gap-2 shrink-0">
              {r.sub && <span className="text-[11px] text-ink-3">{r.sub}</span>}
              <span className="tnum text-ink">{fmt(r.value)}</span>
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-sunken overflow-hidden ring-1 ring-inset ring-line">
            <motion.div className="h-full rounded-full" style={{ background: r.color }}
              initial={{ width: 0 }} animate={{ width: `${Math.max(1, (r.value / max) * 100)}%` }}
              transition={{ duration: 0.7, delay: i * 0.04, ease: [0.22, 1, 0.36, 1] }} />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Radial gauge for a single headline percentage ──────────────────────────── */
export function Ring({ value, size = 56, stroke = 5, color = "var(--accent)" }: { value: number; size?: number; stroke?: number; color?: string }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} className="-rotate-90" aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line-strong)" strokeWidth={stroke} />
      <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
        strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - Math.min(1, value)) }}
        transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }} />
    </svg>
  );
}
