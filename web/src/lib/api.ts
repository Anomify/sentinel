import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

const TOKEN_KEY = "sentinel-token";
const cache = new Map<string, unknown>();
let version = 0;
const listeners = new Set<() => void>();

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
export function setToken(t: string) {
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ }
  invalidate();
}

export class AuthError extends Error {}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const t = getToken();
  const res = await fetch(path, { ...init, headers: { ...(t ? { Authorization: `Bearer ${t}` } : {}), ...init?.headers } });
  if (res.status === 401) throw new AuthError("unauthorized");
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

/** Bump the global version: every mounted useApi refetches (stale-while-revalidate). */
export function invalidate() {
  version++;
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => { listeners.add(l); return () => listeners.delete(l); };

export function useApi<T>(path: string | null) {
  const v = useSyncExternalStore(subscribe, () => version);
  const [data, setData] = useState<T | undefined>(() => (path ? (cache.get(path) as T) : undefined));
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(!data);
  const current = useRef(path);
  current.current = path;

  const load = useCallback(() => {
    if (!path) return;
    if (cache.has(path)) setData(cache.get(path) as T);
    setLoading(!cache.has(path));
    api<T>(path)
      .then((d) => { cache.set(path, d); if (current.current === path) { setData(d); setError(null); } })
      .catch((e) => current.current === path && setError(e))
      .finally(() => current.current === path && setLoading(false));
  }, [path]);

  useEffect(load, [load, v]);
  return { data, error, loading, reload: load };
}

export async function runJob(job: string, opts: { deliver?: boolean } = {}) {
  const q = opts.deliver === false ? "?deliver=false" : "";
  return api<{ status: string }>(`/api/jobs/${job}${q}`, { method: "POST" });
}
