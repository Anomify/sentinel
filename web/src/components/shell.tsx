import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Command } from "cmdk";
import {
  Activity, Bot, Check, ChevronDown, FileText, Globe, LayoutDashboard, Loader2, Mail, Menu, Moon, Newspaper,
  Play, Radar, Search, Settings, Sun, Swords, X, Zap,
} from "lucide-react";
import { api, invalidate, runJob } from "../lib/api";
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
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-80 max-w-[calc(100vw-2rem)]" aria-live="polite">
        <AnimatePresence>
          {items.map((t) => (
            <motion.div key={t.id} layout initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, x: 24 }}
              className="card flex gap-3 p-3.5">
              <span className={cx("mt-0.5 grid size-5 shrink-0 place-items-center rounded-full",
                t.tone === "err" ? "bg-crit/15 text-crit" : t.tone === "info" ? "bg-accent-soft text-accent-ink" : "bg-good/15 text-good")}>
                {t.tone === "err" ? <X size={12} strokeWidth={3} /> : t.tone === "info" ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} strokeWidth={3} />}
              </span>
              <div className="min-w-0">
                <div className="text-[13px] font-medium text-ink">{t.title}</div>
                {t.body && <div className="text-[12px] text-ink-3 mt-0.5 break-words">{t.body}</div>}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

/* ── Job runner (polls while a job is in flight, then refreshes every view) ── */
const JOB_LABEL: Record<string, string> = { pages: "Page scan", feeds: "Feed sync", ai: "AI visibility run", digest: "Digest" };
const JobCtx = createContext<{ running: string[]; start: (job: string, opts?: { deliver?: boolean }) => void }>({ running: [], start: () => {} });
export const useJobs = () => useContext(JobCtx);

export function JobProvider({ children }: { children: ReactNode }) {
  const [running, setRunning] = useState<string[]>([]);
  const toast = useToast();
  const timer = useRef<number | undefined>(undefined);

  const poll = useCallback(() => {
    window.clearTimeout(timer.current);
    api<{ runs: Run[]; running: Record<string, string> }>("/api/runs?limit=10").then((r) => {
      const now = Object.keys(r.running);
      setRunning((prev) => {
        for (const job of prev.filter((j) => !now.includes(j))) {
          const last = r.runs.find((x) => x.job === job);
          if (last?.status === "error") toast({ title: `${JOB_LABEL[job]} failed`, body: last.error ?? undefined, tone: "err" });
          else toast({ title: `${JOB_LABEL[job]} complete`, body: summarize(job, last?.stats) });
          invalidate();
        }
        return now;
      });
      if (now.length) timer.current = window.setTimeout(poll, 2000);
    }).catch(() => {});
  }, [toast]);

  useEffect(() => { poll(); return () => window.clearTimeout(timer.current); }, [poll]);

  const start = useCallback((job: string, opts?: { deliver?: boolean }) => {
    runJob(job, opts).then((r) => {
      if (r.status === "already_running") toast({ title: `${JOB_LABEL[job]} already running`, tone: "info" });
      else toast({ title: `${JOB_LABEL[job]} started`, body: "You can keep working — we'll refresh when it's done.", tone: "info" });
      setRunning((p) => Array.from(new Set([...p, job])));
      window.setTimeout(poll, 1200);
    }).catch((e) => toast({ title: "Couldn't start job", body: String(e), tone: "err" }));
  }, [poll, toast]);

  return <JobCtx.Provider value={{ running, start }}>{children}</JobCtx.Provider>;
}

function summarize(job: string, s: any): string | undefined {
  if (!s) return;
  if (job === "pages") return `${s.pages} pages checked · ${s.changed} changed${s.errors ? ` · ${s.errors} errors` : ""}`;
  if (job === "feeds") return `${s.new_posts} new posts`;
  if (job === "ai") return s.skipped ?? `${s.answers} answers from ${(s.engines || []).join(", ")}`;
  if (job === "digest") return s.headline;
}

/* ── Navigation ─────────────────────────────────────────────────────────────── */
export const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, key: "g o" },
  { to: "/signals", label: "Signals", icon: Activity, key: "g s" },
  { to: "/competitors", label: "Competitors", icon: Swords, key: "g c" },
  { to: "/content", label: "Content", icon: Newspaper, key: "g n" },
  { to: "/ai", label: "AI Visibility", icon: Bot, key: "g a" },
  { to: "/digest", label: "Digest", icon: Mail, key: "g d" },
  { to: "/settings", label: "Settings", icon: Settings, key: "g ," },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="relative grid size-7 place-items-center rounded-lg bg-gradient-to-br from-[#b4abff] to-[#6e56cf] shadow-[0_4px_16px_-4px_#6e56cf]">
        <Radar size={15} className="text-white" strokeWidth={2.4} />
      </div>
      <div className="leading-none">
        <div className="text-[14px] font-semibold tracking-[-0.01em] text-ink">Sentinel</div>
        <div className="text-[10.5px] text-ink-3 mt-0.5">Competitive intelligence</div>
      </div>
    </div>
  );
}

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const meta = useMeta();
  const loc = useLocation();
  useEffect(onClose, [loc.pathname]); // eslint-disable-line
  const comps = meta.entities.filter((e) => !e.is_brand);
  const content = (
    <div className="flex h-full flex-col gap-6 px-3 py-4">
      <Logo />
      <nav className="flex flex-col gap-0.5">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === "/"}
            className={({ isActive }) => cx("group relative flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] transition-colors focus-ring",
              isActive ? "text-ink font-medium" : "text-ink-2 hover:text-ink hover:bg-hover")}>
            {({ isActive }) => (
              <>
                {isActive && <motion.span layoutId="nav-active" className="absolute inset-0 rounded-lg bg-hover ring-1 ring-inset ring-line" transition={{ type: "spring", bounce: 0.15, duration: 0.4 }} />}
                <Icon size={15} className={cx("relative", isActive ? "text-accent-ink" : "text-ink-3 group-hover:text-ink-2")} />
                <span className="relative">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div>
        <div className="eyebrow px-2.5 mb-2">Watchlist</div>
        <div className="flex flex-col gap-0.5">
          {comps.map((c) => (
            <NavLink key={c.id} to={`/competitors/${c.id}`}
              className={({ isActive }) => cx("flex h-7 items-center gap-2.5 rounded-lg px-2.5 text-[12.5px] transition-colors", isActive ? "bg-hover text-ink" : "text-ink-2 hover:bg-hover hover:text-ink")}>
              <EntityDot color={c.color} size={7} />
              <span className="truncate">{c.name}</span>
            </NavLink>
          ))}
        </div>
      </div>
      <div className="mt-auto">
        <SystemStatus />
      </div>
    </div>
  );
  return (
    <>
      <aside className="hidden lg:block fixed inset-y-0 left-0 w-60 border-r border-line bg-bg/60 backdrop-blur-xl z-30">{content}</aside>
      <AnimatePresence>
        {open && (
          <>
            <motion.div className="lg:hidden fixed inset-0 z-40 bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
            <motion.aside className="lg:hidden fixed inset-y-0 left-0 z-50 w-64 border-r border-line bg-elev"
              initial={{ x: -280 }} animate={{ x: 0 }} exit={{ x: -280 }} transition={{ type: "spring", bounce: 0, duration: 0.3 }}>
              {content}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}

function SystemStatus() {
  const meta = useMeta();
  const { running } = useJobs();
  const live = meta.engines.filter((e) => e.enabled && e.has_key).length;
  const ok = !meta.demo;
  return (
    <div className="rounded-xl bg-sunken ring-1 ring-inset ring-line p-3 text-[12px]">
      <div className="flex items-center gap-2 text-ink">
        <span className={cx("pulse-dot size-1.5 rounded-full", running.length ? "bg-accent text-accent" : ok ? "bg-good text-good" : "bg-med text-med")} />
        <span className="font-medium">{running.length ? "Collecting…" : ok ? "Monitoring live" : "Demo workspace"}</span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1 text-center">
        {[["Pages", meta.entities.reduce((a, e) => a + e.pages.length, 0)], ["Feeds", meta.entities.reduce((a, e) => a + e.feeds.length, 0)], ["Engines", live]].map(([l, v]) => (
          <div key={l as string} className="rounded-md bg-elev py-1.5 ring-1 ring-inset ring-line">
            <div className="tnum text-ink font-medium">{v}</div>
            <div className="text-[10px] text-ink-3">{l}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Top bar ────────────────────────────────────────────────────────────────── */
export function Topbar({ onMenu, onSearch }: { onMenu: () => void; onSearch: () => void }) {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || "dark");
  const flip = () => {
    const t = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("sentinel-theme", t); } catch { /* ignore */ }
    setTheme(t);
  };
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-bg/70 px-4 backdrop-blur-xl sm:px-6">
      <button onClick={onMenu} className="lg:hidden grid size-8 place-items-center rounded-lg text-ink-2 hover:bg-hover" aria-label="Menu"><Menu size={17} /></button>
      <button onClick={onSearch}
        className="flex h-8 min-w-0 flex-1 max-w-sm items-center gap-2 rounded-lg bg-sunken px-3 text-[13px] text-ink-3 ring-1 ring-inset ring-line transition-colors hover:ring-line-strong focus-ring">
        <Search size={14} />
        <span className="flex-1 text-left truncate"><span className="sm:hidden">Search…</span><span className="hidden sm:inline">Search competitors, signals, questions…</span></span>
        <span className="hidden sm:flex gap-1"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
      </button>
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        <RunMenu />
        <button onClick={flip} className="grid size-8 place-items-center rounded-lg text-ink-2 hover:text-ink hover:bg-hover focus-ring" aria-label="Toggle theme">
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
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
  const items = [
    { job: "pages", icon: Globe, label: "Scan pages now", sub: "Homepage, product & pricing diffs" },
    { job: "feeds", icon: Newspaper, label: "Sync feeds", sub: "New blog posts & announcements" },
    { job: "ai", icon: Bot, label: "Run AI visibility", sub: "Ask every engine your questions" },
    { job: "digest", icon: Mail, label: "Send digest", sub: "Build & deliver to Slack / email" },
  ];
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)}
        className="inline-flex h-8 items-center gap-2 rounded-lg bg-accent px-3 text-[12.5px] font-medium text-white shadow-[0_4px_14px_-6px_var(--accent)] hover:brightness-110 focus-ring">
        {running.length ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
        <span className="hidden sm:inline">{running.length ? "Running…" : "Run now"}</span>
        <ChevronDown size={13} className="opacity-70" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: -4, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="card absolute right-0 top-10 z-30 w-72 p-1.5">
            {items.map(({ job, icon: Icon, label, sub }) => {
              const busy = running.includes(job);
              return (
                <button key={job} disabled={busy} onClick={() => { start(job); setOpen(false); }}
                  className="flex w-full items-start gap-3 rounded-lg p-2.5 text-left hover:bg-hover disabled:opacity-60">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-sunken ring-1 ring-inset ring-line text-ink-2">
                    {busy ? <Loader2 size={15} className="animate-spin text-accent" /> : <Icon size={15} />}
                  </span>
                  <span>
                    <span className="block text-[13px] font-medium text-ink">{label}</span>
                    <span className="block text-[11.5px] text-ink-3">{busy ? "Running…" : sub}</span>
                  </span>
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── ⌘K command palette ─────────────────────────────────────────────────────── */
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
  const item = "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-ink-2 aria-selected:text-ink";
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[55] grid place-items-start justify-center bg-black/50 backdrop-blur-sm pt-[12vh] px-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)}>
          <motion.div initial={{ opacity: 0, scale: 0.97, y: -8 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.16 }} className="card w-[600px] max-w-full overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <Command loop label="Command menu">
              <div className="flex items-center gap-2 border-b border-line px-4">
                <Search size={15} className="text-ink-3" />
                <Command.Input autoFocus placeholder="Type a command or search…" className="h-12 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-3" />
                <Kbd>esc</Kbd>
              </div>
              <Command.List className="max-h-[50vh] overflow-y-auto p-1.5">
                <Command.Empty className="py-10 text-center text-[13px] text-ink-3">No results.</Command.Empty>
                <Command.Group heading="Navigate">
                  {NAV.map((n) => (
                    <Command.Item key={n.to} onSelect={() => go(n.to)} className={item}>
                      <n.icon size={15} className="text-ink-3" />{n.label}
                    </Command.Item>
                  ))}
                </Command.Group>
                <Command.Group heading="Competitors">
                  {meta.entities.filter((e) => !e.is_brand).map((c) => (
                    <Command.Item key={c.id} value={`competitor ${c.name} ${c.domains.join(" ")}`} onSelect={() => go(`/competitors/${c.id}`)} className={item}>
                      <EntityDot color={c.color} />{c.name}<span className="ml-auto text-[11px] text-ink-3">{c.domains[0]}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
                <Command.Group heading="Actions">
                  {[["pages", "Scan competitor pages now", Globe], ["feeds", "Sync blog feeds", Newspaper], ["ai", "Run AI visibility check", Bot], ["digest", "Send weekly digest now", Mail]].map(([j, l, I]: any) => (
                    <Command.Item key={j} onSelect={() => { start(j); setOpen(false); }} className={item}>
                      <Play size={15} className="text-ink-3" />{l}
                    </Command.Item>
                  ))}
                  {meta.entities.filter((e) => !e.is_brand).map((c) => (
                    <Command.Item key={`bc-${c.id}`} value={`battlecard copy ${c.name}`} onSelect={() => go(`/competitors/${c.id}?battlecard=1`)} className={item}>
                      <FileText size={15} className="text-ink-3" />Open battlecard: {c.name}
                    </Command.Item>
                  ))}
                </Command.Group>
                <Command.Group heading="AI questions">
                  {meta.questions.map((q) => (
                    <Command.Item key={q.id} value={`question ${q.text}`} onSelect={() => go(`/ai?q=${q.id}`)} className={item}>
                      <Bot size={15} className="text-ink-3 shrink-0" /><span className="truncate">{q.text}</span>
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

export function LastRun({ iso }: { iso?: string | null }) {
  return <span className="text-[12px] text-ink-3">Updated {ago(iso)}</span>;
}
