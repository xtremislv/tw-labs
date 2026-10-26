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
