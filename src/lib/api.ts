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
  own_clicks_28d?: number | null;
  own_impressions_28d?: number | null;
  own_position?: number | null;
  own_views_28d?: number | null;
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

export interface SitemapCheck {
  index_url: string | null;
  error?: string;
  latest_day?: string | null;
  added_now?: number;
  children: { url: string; lastmod: string | null; urls: number; latest_day_urls: number; tracked: number; visible: number; day?: string; error?: string; missing: { url: string; reason: string }[] }[];
}

// ── YouTube (Phase 3) ──────────────────────────────────────────────────────
export interface Channel {
  id: number;
  external_id: string;
  handle: string;
  name: string;
  avatar_url: string | null;
  subscriber_count: number | null;
  cohort: string | null;
  site_id: number | null;
  site_name: string | null;
  is_active: boolean;
  track_posts: boolean;
  created_at: string;
  last_scraped_at: string | null;
  posts_scraped_at: string | null;
  last_error: string | null;
  video_count: number;
  median_views_last10: number | null;
  last_published_at: string | null;
}

export interface Video {
  id: string;
  channel_id: number;
  channel_name: string;
  channel_avatar_url: string | null;
  title: string;
  thumbnail_url: string | null;
  url: string;
  views: number;
  likes: number | null;
  comments: number | null;
  published_at: string;
  duration_seconds: number;
  format: "long" | "short";
  avg_views_baseline: number | null;
  overperform_ratio: number | null;
  median_views_baseline: number | null;
  overperform_ratio_median: number | null;
  has_sponsor_segment: boolean;
  sponsor_segment_seconds: number | null;
  h1_views: number | null;
  h1_ratio: number | null;
  h3_views: number | null;
  h3_ratio: number | null;
  h6_views: number | null;
  h6_ratio: number | null;
  embedded_in: number;
}

export interface VideoPage {
  items: Video[];
  total: number;
  overperform_count: number;
  limit: number;
  offset: number;
}

export interface Post {
  id: string;
  channel_id: number;
  channel_name: string;
  channel_avatar_url: string | null;
  post_type: string | null;
  text: string | null;
  url: string | null;
  image_url: string | null;
  video_id: string | null;
  poll_options: string[] | null;
  likes: number | null;
  comments: number | null;
  published_text: string | null;
  published_at: string | null;
  first_seen_at: string;
}

export interface YouTubeStatus {
  api_key_set: boolean;
  apify_set: boolean;
  quota_used_today: number;
  quota_budget: number;
  apify_posts_today: number;
  channels: number;
  videos: number;
  posts: number;
  last_scrape_at: string | null;
  last_posts_at: string | null;
  overperform_threshold: number;
}

export interface VideoQuery {
  channels?: number[];
  cohort?: string;
  date_from?: string;
  date_to?: string;
  views_threshold?: number;
  format?: "all" | "long" | "short";
  sort_by?: "ratio" | "views" | "date" | "engagement" | "velocity";
  metric?: "average" | "median";
  has_sponsor?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

// ── Phase 4 ────────────────────────────────────────────────────────────────
export interface StoryVideo {
  id: string;
  title: string;
  channel_name: string;
  views: number;
  ratio: number | null;
  published_at: string;
  thumbnail_url: string | null;
}

export interface Story {
  key: string;
  label: string;
  terms: string[];
  site_count: number;
  competitor_site_count: number;
  article_count: number;
  first_at: string;
  last_at: string;
  hours_to_3_sites: number | null;
  covered_by_us: boolean | null;
  gap: boolean | null;
  score: number;
  sites: { id: number; name: string; icon_url: string | null; is_own_site: boolean }[];
  articles: Article[];
  videos: StoryVideo[];
  shortlisted: boolean;
}

export interface Radar {
  stories: Story[];
  total: number;
  gaps: number;
  own_site_configured: boolean;
  window_hours: number;
}

export type ShortStatus = "idea" | "assigned" | "in_progress" | "published" | "dropped";

export interface ShortlistItem {
  id: number;
  kind: "article" | "story" | "video" | "post" | "idea";
  ref_id: string | null;
  title: string;
  url: string | null;
  source: string | null;
  status: ShortStatus;
  owner: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertRule {
  id: number;
  name: string;
  kind: "article" | "video";
  keywords: string[] | null;
  site_ids: number[] | null;
  channel_ids: number[] | null;
  content_types: string[] | null;
  include_updates: boolean;
  min_ratio: number | null;
  destinations: ("slack" | "telegram")[];
  enabled: boolean;
  created_at: string;
  last_fired_at: string | null;
  fire_count: number;
}

export type AlertRuleInput = Omit<AlertRule, "id" | "created_at" | "last_fired_at" | "fire_count" | "keywords" | "site_ids" | "channel_ids" | "content_types"> & {
  keywords: string[];
  site_ids: number[];
  channel_ids: number[];
  content_types: string[];
};

export interface Integrations {
  slack: boolean;
  telegram: boolean;
  youtube: boolean;
  apify: boolean;
  search_console: boolean;
  ga4: boolean;
  digest_enabled: boolean;
  digest_time_ist: string;
  digest_last_sent: string | null;
  benchmark_last_sync: { at: string; matched: number; gsc_pages: number; ga4_pages: number } | null;
  dashboard_url: string;
}

function qs(o: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
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
  sitemapCheck: (id: number) => request<SitemapCheck>(`/api/sites/${id}/sitemap-check`, { method: "POST" }),
  pollSite: (id: number) => request<{ queued: boolean }>(`/api/sites/${id}/poll`, { method: "POST" }),
  articles: (q: ArticleQuery) => request<ArticlePage>(`/api/articles?${articleQueryString(q)}`),
  article: (id: number) => request<ArticleDetail>(`/api/articles/${id}`),
  exportUrl: (q: ArticleQuery) => `${API_BASE}/api/articles/export.csv?${articleQueryString({ ...q, limit: undefined, offset: undefined })}`,
  facets: (sites?: number[]) => request<Facets>(`/api/facets${sites?.length ? `?sites=${sites.join(",")}` : ""}`),
  status: () => request<SystemStatus>("/api/status"),
  jobs: (siteId?: number) => request<JobRun[]>(`/api/jobs${siteId != null ? `?site_id=${siteId}` : ""}`),
  refresh: () => request<{ queued: boolean }>("/api/refresh", { method: "POST" }),

  // YouTube
  ytStatus: () => request<YouTubeStatus>("/api/youtube/status"),
  channels: () => request<Channel[]>("/api/youtube/channels"),
  addChannel: (body: { handle: string; cohort?: string; site_id?: number | null }) =>
    request<Channel>("/api/youtube/channels", { method: "POST", body: JSON.stringify(body) }),
  updateChannel: (id: number, body: Partial<{ cohort: string; site_id: number | null; clear_site: boolean; is_active: boolean; track_posts: boolean }>) =>
    request<Channel>(`/api/youtube/channels/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteChannel: (id: number) => request<void>(`/api/youtube/channels/${id}`, { method: "DELETE" }),
  videos: (q: VideoQuery) => request<VideoPage>(`/api/youtube/videos${qs(q as Record<string, unknown>)}`),
  videosByIds: (ids: string[]) => request<Video[]>(`/api/youtube/videos/by-ids?ids=${ids.join(",")}`),
  videoArticles: (id: string) => request<Article[]>(`/api/youtube/videos/${encodeURIComponent(id)}/articles`),
  posts: (q: { channels?: number[]; days?: number; q?: string }) => request<Post[]>(`/api/youtube/posts${qs(q)}`),
  ytRefresh: (posts = false) => request<{ queued: boolean }>(`/api/youtube/refresh${posts ? "?posts=true" : ""}`, { method: "POST" }),

  // Phase 4
  radar: (q: { hours?: number; min_sites?: number; gaps_only?: boolean; cohort?: string; q?: string }) => request<Radar>(`/api/radar${qs(q)}`),
  shortlist: () => request<ShortlistItem[]>("/api/shortlist"),
  addShortlist: (body: { kind: ShortlistItem["kind"]; ref_id?: string | null; title: string; url?: string | null; source?: string | null; notes?: string | null }) =>
    request<ShortlistItem>("/api/shortlist", { method: "POST", body: JSON.stringify(body) }),
  updateShortlist: (id: number, body: Partial<Pick<ShortlistItem, "status" | "owner" | "notes" | "title">>) =>
    request<ShortlistItem>(`/api/shortlist/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteShortlist: (id: number) => request<void>(`/api/shortlist/${id}`, { method: "DELETE" }),
  rules: () => request<AlertRule[]>("/api/alerts/rules"),
  addRule: (body: AlertRuleInput) => request<AlertRule>("/api/alerts/rules", { method: "POST", body: JSON.stringify(body) }),
  updateRule: (id: number, body: AlertRuleInput) => request<AlertRule>(`/api/alerts/rules/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRule: (id: number) => request<void>(`/api/alerts/rules/${id}`, { method: "DELETE" }),
  integrations: () => request<Integrations>("/api/integrations"),
  testAlert: (dest: "slack" | "telegram") => request<{ ok: boolean }>(`/api/alerts/test?dest=${dest}`, { method: "POST" }),
  digestPreview: () => request<{ title: string; lines: string[] }>("/api/digest/preview"),
  digestSend: () => request<{ ok: boolean }>("/api/digest/send", { method: "POST" }),
  benchmarkSync: () => request<{ matched?: number; skipped?: string }>("/api/benchmark/sync", { method: "POST" }),
};
