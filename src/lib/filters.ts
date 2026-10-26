import type { ArticleQuery } from "./api";
import { istDate } from "./format";

export type DatePreset = "today" | "3d" | "7d" | "2w" | "1m" | "custom";
export type Status = "all" | "new" | "updated";
export type Sort = "newest" | "words" | "most_updated";

export const DATE_PRESETS: { value: DatePreset; label: string; days: number | null }[] = [
  { value: "today", label: "Today", days: 0 },
  { value: "3d", label: "Last 3 days", days: 3 },
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "2w", label: "Last 2 weeks", days: 14 },
  { value: "1m", label: "Last 30 days", days: 30 },
  { value: "custom", label: "Custom range", days: null },
];

export interface Filters {
  sites: number[];
  cohort: string;
  datePreset: DatePreset;
  dateFrom: string;
  dateTo: string;
  status: Status;
  contentType: string;
  section: string;
  author: string;
  q: string;
  minWords: string;
  hasYoutube: boolean;
  hasAffiliate: boolean;
  sort: Sort;
}

export function presetToRange(preset: DatePreset): { dateFrom: string; dateTo: string } {
  const found = DATE_PRESETS.find(p => p.value === preset);
  if (found?.days == null) return { dateFrom: "", dateTo: "" };
  const to = new Date();
  const from = new Date(Date.now() - found.days * 86400_000);
  return { dateFrom: istDate(from), dateTo: istDate(to) };
}

/** Computed fresh each call so a long-open tab's "Last 3 days" doesn't drift. */
export function defaultFilters(): Filters {
  return {
    sites: [],
    cohort: "",
    datePreset: "3d",
    ...presetToRange("3d"),
    status: "all",
    contentType: "",
    section: "",
    author: "",
    q: "",
    minWords: "",
    hasYoutube: false,
    hasAffiliate: false,
    sort: "newest",
  };
}

export function toQuery(f: Filters): ArticleQuery {
  const range = f.datePreset === "custom" ? { dateFrom: f.dateFrom, dateTo: f.dateTo } : presetToRange(f.datePreset);
  return {
    sites: f.sites,
    cohort: f.cohort || undefined,
    date_from: range.dateFrom || undefined,
    date_to: range.dateTo || undefined,
    status: f.status,
    content_type: f.contentType || undefined,
    section: f.section || undefined,
    author: f.author || undefined,
    q: f.q.trim() || undefined,
    min_words: f.minWords ? Number(f.minWords) : undefined,
    has_youtube: f.hasYoutube || undefined,
    has_affiliate: f.hasAffiliate || undefined,
    sort: f.sort,
  };
}

/** Filters live in the URL so any view can be shared as a link. */
export function filtersToSearch(f: Filters): string {
  const d = defaultFilters();
  const p = new URLSearchParams();
  if (f.sites.length) p.set("sites", f.sites.join(","));
  if (f.cohort) p.set("cohort", f.cohort);
  if (f.datePreset !== d.datePreset) p.set("range", f.datePreset);
  if (f.datePreset === "custom") {
    if (f.dateFrom) p.set("from", f.dateFrom);
    if (f.dateTo) p.set("to", f.dateTo);
  }
  if (f.status !== "all") p.set("status", f.status);
  if (f.contentType) p.set("type", f.contentType);
  if (f.section) p.set("section", f.section);
  if (f.author) p.set("author", f.author);
  if (f.q) p.set("q", f.q);
  if (f.minWords) p.set("minWords", f.minWords);
  if (f.hasYoutube) p.set("yt", "1");
  if (f.hasAffiliate) p.set("aff", "1");
  if (f.sort !== "newest") p.set("sort", f.sort);
  return p.toString();
}

export function searchToFilters(search: string): Filters {
  const p = new URLSearchParams(search);
  const f = defaultFilters();
  const sites = p.get("sites");
  if (sites) f.sites = sites.split(",").map(Number).filter(n => Number.isFinite(n) && n > 0);
  f.cohort = p.get("cohort") ?? "";
  const range = p.get("range") as DatePreset | null;
  if (range && DATE_PRESETS.some(x => x.value === range)) {
    f.datePreset = range;
    Object.assign(f, range === "custom" ? { dateFrom: p.get("from") ?? "", dateTo: p.get("to") ?? "" } : presetToRange(range));
  }
  const status = p.get("status");
  if (status === "new" || status === "updated") f.status = status;
  f.contentType = p.get("type") ?? "";
  f.section = p.get("section") ?? "";
  f.author = p.get("author") ?? "";
  f.q = p.get("q") ?? "";
  f.minWords = p.get("minWords") ?? "";
  f.hasYoutube = p.get("yt") === "1";
  f.hasAffiliate = p.get("aff") === "1";
  const sort = p.get("sort");
  if (sort === "words" || sort === "most_updated") f.sort = sort;
  return f;
}

export function activeFilterCount(f: Filters): number {
  const d = defaultFilters();
  let n = 0;
  if (f.sites.length) n++;
  if (f.cohort) n++;
  if (f.status !== d.status) n++;
  if (f.contentType) n++;
  if (f.section) n++;
  if (f.author) n++;
  if (f.q) n++;
  if (f.minWords) n++;
  if (f.hasYoutube) n++;
  if (f.hasAffiliate) n++;
  return n;
}
