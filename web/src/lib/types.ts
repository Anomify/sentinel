export type Severity = "critical" | "high" | "medium" | "low" | "noise";

export interface Entity {
  id: string; name: string; color: string; tier: string; domains: string[]; aliases: string[]; is_brand: boolean;
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
}

export interface Change {
  id: number; competitor: string; url: string; kind: string; detected_at: string;
  severity: Severity; category: string; headline: string; summary: string;
  so_what: string | null; action: string | null; added: string[]; removed: string[];
  signals: Record<string, any>; change_ratio: number; acknowledged: number;
}

export interface ChangeDetail extends Change {
  before: { fetched_at: string; title: string; meta: string } | null;
  after: { fetched_at: string; title: string; meta: string } | null;
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
    ai_share: number | null; ai_share_prev: number | null; ai_gaps: number; pages: number; feeds: number; questions: number;
  };
  competitors: {
    id: string; name: string; color: string; tier: string; changes: number; critical: number; posts: number;
    heat: number; heat_delta: number; last_checked: string | null; ai_share: number | null; latest: Change | null;
  }[];
  timeline: ({ date: string } & Record<string, number | string>)[];
  top_changes: Change[];
  recent_posts: Post[];
  share: Share[];
  last_run: { job: string; finished_at: string; status: string } | null;
}

export interface Visibility {
  runs: { run_id: string; run_at: string; answers: number; engines: string }[];
  latest: { run_id: string; run_at: string } | null;
  engines: string[];
  share: Share[];
  per_engine: Record<string, Share[]>;
  matrix: { id: string; text: string; category: string; cells: Record<string, Record<string, number | null>> }[];
  trend: ({ run_id: string; date: string } & Record<string, number | string>)[];
  citations: { domain: string; count: number }[];
  gaps: { id: string; text: string; category: string; competitors: string[] }[];
}

export interface AiAnswer {
  id: number; engine: string; model: string; question: string; answer: string; run_at: string;
  citations: { url: string; title: string | null }[];
  mentions: Record<string, { mentioned: boolean; rank: number | null; count: number; cited: number }>;
  error: string | null;
}

export interface Run { id: number; job: string; started_at: string; finished_at: string | null; status: string; stats: any; error: string | null }
