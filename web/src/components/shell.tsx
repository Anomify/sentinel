import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Command } from "cmdk";
import {
  Activity, BadgeDollarSign, Bot, Briefcase, Check, ChevronDown, Compass, FileSearch, Globe, Layers, LayoutGrid, Loader2, Mail, MessagesSquare, Package,
  Menu, Network, Newspaper, Play, Rocket, Search, Settings, ShieldCheck, Swords, X,
} from "lucide-react";
import { api, invalidate, runJob, setWorkspace, workspace } from "../lib/api";
import type { Run } from "../lib/types";
import { ago } from "../lib/format";
import { cx, EntityDot, Kbd, useMeta } from "./ui";

/* ── Toasts ─────────────────────────────────────────────────────────────────── */
type Toast = { id: number; title: string; body?: string; tone?: "ok" | "err" | "info" };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { ...t, id }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-5 right-5 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        <AnimatePresence>
          {items.map((t) => (
            <motion.div key={t.id} layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 20 }}
              className="flex gap-3 rounded-2xl border border-line bg-elev p-4 shadow-[0_12px_40px_-12px_rgba(0,0,0,0.18)]">
              <span className={cx("mt-0.5 grid size-5 shrink-0 place-items-center rounded-full",
                t.tone === "err" ? "bg-crit/10 text-crit" : t.tone === "info" ? "bg-sunken text-ink-2" : "bg-good/10 text-good")}>
                {t.tone === "err" ? <X size={11} /> : t.tone === "info" ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
              </span>
              <div className="min-w-0">
                <div className="text-[13px] text-ink">{t.title}</div>
                {t.body && <div className="mt-0.5 break-words text-[12px] text-ink-3">{t.body}</div>}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

/* ── Jobs ───────────────────────────────────────────────────────────────────── */
export const JOB_LABEL: Record<string, string> = {
  pages: "Page scan", feeds: "Content sync", stack: "Stack & tag manager", dns: "DNS & email", subdomains: "Certificate transparency",
  radar: "Pre-launch radar", product: "Product launches", social: "Social media", hiring: "Hiring", money: "Partners & money", ads: "Ads", ai: "AI visibility", deepdive: "Deep dives", digest: "Digest", all: "Everything",
};
// What each job refreshes, in the words of the sidebar.
const JOB_HELP: Record<string, string> = {
  all: "Every section below, for every company. Takes 10 to 20 minutes.",
  subdomains: "New subdomains and certificates (Infrastructure)", dns: "Email tools and DNS verifications (Infrastructure)",
  stack: "Marketing tools and tracking (GTM stack)", pages: "Homepage, pricing and messaging changes (Positioning)",
  radar: "Staging sites, new pages, new repos (Launch radar)", product: "New products, release notes, launches (Product launches)",
  social: "LinkedIn, X, YouTube, Medium, Bluesky, Hacker News (Messaging)",
  hiring: "Open roles and first-of-their-kind hires (Hiring)", money: "Funding, partners, marketplaces, press (Partners & money)",
  ads: "Ad channels (Partners & money)", feeds: "New blog posts (Messaging)", ai: "What AI search engines say (AI visibility). Uses API quota.",
  deepdive: "Rewrites every deep dive from the latest data (Deep dives)", digest: "Saves a new weekly digest (Digest)",
};
// Count new findings in a run's stats, wherever the collector reported them.
const countAdded = (s: any): number => !s || typeof s !== "object" ? 0
  : Object.entries(s).reduce((n, [k, v]) => n + (k === "added" && typeof v === "number" ? v : countAdded(v)), 0);
const JobCtx = createContext<{ running: string[]; start: (job: string, opts?: { deliver?: boolean }) => void; poll: () => void }>({ running: [], start: () => {}, poll: () => {} });
export const useJobs = () => useContext(JobCtx);

export function JobProvider({ children }: { children: ReactNode }) {
  const [running, setRunning] = useState<string[]>([]);
  const toast = useToast();
  const timer = useRef<number | undefined>(undefined);
  const poll = useCallback(() => {
    window.clearTimeout(timer.current);
    api<{ runs: Run[]; running: Record<string, string> }>("/api/runs?limit=15").then((r) => {
      const now = Object.keys(r.running);
      setRunning((prev) => {
        for (const job of prev.filter((j) => !now.includes(j))) {
          const last = r.runs.find((x) => x.job === job);
          const label = JOB_LABEL[job] ?? (job.startsWith("scan:") ? "Full scan" : job);
          if (last?.status === "error") toast({ title: `${label} failed`, body: last.error ?? undefined, tone: "err" });
          else {
            const n = countAdded(last?.stats);
            toast({ title: `${label} finished`, body: n ? `${n} new finding${n === 1 ? "" : "s"}. The pages have been refreshed; new items are in Signals.` : "Nothing new since the last run. The pages are up to date." });
          }
          invalidate();
        }
        return now;
      });
      if (now.length) timer.current = window.setTimeout(poll, 2500);
    }).catch(() => {});
  }, [toast]);
  useEffect(() => { poll(); return () => window.clearTimeout(timer.current); }, [poll]);
  const start = useCallback((job: string, opts?: { deliver?: boolean }) => {
    runJob(job, opts).then((r) => {
      toast({ title: r.status === "already_running" ? `${JOB_LABEL[job]} is already running` : `${JOB_LABEL[job]} started`, body: r.status === "already_running" ? undefined : "Collecting fresh data in the background. This usually takes 1 to 5 minutes; you'll get a message here when it's done.", tone: "info" });
      setRunning((p) => Array.from(new Set([...p, job])));
      window.setTimeout(poll, 1200);
    }).catch((e) => toast({ title: "Couldn't start job", body: String(e), tone: "err" }));
  }, [poll, toast]);
  return <JobCtx.Provider value={{ running, start, poll }}>{children}</JobCtx.Provider>;
}

/* ── Navigation ─────────────────────────────────────────────────────────────── */
export const NAV: { group: string; items: { to: string; label: string; icon: any }[] }[] = [
  { group: "Intelligence", items: [
    { to: "/", label: "Overview", icon: LayoutGrid },
    { to: "/signals", label: "Signals", icon: Activity },
    { to: "/deep-dives", label: "Deep dives", icon: FileSearch },
    { to: "/competitors", label: "Competitors", icon: Swords },
  ] },
  { group: "Modules", items: [
    { to: "/stack", label: "GTM stack", icon: Layers },
    { to: "/infrastructure", label: "Infrastructure", icon: Network },
    { to: "/radar", label: "Launch radar", icon: Rocket },
    { to: "/product", label: "Product launches", icon: Package },
    { to: "/messaging", label: "Messaging", icon: MessagesSquare },
    { to: "/hiring", label: "Hiring", icon: Briefcase },
    { to: "/money", label: "Partners & money", icon: BadgeDollarSign },
    { to: "/positioning", label: "Positioning", icon: Newspaper },
    { to: "/ai", label: "AI visibility", icon: Bot },
  ] },
  { group: "System", items: [
    { to: "/coverage", label: "Coverage", icon: ShieldCheck },
    { to: "/digest", label: "Digest", icon: Mail },
    { to: "/settings", label: "Settings", icon: Settings },
  ] },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-3">
      <div className="grid size-7 place-items-center rounded-[9px] bg-ink">
        <span className="relative grid size-3.5 place-items-center rounded-full ring-[1.5px] ring-white"><span className="size-1 rounded-full bg-white" /></span>
      </div>
      <span className="text-[16px] tracking-[-0.02em] text-ink">sentinel</span>
    </div>
  );
}

function WorkspaceSwitcher() {
  const meta = useMeta();
  const [open, setOpen] = useState(false);
  if (meta.workspaces.length < 2) return null;
  const cur = meta.workspaces.find((w) => w.slug === meta.workspace);
  return (
    <div className="relative px-1">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-[13px] text-ink hover:bg-hover">
        <span className="truncate">{cur?.name ?? meta.workspace}</span><ChevronDown size={13} className="text-ink-3" />
      </button>
      {open && (
        <div className="card absolute left-1 right-1 top-10 z-30 p-1">
          {meta.workspaces.map((w) => (
            <button key={w.slug} onClick={() => { setWorkspace(w.slug); setOpen(false); }}
              className={cx("block w-full rounded-lg px-3 py-2 text-left text-[13px] hover:bg-hover", w.slug === workspace() ? "text-ink" : "text-ink-2")}>{w.name}</button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const meta = useMeta();
  const loc = useLocation();
  const { running } = useJobs();
  useEffect(onClose, [loc.pathname]); // eslint-disable-line
  const content = (
    <div className="flex h-full flex-col gap-6 overflow-y-auto px-3 pb-4 pt-5">
      <Logo />
      <WorkspaceSwitcher />
      {NAV.map((g) => (
        <nav key={g.group} className="flex flex-col gap-px">
          <div className="eyebrow mb-1.5 px-3">{g.group}</div>
          {g.items.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => cx("group relative flex h-8 items-center gap-2.5 rounded-xl px-3 text-[13px] transition-colors focus-ring",
                isActive ? "text-ink" : "text-ink-2 hover:bg-hover hover:text-ink")}>
              {({ isActive }) => (
                <>
                  {isActive && <motion.span layoutId="nav-active" className="absolute inset-0 rounded-xl bg-elev ring-1 ring-line" transition={{ type: "spring", bounce: 0.12, duration: 0.4 }} />}
                  <Icon size={15} strokeWidth={1.6} className={cx("relative", isActive ? "text-ink" : "text-ink-3 group-hover:text-ink-2")} />
                  <span className="relative">{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>
      ))}
      <div className="mt-auto px-3 text-[11.5px] text-ink-3">
        <div className="flex items-center gap-2">
          <span className={cx("pulse-dot size-1.5 rounded-full", running.length ? "bg-accent text-accent" : meta.demo ? "bg-med text-med" : "bg-good text-good")} />
          {running.length ? `Collecting · ${running.length} job${running.length > 1 ? "s" : ""}` : meta.demo ? "Demo workspace" : "Monitoring live"}
        </div>
        <div className="mt-1.5">{meta.entities.filter((e) => !e.is_brand).length} competitors · {meta.backend}</div>
      </div>
    </div>
  );
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-line bg-bg lg:block">{content}</aside>
      <AnimatePresence>
        {open && (
          <>
            <motion.div className="fixed inset-0 z-40 bg-[#111]/20 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
            <motion.aside className="fixed inset-y-0 left-0 z-50 w-64 border-r border-line bg-bg lg:hidden"
              initial={{ x: -280 }} animate={{ x: 0 }} exit={{ x: -280 }} transition={{ type: "spring", bounce: 0, duration: 0.3 }}>
              {content}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}

/* ── Top bar ────────────────────────────────────────────────────────────────── */
export function Topbar({ onMenu, onSearch }: { onMenu: () => void; onSearch: () => void }) {
  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 bg-bg/80 px-4 backdrop-blur-xl sm:px-8">
      <button onClick={onMenu} className="grid size-9 place-items-center rounded-full text-ink-2 hover:bg-hover lg:hidden" aria-label="Menu"><Menu size={17} /></button>
      <button onClick={onSearch}
        className="flex h-9 min-w-0 max-w-md flex-1 items-center gap-2.5 rounded-full bg-elev px-4 text-[13px] text-ink-3 ring-1 ring-inset ring-line transition-colors hover:ring-line-strong focus-ring">
        <Search size={14} strokeWidth={1.6} />
        <span className="flex-1 truncate text-left"><span className="sm:hidden">Search…</span><span className="hidden sm:inline">Search competitors, modules, questions…</span></span>
        <span className="hidden gap-1 sm:flex"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
      </button>
      <div className="ml-auto flex shrink-0 items-center gap-2"><RunMenu /></div>
    </header>
  );
}

function RunMenu() {
  const { running, start } = useJobs();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const items = ["all", "product", "social", "feeds", "pages", "hiring", "money", "stack", "subdomains", "dns", "radar", "ads", "ai", "deepdive", "digest"];
  const meta = useMeta();
  const lastRun = (job: string) => meta.schedule.find((x) => x.job === job)?.last;
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)}
        className="inline-flex h-9 items-center gap-2 rounded-full bg-ink px-4 text-[13px] text-white transition-colors hover:bg-[#2a2a2e] focus-ring">
        {running.length ? <Loader2 size={14} className="animate-spin" /> : <Play size={13} />}
        <span className="hidden sm:inline">{running.length ? `Refreshing ${running.length === 1 ? (JOB_LABEL[running[0]] ?? "scan").toLowerCase() : `${running.length} sections`}…` : "Refresh data"}</span>
        <ChevronDown size={13} className="opacity-60" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.14 }}
            className="absolute right-0 top-11 z-30 max-h-[80vh] w-[340px] overflow-y-auto rounded-2xl border border-line bg-elev p-1.5 shadow-[0_16px_48px_-16px_rgba(0,0,0,0.2)]">
            <div className="px-3 pb-2 pt-2 text-[12px] leading-relaxed text-ink-3">Sentinel refreshes everything on a schedule. Use this to collect fresh data now instead of waiting.</div>
            {items.map((job) => {
              const busy = running.includes(job);
              const last = lastRun(job);
              return (
                <button key={job} disabled={busy} onClick={() => { start(job); setOpen(false); }}
                  className={cx("flex w-full items-start justify-between gap-3 rounded-xl px-3 py-2 text-left hover:bg-hover disabled:opacity-50", job === "all" && "mb-1 border-b border-line pb-2.5")}>
                  <span>
                    <span className="block text-[13px] text-ink">{job === "all" ? "Refresh everything" : JOB_LABEL[job]}</span>
                    <span className="block text-[11.5px] leading-snug text-ink-3">{JOB_HELP[job]}</span>
                  </span>
                  <span className="shrink-0 pt-0.5 text-[11px] text-ink-3">{busy ? <Loader2 size={13} className="animate-spin" /> : last ? ago(last) : ""}</span>
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── ⌘K ─────────────────────────────────────────────────────────────────────── */
export function CommandPalette({ open, setOpen }: { open: boolean; setOpen: (v: boolean) => void }) {
  const meta = useMeta();
  const nav = useNavigate();
  const { start } = useJobs();
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(!open); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, setOpen]);
  const go = (to: string) => { nav(to); setOpen(false); };
  const item = "flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] text-ink-2 aria-selected:text-ink";
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[55] grid place-items-start justify-center bg-[#111]/15 px-4 pt-[14vh] backdrop-blur-[2px]"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)}>
          <motion.div initial={{ opacity: 0, scale: 0.98, y: -6 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.15 }} className="w-[620px] max-w-full overflow-hidden rounded-2xl border border-line bg-elev shadow-[0_32px_80px_-24px_rgba(0,0,0,0.3)]"
            onClick={(e) => e.stopPropagation()}>
            <Command loop label="Command menu">
              <div className="flex items-center gap-2.5 border-b border-line px-5">
                <Search size={15} className="text-ink-3" strokeWidth={1.6} />
                <Command.Input autoFocus placeholder="Type a command or search…" className="h-14 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3" />
                <Kbd>esc</Kbd>
              </div>
              <Command.List className="max-h-[52vh] overflow-y-auto p-2">
                <Command.Empty className="py-12 text-center text-[13px] text-ink-3">No results.</Command.Empty>
                <Command.Group heading="Go to">
                  {NAV.flatMap((g) => g.items).map((n) => (
                    <Command.Item key={n.to} onSelect={() => go(n.to)} className={item}><n.icon size={15} strokeWidth={1.6} className="text-ink-3" />{n.label}</Command.Item>
                  ))}
                </Command.Group>
                <Command.Group heading="Deep dives">
                  {meta.entities.filter((e) => !e.is_brand).map((c) => (
                    <Command.Item key={c.id} value={`deep dive ${c.name} ${c.domains.join(" ")}`} onSelect={() => go(`/deep-dives/${c.id}`)} className={item}>
                      <EntityDot color={c.color} />{c.name}<span className="ml-auto text-[11.5px] text-ink-3">{c.domains[0]}</span>
                    </Command.Item>
                  ))}
                  <Command.Item value="new deep dive enter a domain analyse" onSelect={() => go("/deep-dives?new=1")} className={item}><Compass size={15} strokeWidth={1.6} className="text-ink-3" />Analyse a new domain…</Command.Item>
                </Command.Group>
                <Command.Group heading="Run">
                  {Object.entries(JOB_LABEL).map(([j, l]) => (
                    <Command.Item key={j} value={`run ${l}`} onSelect={() => { start(j); setOpen(false); }} className={item}><Play size={14} className="text-ink-3" />Run {l.toLowerCase()}</Command.Item>
                  ))}
                </Command.Group>
                <Command.Group heading="AI questions">
                  {meta.questions.map((q) => (
                    <Command.Item key={q.id} value={`question ${q.text}`} onSelect={() => go(`/ai?q=${q.id}`)} className={item}>
                      <Bot size={15} strokeWidth={1.6} className="shrink-0 text-ink-3" /><span className="truncate">{q.text}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
                <Command.Group heading="Sites">
                  {meta.entities.filter((e) => !e.is_brand).map((c) => (
                    <Command.Item key={`site-${c.id}`} value={`open site ${c.name}`} onSelect={() => { window.open(`https://${c.domains[0]}`, "_blank"); setOpen(false); }} className={item}>
                      <Globe size={15} strokeWidth={1.6} className="text-ink-3" />{c.domains[0]}
                    </Command.Item>
                  ))}
                </Command.Group>
              </Command.List>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
