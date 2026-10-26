/**
 * Fetch wrapper + types for the Web Intel API (backend/app/schemas.py).
 *
 * API_BASE is "" (same-origin: Vite dev proxy / nginx /api proxy) unless
 * VITE_API_BASE_URL is set at build time for a split deployment.
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "Can't reach the Web Intel server — is the backend running?");
  }
  if (res.status === 204) return undefined as T;
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    // Session missing or expired: App shows the login screen.
    window.dispatchEvent(new Event("webintel:unauthorized"));
  }
  if (!res.ok) {
    const detail = body?.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg).join("; ")
          : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

// ── Types ──────────────────────────────────────────────────────────────────
export type SourceKind = "wp_rest" | "news_sitemap" | "rss" | "sitemap" | "html";
export type Health = "ok" | "warning" | "error" | "pending";

export interface Source {
  id: number;
  kind: SourceKind;
  url: string;
  priority: number;
  enabled: boolean;
  last_checked_at: string | null;
  last_ok_at: string | null;
  last_item_count: number | null;
  consecutive_errors: number;
  last_error: string | null;
}

export interface Site {
  id: number;
  domain: string;
  name: string;
  home_url: string;
  cohort: string | null;
  is_own_site: boolean;
  paused: boolean;
  icon_url: string | null;
  backfill_status: "pending" | "running" | "done" | "error";
  created_at: string;
  last_poll_at: string | null;
  last_poll_ok_at: string | null;
  last_error: string | null;
  fast_source: SourceKind | null;
  health: Health;
  articles_24h: number;
  articles_7d: number;
  updates_7d: number;
  last_article_at: string | null;
  queued: number;
}

export interface SiteDetail extends Site {
  sources: Source[];
  discovery_log: string[];
}

export type ContentType = "news" | "review" | "how-to" | "listicle" | "comparison" | "deal";

export interface Article {
  id: number;
  site_id: number;
  site_name: string;
  site_domain: string;
  site_icon_url: string | null;
  url: string;
  title: string | null;
  excerpt: string | null;
  author: string | null;
  section: string | null;
  tags: string[] | null;
  content_type: ContentType | null;
  thumbnail_url: string | null;
  word_count: number | null;
  image_count: number | null;
  youtube_ids: string[] | null;
  affiliate_link_count: number | null;
  published_at: string | null;
  modified_at: string | null;
  first_seen_at: string;
  last_updated_at: string | null;
  update_count: number;
  activity_at: string | null;
  is_backfill: boolean;
  discovered_via: SourceKind | null;
  enrich_status: string;
  latest_change: string | null;
}

export interface Version {
  id: number;
  seen_at: string;
  old_title: string | null;
  new_title: string | null;
  old_word_count: number | null;
  new_word_count: number | null;
  paragraphs_added: number;
  paragraphs_removed: number;
  headings_added: string[] | null;
  headings_removed: string[] | null;
  summary: string;
}

export interface ArticleDetail extends Article {
  headings: string[] | null;
  versions: Version[];
  also_covered_by: Article[];
}

export interface ArticlePage {
  items: Article[];
  total: number;
  limit: number;
  offset: number;
}

export interface Facets {
  content_types: [string, number][];
  sections: [string, number][];
  authors: [string, number][];
  cohorts: string[];
}

export interface JobRun {
  id: number;
  job: string;
  site_id: number | null;
  started_at: string;
  finished_at: string | null;
  items_new: number;
  items_updated: number;
  items_processed: number;
  ok: boolean | null;
  error: string | null;
  trigger: string;
}

export interface SystemStatus {
  workspace_name: string;
  sites: number;
  articles_total: number;
  articles_24h: number;
  updates_24h: number;
  queue_pending: number;
  last_poll_at: string | null;
  worker_alive: boolean;
  recent_runs: JobRun[];
}

export interface ArticleQuery {
  sites?: number[];
  cohort?: string;
  date_from?: string;
  date_to?: string;
  status?: "all" | "new" | "updated";
  content_type?: string;
  section?: string;
  author?: string;
  q?: string;
  min_words?: number;
  has_youtube?: boolean;
  has_affiliate?: boolean;
  sort?: "newest" | "words" | "most_updated";
  limit?: number;
  offset?: number;
}

export function articleQueryString(q: ArticleQuery): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    if (Array.isArray(v)) {
      if (v.length) p.set(k, v.join(","));
    } else {
      p.set(k, String(v));
    }
  }
  return p.toString();
}

// ── Calls ──────────────────────────────────────────────────────────────────
export const api = {
  me: () => request<{ auth_required: boolean; authenticated: boolean }>("/api/auth/me"),
  login: (password: string) => request<{ ok: boolean }>("/api/auth/login", { method: "POST", body: JSON.stringify({ password }) }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  sites: () => request<Site[]>("/api/sites"),
  site: (id: number) => request<SiteDetail>(`/api/sites/${id}`),
  addSite: (body: { url: string; name?: string; cohort?: string; is_own_site?: boolean }) =>
    request<Site>("/api/sites", { method: "POST", body: JSON.stringify(body) }),
  updateSite: (id: number, body: Partial<Pick<Site, "name" | "cohort" | "paused" | "is_own_site">>) =>
    request<Site>(`/api/sites/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSite: (id: number) => request<void>(`/api/sites/${id}`, { method: "DELETE" }),
  rediscover: (id: number) => request<{ queued: boolean }>(`/api/sites/${id}/rediscover`, { method: "POST" }),
  pollSite: (id: number) => request<{ queued: boolean }>(`/api/sites/${id}/poll`, { method: "POST" }),
  articles: (q: ArticleQuery) => request<ArticlePage>(`/api/articles?${articleQueryString(q)}`),
  article: (id: number) => request<ArticleDetail>(`/api/articles/${id}`),
  exportUrl: (q: ArticleQuery) => `${API_BASE}/api/articles/export.csv?${articleQueryString({ ...q, limit: undefined, offset: undefined })}`,
  facets: (sites?: number[]) => request<Facets>(`/api/facets${sites?.length ? `?sites=${sites.join(",")}` : ""}`),
  status: () => request<SystemStatus>("/api/status"),
  jobs: (siteId?: number) => request<JobRun[]>(`/api/jobs${siteId != null ? `?site_id=${siteId}` : ""}`),
  refresh: () => request<{ queued: boolean }>("/api/refresh", { method: "POST" }),
};
