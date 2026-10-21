import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Maximize, Minimize, Volume2, VolumeX } from "lucide-react";
import { useApi } from "../lib/api";
import type { Overview, SignalEvent } from "../lib/types";
import { ago, day, pct } from "../lib/format";
import {
  moveKey, quietUntil, quietWindows, useActivity, useChanged, useCountUp, useDailyReload, useFullscreen, useNewMoves, useNow, useSound, useWakeLock,
} from "../lib/kiosk";
import { cx, Monogram, useMeta } from "../components/ui";
import { useJobs } from "../components/shell";

/* The office TV (/tv): a read-only, glanceable view for a 40" 4K screen read from 3-4 m.
   Designed on a fixed 1920x1080 stage that is scaled to fill the screen exactly, so it looks the same at 4K whatever
   the browser's zoom, and never scrolls. Data comes from the same endpoints and refresh as the dashboard: any
   finished collection run updates it within ~15 s, and a new deploy reloads it. */

const W = 1920, H = 1080;
const RANK: Record<string, number> = { critical: 3, high: 2, medium: 1, low: 0 };
const TAKEOVER_MS = 12_000, CORNER_MS = 8_000;
const SEV_STYLE: Record<string, string> = {
  critical: "bg-red/15 text-crit ring-red/40", high: "bg-amber/15 text-high ring-amber/40",
  medium: "bg-sunken text-ink-2 ring-line", low: "bg-sunken text-ink-3 ring-line",
};
type Alert = { e: SignalEvent; kind: "takeover" | "corner" };

export default function Kiosk() {
  const meta = useMeta();
  const now = useNow();
  const active = useActivity(3000);
  const fs = useFullscreen();
  const sound = useSound();
  useWakeLock();
  useDailyReload(4);
  useKioskChrome();

  const { data: ov } = useApi<Overview>("/api/overview?days=7");
  const { data: recent } = useApi<SignalEvent[]>("/api/events?days=3");
  const rivals = useMemo(() => new Set(meta.entities.filter((e) => !e.is_brand && e.tier !== "self").map((e) => e.id)), [meta]);
  const fresh = useMemo(() => recent?.filter((e) => rivals.has(e.competitor)), [recent, rivals]);

  // New moves: critical/high take over the screen, medium slides in at the corner, low just joins the list.
  const [queue, setQueue] = useState<Alert[]>([]);
  const [lately, setLately] = useState<Record<string, number>>({});  // move key -> when it arrived, for a "New" badge
  useNewMoves(fresh, useCallback((items: SignalEvent[]) => {
    const sorted = [...items].sort((a, b) => (RANK[b.severity] ?? 0) - (RANK[a.severity] ?? 0));
    const big = sorted.filter((e) => RANK[e.severity] >= 2).slice(0, 3).map((e) => ({ e, kind: "takeover" as const }));
    const small = sorted.filter((e) => RANK[e.severity] === 1).slice(0, 3).map((e) => ({ e, kind: "corner" as const }));
    setQueue((q) => [...q, ...big, ...small]);
    setLately((l) => ({ ...l, ...Object.fromEntries(items.map((e) => [moveKey(e), Date.now()])) }));
  }, []));
  const current = queue[0];
  useEffect(() => {
    if (!current) return;
    sound.play(current.e.severity);
    const t = window.setTimeout(() => setQueue((q) => q.slice(1)), current.kind === "takeover" ? TAKEOVER_MS : CORNER_MS);
    return () => window.clearTimeout(t);
  }, [current]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Stage cursor={active}>
      <div className="flex h-full flex-col gap-7 p-12">
        <Header ov={ov} now={now} />
        {!ov ? <div className="grid flex-1 place-items-center text-[36px] text-ink-3">Loading…</div> : (
          <>
            <div className="grid min-h-0 flex-1 grid-cols-[1.5fr_1fr] grid-rows-[minmax(0,1fr)] gap-7">
              <Moves events={ov.top_events.slice(0, 4)} lately={lately} now={now} />
              <div className="flex min-h-0 flex-col gap-7">
                <div className="grid grid-cols-3 gap-7">
                  <Big label="High-impact" value={ov.kpis.critical} tone={ov.kpis.critical ? "text-crit" : "text-ink"} sub="this week" />
                  <Big label="Moves" value={ov.kpis.changes} sub={delta(ov.kpis.changes - ov.kpis.changes_prev, "vs last week")} />
                  <Big label="Pre-launch" value={ov.kpis.launch_indicators} sub="indicators" />
                </div>
                <AiShare ov={ov} />
                <Movers ov={ov} />
              </div>
            </div>
            <Posts ov={ov} />
          </>
        )}
      </div>
      <Controls active={active} fs={fs} sound={sound} now={now} />
      <AnimatePresence>
        {current?.kind === "takeover" && <Takeover key={moveKey(current.e)} e={current.e} />}
        {current?.kind === "corner" && <Corner key={moveKey(current.e)} e={current.e} />}
      </AnimatePresence>
    </Stage>
  );
}

/** Fixed 16:9 stage, scaled to the screen, no scrolling; the cursor hides with inactivity. */
function Stage({ children, cursor }: { children: ReactNode; cursor: boolean }) {
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const fit = () => setScale(Math.min(window.innerWidth / W, window.innerHeight / H));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  return (
    <div className="fixed inset-0 grid place-items-center overflow-hidden bg-bg" style={{ cursor: cursor ? "default" : "none" }}>
      <div className="relative shrink-0 overflow-hidden" style={{ width: W, height: H, transform: `scale(${scale})` }}>{children}</div>
    </div>
  );
}

/** The TV is always in high-contrast dark mode, and the page itself never scrolls. */
function useKioskChrome() {
  useEffect(() => {
    const root = document.documentElement;
    const wasDark = root.classList.contains("dark");
    root.classList.add("dark", "kiosk");
    return () => { root.classList.remove("kiosk"); root.classList.toggle("dark", wasDark); };
  }, []);
}

const delta = (d: number, what: string) => (d === 0 ? `same as last week` : `${d > 0 ? "+" : ""}${d} ${what}`);

function Header({ ov, now }: { ov?: Overview; now: Date }) {
  const { connection } = useJobs();
  const offline = connection.failures >= 2;
  const gaps = ov?.health.status === "degraded" ? [...ov.health.failing, ...ov.health.stale] : [];
  return (
    <header className="flex items-center gap-8">
      <div className="grid size-16 place-items-center rounded-[18px] bg-brand">
        <span className="grid size-8 place-items-center rounded-full ring-[3px] ring-brand-fg"><span className="size-2.5 rounded-full bg-brand-fg" /></span>
      </div>
      <div>
        <div className="text-[40px] font-semibold leading-none tracking-[-0.02em] text-ink">Sentinel</div>
        <div className="mt-2 text-[24px] leading-none text-ink-3">Competitive intelligence · last 7 days</div>
      </div>
      <div className="ml-auto flex items-center gap-10">
        {/* Never let a quiet screen pass for a quiet week. */}
        {offline ? (
          <Status dot="bg-red" text="text-crit" label={`Offline · last contact ${connection.lastOk ? ago(new Date(connection.lastOk).toISOString()) : "never"}`} />
        ) : gaps.length ? (
          <Status dot="bg-amber" text="text-high" label={`Collection gaps: ${gaps.slice(0, 2).join(", ")}${gaps.length > 2 ? ` +${gaps.length - 2}` : ""}`} />
        ) : (
          <Status dot="bg-green" text="text-ink-2" label={`Live · data ${ago(ov?.last_run?.finished_at)}`} pulse />
        )}
        <div className="text-right">
          <div className="mono text-[56px] font-medium leading-none text-ink">{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
          <div className="mt-2 text-[22px] leading-none text-ink-3">{now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}</div>
        </div>
      </div>
    </header>
  );
}

function Status({ dot, text, label, pulse }: { dot: string; text: string; label: string; pulse?: boolean }) {
  return (
    <div className={cx("flex max-w-[620px] items-center gap-3 text-[24px]", text)} role="status">
      <span className={cx("size-3.5 shrink-0 rounded-full", dot, pulse && "pulse-dot text-green")} />
      <span className="truncate">{label}</span>
    </div>
  );
}

function Panel({ title, children, className, flash }: { title: string; children: ReactNode; className?: string; flash?: boolean }) {
  return (
    <section className={cx("flex min-h-0 flex-col rounded-[24px] border border-line bg-solid p-8", flash && "kiosk-flash", className)}>
      <h2 className="eyebrow mb-4 !text-[20px] !font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Moves({ events, lately, now }: { events: SignalEvent[]; lately: Record<string, number>; now: Date }) {
  const flash = useChanged(events.map(moveKey));
  return (
    <Panel title="Latest moves" flash={flash} className="min-h-0">
      {events.length === 0 ? (
        <div className="grid flex-1 place-items-center text-center text-[32px] text-ink-3">No competitor moves this week.</div>
      ) : (
        <ol className="flex min-h-0 flex-1 flex-col justify-start divide-y divide-line overflow-hidden">
          {events.map((e) => {
            const isNew = now.getTime() - (lately[moveKey(e)] ?? 0) < 15 * 60_000;
            return (
              <li key={moveKey(e)} className={cx("flex items-start gap-6 py-6 first:pt-0", isNew && "kiosk-new")}>
                <Monogram id={e.competitor} size={64} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-4 text-[22px] text-ink-3">
                    <Name id={e.competitor} />
                    <span className={cx("rounded-full px-3.5 py-1 text-[19px] font-semibold ring-1 ring-inset", SEV_STYLE[e.severity] ?? SEV_STYLE.low)}>{label(e.severity)}</span>
                    {isNew && <span className="rounded-full bg-blue/15 px-3.5 py-1 text-[19px] font-semibold text-accent-ink ring-1 ring-inset ring-blue/40">New</span>}
                    <span className="mono ml-auto shrink-0 text-[20px]">
                      {e.occurred_at && e.occurred_at.slice(0, 10) !== e.detected_at.slice(0, 10) ? `happened ${day(e.occurred_at)} · ` : ""}found {ago(e.detected_at)}
                      {(e.related ?? 1) > 1 ? ` · ${e.related} reports` : ""}
                    </span>
                  </div>
                  <div className="mt-2.5 line-clamp-2 text-[34px] font-semibold leading-[1.18] tracking-[-0.01em] text-ink">{e.title}</div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

function Big({ label: l, value, sub, tone = "text-ink" }: { label: string; value: number; sub: string; tone?: string }) {
  const shown = useCountUp(value);
  const flash = useChanged(value);
  return (
    <div className={cx("rounded-[24px] border border-line bg-solid px-7 py-5", flash && "kiosk-flash")}>
      <div className="eyebrow !text-[19px] !font-semibold">{l}</div>
      <div className={cx("mt-2 text-[88px] font-semibold leading-none tracking-[-0.03em] tnum", tone)}>{shown}</div>
      <div className="mt-2 truncate text-[20px] text-ink-3">{sub}</div>
    </div>
  );
}

function AiShare({ ov }: { ov: Overview }) {
  const meta = useMeta();
  const share = ov.kpis.ai_share;
  const prev = ov.kpis.ai_share_prev;
  const leader = [...ov.share].sort((a, b) => b.share - a.share)[0];
  const leaderName = leader && meta.entities.find((x) => x.id === leader.id);
  const flash = useChanged(share);
  const shown = useCountUp(Math.round((share ?? 0) * 100));
  return (
    <div className={cx("flex items-center gap-8 rounded-[24px] border border-line bg-solid px-8 py-5", flash && "kiosk-flash")}>
      <div>
        <div className="eyebrow !text-[19px] !font-semibold">AI share of voice</div>
        <div className="mt-2 text-[80px] font-semibold leading-none tracking-[-0.03em] tnum text-ink">{share == null ? "-" : `${shown}%`}</div>
      </div>
      <div className="min-w-0 flex-1 space-y-2 text-[22px] text-ink-2">
        {share != null && prev != null && (
          <div className={cx("text-[26px] font-semibold", share > prev ? "text-good" : share < prev ? "text-crit" : "text-ink-3")}>
            {share === prev ? "No change" : `${share > prev ? "+" : ""}${Math.round((share - prev) * 100)} pts`} <span className="font-normal text-ink-3">since last run</span>
          </div>
        )}
        {leaderName && !leaderName.is_brand && <div className="truncate">Leader: <span className="text-ink">{leaderName.name.replace(/\s*\(.*\)/, "")}</span> at {pct(leader.share)}</div>}
        {ov.kpis.ai_gaps > 0 && <div className="truncate">{ov.kpis.ai_gaps} questions where we're missing</div>}
        {share == null && <div className="text-ink-3">No AI-search runs yet</div>}
      </div>
    </div>
  );
}

function Movers({ ov }: { ov: Overview }) {
  const rows = ov.competitors.slice(0, 4);
  const max = Math.max(1, ...rows.map((r) => r.changes));
  const flash = useChanged(rows.map((r) => [r.id, r.changes, r.critical]));
  return (
    <Panel title="Who's moving" flash={flash} className="flex-1">
      <ol className="flex min-h-0 flex-1 flex-col justify-around overflow-hidden">
        {rows.map((c) => (
          <li key={c.id} className="flex items-center gap-5">
            <Monogram id={c.id} size={40} />
            <div className="w-[230px] truncate text-[26px] text-ink">{c.name.replace(/\s*\(.*\)/, "")}</div>
            <div className="h-3 flex-1 overflow-hidden rounded-full bg-sunken">
              <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${(c.changes / max) * 100}%`, background: c.color }} />
            </div>
            <div className="w-[220px] whitespace-nowrap text-right text-[22px] tnum text-ink-2">
              {c.changes} {c.changes === 1 ? "move" : "moves"}{c.critical ? <span className="text-high"> · {c.critical} high</span> : null}
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

function Posts({ ov }: { ov: Overview }) {
  const posts = ov.recent_posts.slice(0, 3);
  if (!posts.length) return null;
  return (
    <section className="grid grid-cols-3 gap-7">
      {posts.map((p) => (
        <div key={p.id} className="flex items-start gap-5 rounded-[24px] border border-line bg-solid px-7 py-5">
          <Monogram id={p.competitor} size={44} />
          <div className="min-w-0">
            <div className="text-[19px] text-ink-3"><Name id={p.competitor} /> · new post · {ago(p.published || p.first_seen)}</div>
            <div className="mt-1.5 line-clamp-2 text-[24px] leading-snug text-ink">{p.title}</div>
          </div>
        </div>
      ))}
    </section>
  );
}

/** Full-screen announcement of a new critical or high move. */
function Takeover({ e }: { e: SignalEvent }) {
  const crit = e.severity === "critical";
  return (
    <motion.div className="absolute inset-0 z-20 grid place-items-center bg-bg/92 p-24" role="alert"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}>
      <motion.div className={cx("w-full max-w-[1500px] rounded-[32px] border-2 bg-solid p-16", crit ? "border-red/60" : "border-amber/60")}
        initial={{ y: 24, scale: 0.98 }} animate={{ y: 0, scale: 1 }} transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}>
        <div className={cx("flex items-center gap-4 text-[30px] font-semibold uppercase tracking-[0.14em]", crit ? "text-crit" : "text-high")}>
          <span className={cx("pulse-dot size-5 rounded-full", crit ? "bg-red text-red" : "bg-amber text-amber")} />New {crit ? "critical" : "high-impact"} move
        </div>
        <div className="mt-10 flex items-center gap-8">
          <Monogram id={e.competitor} size={112} />
          <div className="text-[44px] text-ink-2"><Name id={e.competitor} /></div>
        </div>
        <div className="mt-8 line-clamp-3 text-[72px] font-semibold leading-[1.1] tracking-[-0.02em] text-ink">{e.title}</div>
        {(e.so_what || e.detail) && <div className="mt-8 line-clamp-3 text-[36px] leading-snug text-ink-2">{e.so_what || e.detail}</div>}
        <div className="mono mt-10 text-[26px] text-ink-3">
          {e.occurred_at && e.occurred_at.slice(0, 10) !== e.detected_at.slice(0, 10) ? `happened ${day(e.occurred_at)} · ` : ""}found {ago(e.detected_at)}
          {(e.related ?? 1) > 1 ? ` · ${e.related} reports` : ""}
        </div>
        <motion.div className={cx("mt-12 h-2 rounded-full", crit ? "bg-red/70" : "bg-amber/70")} style={{ transformOrigin: "left" }}
          initial={{ scaleX: 1 }} animate={{ scaleX: 0 }} transition={{ duration: TAKEOVER_MS / 1000, ease: "linear" }} />
      </motion.div>
    </motion.div>
  );
}

/** A medium move slides in at the corner for a few seconds. */
function Corner({ e }: { e: SignalEvent }) {
  return (
    <motion.div className="absolute bottom-12 right-12 z-10 w-[720px] rounded-[24px] border-2 border-blue/50 bg-solid p-8 shadow-[var(--shadow-panel)]" role="status"
      initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}>
      <div className="flex items-center gap-4 text-[20px] font-semibold uppercase tracking-[0.14em] text-accent-ink">New move</div>
      <div className="mt-4 flex items-start gap-5">
        <Monogram id={e.competitor} size={56} />
        <div className="min-w-0">
          <div className="text-[22px] text-ink-3"><Name id={e.competitor} /></div>
          <div className="mt-1 line-clamp-2 text-[32px] font-semibold leading-tight text-ink">{e.title}</div>
        </div>
      </div>
    </motion.div>
  );
}

/** Fullscreen and sound state: shown while the mouse moves; the sound prompt stays until audio is allowed. */
function Controls({ active, fs, sound, now }: { active: boolean; fs: ReturnType<typeof useFullscreen>; sound: ReturnType<typeof useSound>; now: Date }) {
  const quiet = quietUntil(quietWindows(), now);
  const needsClick = sound.enabled && !sound.unlocked;
  const btn = "flex items-center gap-3 rounded-[14px] border border-line bg-solid px-5 py-3 text-[20px] text-ink-2";
  return (
    <div className={cx("absolute bottom-5 left-12 z-30 flex items-center gap-4 transition-opacity duration-500", active || needsClick ? "opacity-100" : "opacity-0")}>
      {fs.supported && active && (
        <button onClick={fs.toggle} className={cx(btn, "hover:text-ink focus-ring")} aria-label={fs.on ? "Exit full screen (F)" : "Full screen (F)"}>
          {fs.on ? <Minimize size={22} /> : <Maximize size={22} />}{fs.on ? "Exit full screen" : "Full screen"} <span className="mono text-ink-3">F</span>
        </button>
      )}
      {sound.enabled && (needsClick || active) && (
        <div className={btn} role="status">
          {needsClick || quiet ? <VolumeX size={22} /> : <Volume2 size={22} />}
          {needsClick ? "Click anywhere to allow sound" : quiet ? `Sound off until ${quiet}` : "Sound on"}
        </div>
      )}
    </div>
  );
}

function Name({ id }: { id: string }) {
  const e = useMeta().entities.find((x) => x.id === id);
  return <span className="truncate">{e?.name.replace(/\s*\(.*\)/, "") ?? id}</span>;
}

const label = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
