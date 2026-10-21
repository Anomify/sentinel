export type Severity = "critical" | "high" | "medium" | "low" | "noise";

export interface Entity {
  id: string; name: string; color: string; tier: string; domains: string[]; aliases: string[]; is_brand: boolean; source?: string;
  pages: { kind: string; url: string; focus?: string | null }[];
  feeds: { type: string; url: string; filter?: string | null; link_pattern?: string | null }[];
}

export interface Meta {
  brand: { name: string; color: string; domains: string[] };
  entities: Entity[];
  watch_terms: string[];
  questions: { id: string; text: string; category: string }[];
  engines: { id: string; model: string; enabled: boolean; has_key: boolean }[];
  channels: { slack: boolean; email: boolean };
  analysis: boolean;
  schedule: { job: string; spec: string; last: string | null; next: string | null; running: boolean }[];
  demo: boolean;
  counts: Record<string, number>;
  auth: boolean;
  workspace: string;
  workspaces: { slug: string; name: string }[];
  backend: string;
  policy: { title: string; detail: string }[];
  modules: Record<string, string>;
}

export interface Change {
  id: number; competitor: string; url: string; kind: string; detected_at: string;
  severity: Severity; category: string; headline: string; summary: string;
  so_what: string | null; action: string | null; added: string[]; removed: string[];
  signals: Record<string, any>; change_ratio: number; acknowledged: number;
}

export interface ChangeDetail extends Change {
  before: { fetched_at: string; title: string; meta: string; screenshot?: string } | null;
  after: { fetched_at: string; title: string; meta: string; screenshot?: string } | null;
  diff: { t: "eq" | "add" | "del" | "gap"; s: string }[];
}

export interface Post {
  id: number; competitor: string; title: string; url: string; published: string | null;
  summary: string; first_seen: string; topics: string[];
}

export interface Share { id: string; share: number; mentions: number; avg_rank: number | null; top3: number; cited: number }

export interface Overview {
  days: number;
  kpis: {
    changes: number; critical: number; pricing: number; posts: number; changes_prev: number;
    ai_share: number | null; ai_share_prev: number | null; ai_gaps: number; pages: number; feeds: number; questions: number; launch_indicators: number; facts: number;
  };
  competitors: {
    id: string; name: string; color: string; tier: string; changes: number; critical: number; posts: number;
    heat: number; heat_delta: number; ai_share: number | null; latest: SignalEvent | null; launch: number; modules: Record<string, number>;
  }[];
  timeline: ({ date: string } & Record<string, number | string>)[];
  top_events: SignalEvent[];
  by_module: Record<string, number>;
  launch: Record<string, Launch>;
  recent_posts: Post[];
  share: Share[];
  last_run: { job: string; finished_at: string; status: string } | null;
  health: Health;
}

/** Whether "nothing changed" can be trusted: module freshness and companies a module couldn't read. */
export interface Health {
  status: "ok" | "degraded";
  modules: { job: string; label: string; spec: string; last_ok: string | null; last_error: string | null; status: "ok" | "stale" | "error" }[];
  issues: { competitor: string; name: string; job: string; label: string; status: "error" | "partial"; detail: string }[];
  stale: string[];
  failing: string[];
}

export interface Visibility {
  runs: { run_id: string; run_at: string; answers: number; errors: number; questions: number; complete: boolean; engines: string }[];
  latest: { run_id: string; run_at: string; answers: number; errors: number; complete: boolean; measured: number;
    no_answer: number; branded_excluded: string[]; samples?: number } | null;
  spread?: Record<string, { min: number; max: number }>; // share range across repeated samples (settings ai.samples > 1)
  engines: string[];
  share: Share[];
  per_engine: Record<string, Share[]>;
  matrix: { id: string; text: string; category: string; cells: Record<string, Record<string, number | null>> }[];
  trend: ({ run_id: string; date: string } & Record<string, number | string>)[];
  citations: { domain: string; count: number }[];
  source_gaps: { domain: string; count: number }[];
  accuracy: { score: number; n: number; verdicts: Record<string, number>; issues: string[] } | null;
  gaps: { id: string; text: string; category: string; competitors: string[] }[];
}

export interface AiAnswer {
  id: number; engine: string; model: string; question: string; answer: string; run_at: string;
  citations: { url: string; title: string | null }[];
  mentions: Record<string, { mentioned: boolean; rank: number | null; count: number; cited: number }>;
  error: string | null;
}

export interface Run { id: number; job: string; started_at: string; finished_at: string | null; status: string; stats: any; error: string | null }

export interface Evidence { url?: string | null; observed_at?: string; method?: string; note?: string; screenshot?: string }

export interface SignalEvent {
  id: number; competitor: string; module: string; kind: string; severity: Severity; title: string; detail: string | null;
  so_what: string | null; confidence: string; evidence: Evidence[]; data: Record<string, any>; detected_at: string;
  occurred_at?: string | null; // when it happened (article / release date), if known; detected_at is when Sentinel found it
  rating?: number | null; // 1 useful, -1 not useful (reader's verdict, used by `sentinel evaluate`)
  story?: string | null; // reports of one move share a story key (grouped into one signal)
  related?: number; // reports of the same move this signal stands for (syndicated copies, coverage of one round)
  reports?: { id: number; title: string; severity: Severity; detected_at: string; occurred_at: string | null; evidence: Evidence[] }[];
  acknowledged: number; change_id: number | null; change?: ChangeDetail;
}

export interface Fact {
  id: number; competitor: string; module: string; kind: string; key: string; label: string; value: Record<string, any>;
  confidence: string; evidence: Evidence[]; first_seen: string; last_seen: string; removed_at: string | null;
}

export interface Finding {
  id: string; section: string; title: string; detail: string; confidence: string; evidence: Evidence[];
  vs_us: string | null; vs_us_by?: string; first_seen: string | null; data: Record<string, any>; weight: number;
}
export interface DeepDive {
  competitor: string; name: string; domain: string; generated_at: string;
  profile_as_of?: string | null; // date the Hyperfence profile behind every "Vs. us" was last checked
  summary: { label: string; value: string }[]; sections: { id: string; title: string; findings: Finding[] }[];
  counts: Record<string, number>;
}
/** Pre-launch indicators: evidence count and the signals themselves. `probability` is an unvalidated internal score: never show it. */
export interface Launch { probability: number; signals: { signal: string; title: string; at: string; weight: number }[]; n: number; kinds?: Record<string, number> }
