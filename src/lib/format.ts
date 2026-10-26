const IST = "Asia/Kolkata";

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 0) return "just now";
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
  return fmtDate(iso);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: IST });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: IST,
  });
}

export function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

/** "YYYY-MM-DD" in IST — the backend reads date filters as IST days. */
export function istDate(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: IST, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

export function currentMonthLabel(): string {
  return new Date().toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: IST });
}

export const CONTENT_TYPE_LABEL: Record<string, string> = {
  news: "News",
  review: "Review",
  "how-to": "How-to",
  listicle: "Listicle",
  comparison: "Comparison",
  deal: "Deal",
};

export const SOURCE_LABEL: Record<string, string> = {
  wp_rest: "WordPress API",
  news_sitemap: "News sitemap",
  rss: "RSS feed",
  sitemap: "Sitemap",
  html: "Homepage scan",
};

/** 1234 → "1.2K", 2_500_000 → "2.5M" (TW-Labs style). */
export function fmtViews(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}K`;
  return String(n);
}

export function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

/** Overperformance tiers, same bands as TW-Labs: <0.5x red, <1x grey, <2x green, <3x blue, 3x+ gold. */
export function ratioColor(r: number | null | undefined): string {
  if (r == null) return "var(--text-muted)";
  if (r < 0.5) return "var(--tier-danger)";
  if (r < 1) return "var(--tier-grey)";
  if (r < 2) return "var(--success)";
  if (r < 3) return "var(--tier-blue)";
  return "var(--warning)";
}

/** Fixed bright colours for the badge on top of thumbnails (dark scrim). */
export function overlayRatioColor(r: number | null | undefined): string {
  if (r == null) return "#a8adc0";
  if (r < 0.5) return "#f87171";
  if (r < 1) return "#94a3b8";
  if (r < 2) return "#4ade80";
  if (r < 3) return "#38bdf8";
  return "#facc15";
}
