import { useCallback, useEffect, useRef, useState } from "react";
import type { Severity, SignalEvent } from "./types";

/* Helpers for the office TV view (/tv): a read-only screen left running for weeks. */

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ── Quiet hours ─────────────────────────────────────────────────────────────
   Sounds stay off during these windows (visuals carry on). Default: Tuesday and Wednesday 10:00–10:45, local time.
   Override in the address: ?quiet=tue,wed@10:00-10:45;fri@16:00-17:00  ·  ?quiet=off  ·  ?sound=off (never play). */
type Window = { days: number[]; from: number; to: number };
const DAY = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const mins = (hhmm: string) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + (m || 0); };

export function quietWindows(search = window.location.search): Window[] {
  const q = new URLSearchParams(search).get("quiet") ?? "tue,wed@10:00-10:45";
  if (q === "off") return [];
  return q.split(";").flatMap((part) => {
    const m = part.trim().match(/^([a-z,]+)@(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$/i);
    if (!m) return [];
    const days = m[1].toLowerCase().split(",").map((d) => DAY.indexOf(d.slice(0, 3))).filter((d) => d >= 0);
    return days.length ? [{ days, from: mins(m[2]), to: mins(m[3]) }] : [];
  });
}

/** The quiet window in force now, if any, as "until 10:45". */
export function quietUntil(windows: Window[], now = new Date()): string | null {
  const t = now.getHours() * 60 + now.getMinutes();
  const w = windows.find((x) => x.days.includes(now.getDay()) && t >= x.from && t < x.to);
  return w ? `${String(Math.floor(w.to / 60)).padStart(2, "0")}:${String(w.to % 60).padStart(2, "0")}` : null;
}

/* ── Sounds ──────────────────────────────────────────────────────────────────
   A distinct cue per severity, synthesised so nothing needs installing. Drop your own critical.mp3 / high.mp3 /
   medium.mp3 into web/public/kiosk-sounds/ and they are used instead. Browsers start audio muted until the page
   is clicked once, unless Chrome runs with --autoplay-policy=no-user-gesture-required. */
type Cue = "critical" | "high" | "medium";
const TONES: Record<Cue, { notes: number[]; step: number; repeat: number; gain: number }> = {
  critical: { notes: [659.25, 783.99, 1046.5], step: 0.16, repeat: 2, gain: 0.32 },  // E5 G5 C6, twice: rising, urgent
  high: { notes: [523.25, 783.99], step: 0.2, repeat: 1, gain: 0.26 },                // C5 G5: a two-note chime
  medium: { notes: [880], step: 0.18, repeat: 1, gain: 0.14 },                        // A5: one soft tick
};

export function useSound() {
  const ctx = useRef<AudioContext | null>(null);
  const files = useRef<Partial<Record<Cue, string>>>({});
  const [unlocked, setUnlocked] = useState(false);
  const enabled = new URLSearchParams(window.location.search).get("sound") !== "off";

  useEffect(() => {
    if (!enabled) return;
    const AC = window.AudioContext || (window as any).webkitAudioContext;
    if (!AC) return;
    const c: AudioContext = new AC();
    ctx.current = c;
    const sync = () => setUnlocked(c.state === "running");
    c.onstatechange = sync;
    sync();
    // Any click or key resumes audio (the browser's autoplay rule needs one gesture).
    const resume = () => { c.resume().then(sync).catch(() => {}); };
    window.addEventListener("pointerdown", resume);
    window.addEventListener("keydown", resume);
    // Custom sounds: a missing file is answered with the dashboard page, so only real audio counts.
    for (const cue of Object.keys(TONES) as Cue[]) {
      const url = `/kiosk-sounds/${cue}.mp3`;  // GET: the server answers HEAD with 405
      fetch(url).then((r) => { if (r.ok && (r.headers.get("content-type") || "").startsWith("audio/")) files.current[cue] = url; }).catch(() => {});
    }
    return () => { window.removeEventListener("pointerdown", resume); window.removeEventListener("keydown", resume); c.close().catch(() => {}); };
  }, [enabled]);

  const play = useCallback((sev: Severity | string) => {
    const cue: Cue | null = sev === "critical" ? "critical" : sev === "high" ? "high" : sev === "medium" ? "medium" : null;
    const c = ctx.current;
    if (!cue || !c || c.state !== "running" || quietUntil(quietWindows())) return;
    if (files.current[cue]) { new Audio(files.current[cue]).play().catch(() => {}); return; }
    const t = TONES[cue];
    let at = c.currentTime + 0.02;
    for (let r = 0; r < t.repeat; r++) {
      for (const f of t.notes) {
        const o = c.createOscillator(), g = c.createGain();
        o.type = "triangle";
        o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, at);
        g.gain.exponentialRampToValueAtTime(t.gain, at + 0.015);
        g.gain.exponentialRampToValueAtTime(0.0001, at + t.step * 2.2);
        o.connect(g).connect(c.destination);
        o.start(at);
        o.stop(at + t.step * 2.4);
        at += t.step;
      }
      at += 0.25;
    }
  }, []);

  return { play, unlocked, enabled };
}

/* ── New moves ───────────────────────────────────────────────────────────────
   Which moves this screen has already announced, kept across reloads so a restart or deploy doesn't replay them.
   The first time the screen ever runs, everything already there counts as seen: no wall of alerts on day one. */
const SEEN_KEY = "sentinel-kiosk-seen";
export const moveKey = (e: SignalEvent) => `${e.competitor}|${e.story ?? e.id}`;

export function useNewMoves(events: SignalEvent[] | undefined, onNew: (fresh: SignalEvent[]) => void) {
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!events) return;
    if (!seen.current) {
      let stored: string[] | null = null;
      try { stored = JSON.parse(localStorage.getItem(SEEN_KEY) || "null"); } catch { /* unreadable: start fresh */ }
      seen.current = new Set(stored ?? []);
      if (!stored) {  // first run on this screen: take what's there as already seen
        events.forEach((e) => seen.current!.add(moveKey(e)));
        save(seen.current);
        return;
      }
    }
    const fresh = events.filter((e) => !seen.current!.has(moveKey(e)));
    if (!fresh.length) return;
    fresh.forEach((e) => seen.current!.add(moveKey(e)));
    save(seen.current);
    onNew(fresh);
  }, [events]); // eslint-disable-line react-hooks/exhaustive-deps
}
function save(s: Set<string>) {
  try { localStorage.setItem(SEEN_KEY, JSON.stringify([...s].slice(-3000))); } catch { /* storage full or blocked */ }
}

/* ── Screen utilities ────────────────────────────────────────────────────── */

/** True while the mouse has moved in the last `ms`: the cursor and on-screen controls hide after that. */
export function useActivity(ms = 3000) {
  const [active, setActive] = useState(true);
  useEffect(() => {
    let t = window.setTimeout(() => setActive(false), ms);
    const wake = () => { setActive(true); window.clearTimeout(t); t = window.setTimeout(() => setActive(false), ms); };
    window.addEventListener("mousemove", wake);
    window.addEventListener("pointerdown", wake);
    return () => { window.clearTimeout(t); window.removeEventListener("mousemove", wake); window.removeEventListener("pointerdown", wake); };
  }, [ms]);
  return active;
}

/** Native fullscreen, toggled by a button or the F key. */
export function useFullscreen() {
  const [on, setOn] = useState(!!document.fullscreenElement);
  const toggle = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen().catch(() => {});
  }, []);
  useEffect(() => {
    const sync = () => setOn(!!document.fullscreenElement);
    const key = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "f" && !e.metaKey && !e.ctrlKey && !e.altKey && !(e.target as HTMLElement)?.closest?.("input, textarea")) toggle();
    };
    document.addEventListener("fullscreenchange", sync);
    window.addEventListener("keydown", key);
    return () => { document.removeEventListener("fullscreenchange", sync); window.removeEventListener("keydown", key); };
  }, [toggle]);
  return { on, toggle, supported: !!document.documentElement.requestFullscreen };
}

/** Keep the display awake (Screen Wake Lock), re-taken whenever the page becomes visible again. */
export function useWakeLock() {
  useEffect(() => {
    let lock: any = null;
    const take = () => { if (document.visibilityState === "visible") (navigator as any).wakeLock?.request("screen").then((l: any) => { lock = l; }).catch(() => {}); };
    take();
    document.addEventListener("visibilitychange", take);
    return () => { document.removeEventListener("visibilitychange", take); lock?.release?.().catch?.(() => {}); };
  }, []);
}

/** Reload once a day at `hour` local time: a browser left open for weeks stays quick. */
export function useDailyReload(hour = 4) {
  useEffect(() => {
    const next = new Date();
    next.setHours(hour, 0, 0, 0);
    if (next.getTime() <= Date.now()) next.setDate(next.getDate() + 1);
    const t = window.setTimeout(() => window.location.reload(), next.getTime() - Date.now());
    return () => window.clearTimeout(t);
  }, [hour]);
}

/** Re-render every `ms` so clocks and "5 min ago" stay true. */
export function useNow(ms = 15_000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const t = window.setInterval(() => setNow(new Date()), ms); return () => window.clearInterval(t); }, [ms]);
  return now;
}

/** Counts up (or down) to a new value over ~0.7 s, so a change is seen as movement. */
export function useCountUp(value: number) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const start = from.current;
    from.current = value;
    if (start === value || reducedMotion()) { setShown(value); return; }
    let raf = 0;
    const t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / 700);
      const eased = 1 - Math.pow(1 - k, 3);
      setShown(Math.round(start + (value - start) * eased));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return shown;
}

/** True for ~1.6 s after `value` changes (not on first render): drives the "this just changed" pulse. */
export function useChanged(value: unknown) {
  const [flash, setFlash] = useState(false);
  const prev = useRef(JSON.stringify(value));
  useEffect(() => {
    const v = JSON.stringify(value);
    if (v === prev.current) return;
    prev.current = v;
    setFlash(true);
    const t = window.setTimeout(() => setFlash(false), 1600);
    return () => window.clearTimeout(t);
  }, [value]);
  return flash;
}
