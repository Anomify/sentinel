import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

const WS_KEY = "sentinel-ws";
const tokenKey = (ws: string) => `sentinel-token:${ws}`;
const cache = new Map<string, unknown>();
let version = 0;
const listeners = new Set<() => void>();

const read = (k: string) => { try { return localStorage.getItem(k) || ""; } catch { return ""; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } };

export const workspace = () => read(WS_KEY) || "default";
export function setWorkspace(ws: string) {
  write(WS_KEY, ws);
  cache.clear();
  invalidate();
}
export const getToken = () => read(tokenKey(workspace())) || read("sentinel-token");
export function setToken(t: string) {
  write(tokenKey(workspace()), t);
  invalidate();
}

/** A screen set up once and left alone (the office TV) can be given its token in the address: `/tv?token=…`.
 *  It is saved like a typed-in token and removed from the address bar at once, so it isn't left on screen or in history. */
export function captureTokenFromUrl() {
  const url = new URL(window.location.href);
  const t = url.searchParams.get("token");
  if (!t) return;
  write(tokenKey(workspace()), t);
  url.searchParams.delete("token");
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
}

/** Query string for URLs the browser loads itself (images, frames, downloads): those can't send the headers api() does. */
export function authQuery() {
  const t = getToken();
  return new URLSearchParams({ ws: workspace(), ...(t ? { token: t } : {}) }).toString();
}

export class AuthError extends Error {}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const t = getToken();
  const res = await fetch(path, {
    ...init,
    headers: { "X-Workspace": workspace(), ...(t ? { Authorization: `Bearer ${t}` } : {}), ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
  });
  if (res.status === 401) throw new AuthError("unauthorized");
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).detail ?? msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

/** Bump the global version: every mounted useApi refetches (stale-while-revalidate). */
export function invalidate() {
  version++;
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => { listeners.add(l); return () => listeners.delete(l); };

export function useApi<T>(path: string | null, opts: { poll?: number } = {}) {
  const v = useSyncExternalStore(subscribe, () => version);
  const key = path ? `${workspace()}|${path}` : null;
  const [data, setData] = useState<T | undefined>(() => (key ? (cache.get(key) as T) : undefined));
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(!data);
  const current = useRef(key);
  current.current = key;

  const load = useCallback(() => {
    if (!path || !key) return;
    if (cache.has(key)) setData(cache.get(key) as T);
    setLoading(!cache.has(key));
    api<T>(path)
      .then((d) => { cache.set(key, d); if (current.current === key) { setData(d); setError(null); } })
      .catch((e) => current.current === key && setError(e))
      .finally(() => current.current === key && setLoading(false));
  }, [path, key]);

  useEffect(load, [load, v]);
  useEffect(() => {
    if (!opts.poll) return;
    const t = window.setInterval(load, opts.poll);
    return () => window.clearInterval(t);
  }, [load, opts.poll]);
  return { data, error, loading, reload: load };
}

export async function runJob(job: string, opts: { deliver?: boolean } = {}) {
  const q = opts.deliver === false ? "?deliver=false" : "";
  return api<{ status: string }>(`/api/jobs/${job}${q}`, { method: "POST" });
}
