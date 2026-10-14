import { createContext, useContext, useEffect, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Minus, X } from "lucide-react";
import type { Entity, Meta, Severity } from "../lib/types";

/* ── meta context: entity lookup everywhere ─────────────────────────────────── */
export const MetaCtx = createContext<Meta | null>(null);
export const useMeta = () => useContext(MetaCtx)!;
export function useEntity(id: string): Entity | undefined {
  return useMeta()?.entities.find((e) => e.id === id);
}
/** Series order for charts: competitors in watchlist order, brand last (validated palette order). */
export function useSeries(): Entity[] {
  const m = useMeta();
  return m ? [...m.entities.filter((e) => !e.is_brand), ...m.entities.filter((e) => e.is_brand)] : [];
}

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export const fade = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] as const },
};

export function Card({ children, className, glow, ...rest }: { children: ReactNode; className?: string; glow?: boolean } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("card", glow && "glow", className)} {...rest}>{children}</div>;
}

export function CardHeader({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 pt-4 pb-3">
      <div className="min-w-0">
        <h3 className="text-[13px] font-medium text-ink">{title}</h3>
        {sub && <p className="text-[12px] text-ink-3 mt-0.5">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

export function PageHeader({ title, sub, right, eyebrow }: { title: ReactNode; sub?: ReactNode; right?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <motion.div {...fade} className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        {eyebrow && <div className="eyebrow mb-2">{eyebrow}</div>}
        <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.02em] text-ink">{title}</h1>
        {sub && <p className="text-[14px] text-ink-2 mt-1.5 max-w-2xl">{sub}</p>}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </motion.div>
  );
}

const SEV: Record<string, { label: string; cls: string; dot: string }> = {
  critical: { label: "Critical", cls: "text-crit bg-crit/10 ring-crit/25", dot: "bg-crit" },
  high: { label: "High", cls: "text-high bg-high/10 ring-high/25", dot: "bg-high" },
  medium: { label: "Medium", cls: "text-med bg-med/10 ring-med/25", dot: "bg-med" },
  low: { label: "Low", cls: "text-ink-3 bg-ink-3/10 ring-ink-3/20", dot: "bg-low" },
  noise: { label: "Noise", cls: "text-ink-3 bg-ink-3/10 ring-ink-3/20", dot: "bg-low" },
};
export function SeverityBadge({ s, compact }: { s: Severity; compact?: boolean }) {
  const v = SEV[s] ?? SEV.low;
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-md ring-1 ring-inset font-medium", compact ? "px-1.5 py-0.5 text-[10.5px]" : "px-2 py-0.5 text-[11px]", v.cls)}>
      {s === "critical" ? <AlertTriangle size={11} strokeWidth={2.5} /> : <span className={cx("size-1.5 rounded-full", v.dot)} />}
      {v.label}
    </span>
  );
}
export const sevDot = (s: string) => (SEV[s] ?? SEV.low).dot;

export function EntityDot({ color, size = 8, ring }: { color: string; size?: number; ring?: boolean }) {
  return <span className={cx("inline-block shrink-0 rounded-full", ring && "ring-2 ring-elev")} style={{ width: size, height: size, background: color }} />;
}

export function EntityTag({ id, className }: { id: string; className?: string }) {
  const e = useEntity(id);
  if (!e) return <span className="text-ink-3">{id}</span>;
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-[12px] font-medium text-ink", className)}>
      <EntityDot color={e.color} size={7} />
      {e.is_brand ? `${e.name} (you)` : e.name}
    </span>
  );
}

export function Monogram({ id, size = 32 }: { id: string; size?: number }) {
  const e = useEntity(id);
  const name = e?.name ?? id;
  const initials = name.replace(/\(.*?\)/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return (
    <span className="inline-grid place-items-center shrink-0 rounded-[10px] font-semibold text-white"
      style={{ width: size, height: size, fontSize: size * 0.36, background: `linear-gradient(135deg, ${e?.color ?? "#666"}, color-mix(in oklab, ${e?.color ?? "#666"} 55%, black))` }}>
      {initials}
    </span>
  );
}

export function Chip({ children, active, onClick, className }: { children: ReactNode; active?: boolean; onClick?: () => void; className?: string }) {
  const C = onClick ? "button" : "span";
  return (
    <C onClick={onClick} className={cx(
      "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] ring-1 ring-inset transition-colors focus-ring",
      active ? "bg-accent-soft text-accent-ink ring-accent/30" : "text-ink-2 ring-line-strong hover:bg-hover",
      className)}>
      {children}
    </C>
  );
}

export function Button({ children, variant = "ghost", size = "md", className, ...rest }:
  { variant?: "primary" | "ghost" | "outline"; size?: "sm" | "md" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...rest} className={cx(
      "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all focus-ring disabled:opacity-50 disabled:pointer-events-none select-none",
      size === "sm" ? "h-7 px-2.5 text-[12px]" : "h-9 px-3.5 text-[13px]",
      variant === "primary" && "bg-accent text-white hover:brightness-110 shadow-[0_1px_0_0_rgba(255,255,255,0.15)_inset,0_4px_14px_-4px_var(--accent)]",
      variant === "outline" && "ring-1 ring-inset ring-line-strong text-ink hover:bg-hover",
      variant === "ghost" && "text-ink-2 hover:text-ink hover:bg-hover",
      className)}>
      {children}
    </button>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange }: { value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div className="relative inline-flex rounded-lg bg-sunken p-0.5 ring-1 ring-inset ring-line">
      {options.map((o) => (
        <button key={String(o.value)} onClick={() => onChange(o.value)}
          className={cx("relative z-10 h-7 px-3 text-[12px] font-medium rounded-md transition-colors focus-ring", value === o.value ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
          {value === o.value && <motion.span layoutId={`seg-${options.map((x) => x.value).join()}`} className="absolute inset-0 -z-10 rounded-md bg-elev shadow-sm ring-1 ring-line" transition={{ type: "spring", bounce: 0.15, duration: 0.4 }} />}
          {o.label}
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
    <span className={cx("inline-flex items-center gap-0.5 text-[12px] font-medium tnum",
      flat || good === null ? "text-ink-3" : good ? "text-good" : "text-crit")}>
      <Icon size={13} strokeWidth={2.4} />
      {flat ? "flat" : `${up ? "+" : ""}${value}${suffix}`}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("shimmer rounded-md", className)} />;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-14 px-6">
      {icon && <div className="mb-4 grid size-11 place-items-center rounded-xl bg-sunken ring-1 ring-line text-ink-3">{icon}</div>}
      <div className="text-[14px] font-medium text-ink">{title}</div>
      {children && <div className="mt-1 text-[13px] text-ink-3 max-w-sm">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Drawer({ open, onClose, children, width = 640 }: { open: boolean; onClose: () => void; children: ReactNode; width?: number }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside role="dialog" aria-modal
            className="fixed right-0 top-0 bottom-0 z-50 flex flex-col bg-elev border-l border-line shadow-2xl max-w-full"
            style={{ width }}
            initial={{ x: 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 40, opacity: 0 }}
            transition={{ type: "spring", bounce: 0, duration: 0.35 }}>
            <button onClick={onClose} aria-label="Close" className="absolute right-4 top-4 z-10 grid size-8 place-items-center rounded-lg text-ink-3 hover:text-ink hover:bg-hover focus-ring"><X size={16} /></button>
            <div className="flex-1 overflow-y-auto">{children}</div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="inline-grid min-w-5 h-5 place-items-center rounded-[5px] px-1 font-sans text-[11px] text-ink-3 ring-1 ring-inset ring-line-strong bg-sunken">{children}</kbd>;
}
