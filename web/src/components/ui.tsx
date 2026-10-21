import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowDownRight, ArrowUpRight, ExternalLink, Image as ImageIcon, Minus, X } from "lucide-react";
import type { Entity, Evidence, Meta, Severity } from "../lib/types";
import { ago, host } from "../lib/format";
import { authQuery } from "../lib/api";

/* ── meta context ───────────────────────────────────────────────────────────── */
export const MetaCtx = createContext<Meta | null>(null);
export const useMeta = () => useContext(MetaCtx)!;
export function useEntity(id: string): Entity | undefined {
  return useMeta()?.entities.find((e) => e.id === id);
}
/** Chart series order: competitors in watchlist order, brand last (validated palette order). */
export function useSeries(): Entity[] {
  const m = useMeta();
  return m ? [...m.entities.filter((e) => !e.is_brand), ...m.entities.filter((e) => e.is_brand)] : [];
}

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export const fade = {
  initial: { opacity: 0, y: 4 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.3, ease: [0.16, 1, 0.3, 1] as const },  // design-system easing: short, gentle, no bounce
};

export function Card({ children, className, ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("card", className)} {...rest}>{children}</div>;
}

export function CardHeader({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-4">
      <div className="min-w-0">
        <h3 className="text-[14px] text-ink">{title}</h3>
        {sub && <p className="mt-0.5 text-[12.5px] text-ink-3">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

export function PageHeader({ title, sub, right, eyebrow }: { title: ReactNode; sub?: ReactNode; right?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <motion.div {...fade} className="mb-8 flex flex-wrap items-end justify-between gap-5">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-3">{eyebrow}</div>}
        <h1 className="text-[28px] leading-[1.15] tracking-[-0.02em] text-ink">{title}</h1>
        {sub && <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-ink-2">{sub}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </motion.div>
  );
}

const SEV: Record<string, { label: string; dot: string; text: string }> = {
  // Red for what needs action, amber for what to look at; the rest stays neutral (accents are functional).
  critical: { label: "Critical", dot: "bg-red", text: "text-crit" },
  high: { label: "High", dot: "bg-amber", text: "text-high" },
  medium: { label: "Medium", dot: "bg-mauve-500", text: "text-ink-2" },
  low: { label: "Low", dot: "bg-mauve-400", text: "text-ink-3" },
  noise: { label: "Noise", dot: "bg-mauve-400", text: "text-ink-3" },
  info: { label: "Info", dot: "bg-mauve-400", text: "text-ink-3" },
};
export function SeverityBadge({ s }: { s: Severity | string; compact?: boolean }) {
  const v = SEV[s] ?? SEV.low;
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-[11.5px]", v.text)}>
      <span className={cx("size-1.5 rounded-full", v.dot)} />{v.label}
    </span>
  );
}
export const sevDot = (s: string) => (SEV[s] ?? SEV.low).dot;

const CONF: Record<string, { label: string; glyph: ReactNode; tip: string }> = {
  confirmed: { label: "Confirmed", glyph: <span className="size-2 rounded-full bg-ink" />, tip: "Directly observed in a public source" },
  likely: { label: "Likely", glyph: <span className="size-2 rounded-full border border-ink bg-[linear-gradient(90deg,var(--text)_50%,transparent_50%)]" />, tip: "Strong indirect evidence" },
  inferred: { label: "Inferred", glyph: <span className="size-2 rounded-full border border-ink-3" />, tip: "Derived by Sentinel from other signals" },
};
export function Confidence({ c }: { c?: string | null }) {
  const v = CONF[c || "confirmed"] ?? CONF.confirmed;
  return <span title={v.tip} className="inline-flex items-center gap-1.5 text-[11.5px] text-ink-3">{v.glyph}{v.label}</span>;
}

export function EntityDot({ color, size = 8, ring }: { color: string; size?: number; ring?: boolean }) {
  return <span className={cx("inline-block shrink-0 rounded-full", ring && "ring-2 ring-elev")} style={{ width: size, height: size, background: color }} />;
}

export function EntityTag({ id, className }: { id: string; className?: string }) {
  const e = useEntity(id);
  if (!e) return <span className="text-ink-3">{id}</span>;
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-[12.5px] text-ink", className)}>
      <EntityDot color={e.color} size={7} />{e.is_brand ? `${e.name} (you)` : e.tier === "self" ? `${e.name} (us)` : e.name}
    </span>
  );
}

export function Monogram({ id, size = 32 }: { id: string; size?: number }) {
  const e = useEntity(id);
  const name = e?.name ?? id;
  const initials = name.replace(/\(.*?\)/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return (
    <span className="relative inline-grid shrink-0 place-items-center rounded-[10px] font-semibold text-ink"
      style={{ width: size, height: size, fontSize: size * 0.34, background: `color-mix(in oklab, ${e?.color ?? "var(--mauve-500)"} 12%, transparent)`,
        boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${e?.color ?? "var(--mauve-500)"} 28%, transparent)` }}>
      {initials}
    </span>
  );
}

export function Chip({ children, active, onClick, className }: { children: ReactNode; active?: boolean; onClick?: () => void; className?: string }) {
  const C = onClick ? "button" : "span";
  return (
    <C onClick={onClick} className={cx(
      "inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-[12.5px] transition-colors focus-ring",
      active ? "bg-primary text-primary-fg" : "text-ink-2 ring-1 ring-inset ring-line-strong hover:bg-hover hover:text-ink", className)}>
      {children}
    </C>
  );
}

export function Button({ children, variant = "ghost", size = "md", className, ...rest }:
  { variant?: "primary" | "ghost" | "outline"; size?: "sm" | "md" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...rest} className={cx(
      "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-colors focus-ring disabled:pointer-events-none disabled:opacity-40 select-none",
      size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-4 text-[14px]",
      variant === "primary" && "bg-primary text-primary-fg hover:bg-primary-hover",
      variant === "outline" && "bg-elev text-ink ring-1 ring-inset ring-line-strong hover:bg-hover",
      variant === "ghost" && "text-ink-2 hover:bg-hover hover:text-ink",
      className)}>
      {children}
    </button>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange }: { value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void }) {
  const id = options.map((x) => x.value).join();
  return (
    <div className="relative inline-flex rounded-full bg-sunken p-1">
      {options.map((o) => (
        <button key={String(o.value)} onClick={() => onChange(o.value)}
          className={cx("relative z-10 h-7 rounded-full px-3.5 text-[12.5px] transition-colors focus-ring", value === o.value ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
          {value === o.value && <motion.span layoutId={`seg-${id}`} className="absolute inset-0 -z-10 rounded-full bg-solid shadow-[var(--shadow-card)] ring-1 ring-line" transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: { id: T; label: string; count?: number }[]; onChange: (v: T) => void }) {
  return (
    <div className="-mx-1 flex gap-1 overflow-x-auto border-b border-line px-1">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={cx("relative shrink-0 px-3 pb-3 pt-1 text-[13px] transition-colors focus-ring", value === t.id ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
          {t.label}{t.count != null && <span className="ml-1.5 text-ink-3 tnum">{t.count}</span>}
          {value === t.id && <motion.span layoutId="tab-underline" className="absolute inset-x-2 -bottom-px h-px bg-ink" />}
        </button>
      ))}
    </div>
  );
}

export function Delta({ value, suffix = "", invert, neutral }: { value: number | null | undefined; suffix?: string; invert?: boolean; neutral?: boolean }) {
  if (value == null || Number.isNaN(value)) return null;
  const up = value > 0, flat = Math.abs(value) < 1e-9;
  const good = neutral ? null : invert ? !up : up;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cx("inline-flex items-center gap-0.5 text-[12px] tnum", flat || good === null ? "text-ink-3" : good ? "text-good" : "text-crit")}>
      <Icon size={13} strokeWidth={2} />{flat ? "flat" : `${up ? "+" : ""}${value}${suffix}`}
    </span>
  );
}

export function Stat({ label, value, sub, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="eyebrow">{label}</div>
      <div className="mt-2 text-[28px] font-semibold leading-none tracking-[-0.02em] tnum text-ink">{value}</div>
      {sub && <div className="mt-2 text-[12.5px] text-ink-3">{sub}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("shimmer rounded-lg", className)} />;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      {icon && <div className="mb-4 grid size-10 place-items-center rounded-full bg-sunken text-ink-3">{icon}</div>}
      <div className="text-[14px] text-ink">{title}</div>
      {children && <div className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-ink-3">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Drawer({ open, onClose, children, width = 680 }: { open: boolean; onClose: () => void; children: ReactNode; width?: number }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside role="dialog" aria-modal className="glass fixed bottom-2 right-2 top-2 z-50 flex max-w-[calc(100vw-1rem)] flex-col overflow-hidden rounded-[20px] border border-line shadow-[var(--shadow-panel)]"
            style={{ width }} initial={{ x: 24, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 24, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}>
            <button onClick={onClose} aria-label="Close" className="absolute right-4 top-4 z-10 grid size-8 place-items-center rounded-full text-ink-3 hover:bg-hover hover:text-ink focus-ring"><X size={16} /></button>
            <div className="flex-1 overflow-y-auto">{children}</div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="inline-grid h-5 min-w-5 place-items-center rounded-md bg-sunken px-1 font-mono text-[11px] text-ink-3">{children}</kbd>;
}

/* ── Evidence trail ─────────────────────────────────────────────────────────── */
export const shotUrl = (name: string) => `/api/evidence/${name}?${authQuery()}`;

export function EvidenceList({ items, compact }: { items: Evidence[]; compact?: boolean }) {
  const [shot, setShot] = useState<string | null>(null);
  if (!items?.length) return null;
  return (
    <div className={cx("space-y-1.5", compact && "space-y-1")}>
      {items.map((e, i) => (
        <div key={i} className="flex items-center gap-2 text-[11.5px] text-ink-3">
          <span className="mono w-[84px] shrink-0">{e.observed_at ? new Date(e.observed_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "-"}</span>
          <span className="truncate">{e.method}{e.note ? ` · ${e.note}` : ""}</span>
          {e.url && <a href={e.url} target="_blank" rel="noreferrer" className="ml-auto inline-flex shrink-0 items-center gap-1 text-ink-2 hover:text-ink">{host(e.url)}<ExternalLink size={10} /></a>}
          {e.screenshot && (
            <button onClick={() => setShot(e.screenshot!)} className={cx("inline-flex shrink-0 items-center gap-1 text-ink-2 hover:text-ink", !e.url && "ml-auto")}>
              <ImageIcon size={11} />Screenshot
            </button>
          )}
        </div>
      ))}
      <Lightbox src={shot ? shotUrl(shot) : null} onClose={() => setShot(null)} />
    </div>
  );
}

export function Lightbox({ src, onClose }: { src: string | null; onClose: () => void }) {
  return (
    <AnimatePresence>
      {src && (
        <motion.div className="fixed inset-0 z-[70] grid place-items-center bg-overlay p-6 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.img src={src} alt="Evidence screenshot" initial={{ scale: 0.98 }} animate={{ scale: 1 }}
            className="max-h-[88vh] max-w-[92vw] rounded-[20px] border border-line bg-solid shadow-[var(--shadow-panel)]" />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Thumb({ name, className }: { name?: string | null; className?: string }) {
  const [open, setOpen] = useState(false);
  if (!name) return <div className={cx("grid place-items-center rounded-lg bg-sunken text-ink-3", className)}><ImageIcon size={16} /></div>;
  return (
    <>
      <button onClick={() => setOpen(true)} className={cx("overflow-hidden rounded-lg border border-line bg-sunken focus-ring", className)}>
        <img src={shotUrl(name)} alt="" loading="lazy" className="h-full w-full object-cover object-top transition-transform duration-300 hover:scale-[1.01]" />
      </button>
      <Lightbox src={open ? shotUrl(name) : null} onClose={() => setOpen(false)} />
    </>
  );
}

export function Since({ iso }: { iso?: string | null }) {
  return <span className="mono text-[11.5px] text-ink-3">{ago(iso)}</span>;
}
