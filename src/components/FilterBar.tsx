import { useEffect, useRef, useState } from "react";
import type { Facets, Site } from "../lib/api";
import { CONTENT_TYPE_LABEL } from "../lib/format";
import { DATE_PRESETS, type DatePreset, type Filters, presetToRange } from "../lib/filters";
import { ChevronDown, DownloadIcon, GridIcon, ListIcon, SearchIcon, XIcon } from "./icons";
import { SiteIcon } from "./SiteIcon";

export type ViewMode = "grid" | "list";

interface Props {
  filters: Filters;
  setFilters: (f: Filters) => void;
  sites: Site[];
  facets: Facets | null;
  viewMode: ViewMode;
  setViewMode: (v: ViewMode) => void;
  shownCount: number;
  total: number;
  exportHref: string;
  searchRef: React.RefObject<HTMLInputElement | null>;
}

export function FilterBar({ filters, setFilters, sites, facets, viewMode, setViewMode, shownCount, total, exportHref, searchRef }: Props) {
  const [siteOpen, setSiteOpen] = useState(false);
  const [more, setMore] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState(filters.q);

  useEffect(() => setQ(filters.q), [filters.q]);
  // Debounce the search box so typing doesn't fire a request per keystroke.
  useEffect(() => {
    if (q === filters.q) return;
    const t = setTimeout(() => setFilters({ ...filters, q }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setSiteOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const toggleSite = (id: number) =>
    setFilters({ ...filters, sites: filters.sites.includes(id) ? filters.sites.filter(s => s !== id) : [...filters.sites, id] });

  const hasMore = !!(filters.section || filters.author || filters.minWords || filters.hasAffiliate);

  return (
    <div className="sticky top-0 z-30 px-5 py-3 flex flex-col gap-2" style={{ background: "var(--surface-translucent)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--border)" }}>
      <div className="flex flex-wrap items-center gap-2">
        {/* Search */}
        <div className="relative shrink-0">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "var(--text-muted)" }}><SearchIcon /></span>
          <input
            ref={searchRef}
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === "Escape") { setQ(""); (e.target as HTMLInputElement).blur(); } }}
            placeholder="Search headlines…"
            aria-label="Search articles"
            className="select-custom text-xs w-52"
            style={{ paddingLeft: 28, paddingRight: 44 }}
          />
          <span className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none hidden sm:inline"><kbd>Ctrl K</kbd></span>
        </div>

        {/* Status */}
        <div className="flex rounded-lg overflow-hidden shrink-0" style={{ border: "1px solid var(--border)" }}>
          {(["all", "new", "updated"] as const).map(s => (
            <button key={s} onClick={() => setFilters({ ...filters, status: s })}
              className="px-3 py-1.5 text-xs transition-all"
              aria-pressed={filters.status === s}
              style={{
                background: filters.status === s ? "var(--accent)" : "var(--bg-elevated)",
                color: filters.status === s ? "var(--on-accent)" : "var(--text-muted)",
                fontFamily: "Inter, sans-serif",
                fontWeight: 500,
              }}>
              {s === "all" ? "All" : s === "new" ? "New" : "Updated"}
            </button>
          ))}
        </div>

        {/* Site multi-select */}
        <div className="relative shrink-0" ref={dropRef}>
          <button onClick={() => setSiteOpen(o => !o)}
            aria-expanded={siteOpen}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all"
            style={{ background: "var(--bg-elevated)", color: filters.sites.length ? "var(--accent-light)" : "var(--text-muted)", border: `1px solid ${filters.sites.length ? "var(--accent)" : "var(--border)"}`, fontFamily: "Inter, sans-serif" }}>
            {filters.sites.length === 1 ? sites.find(s => s.id === filters.sites[0])?.name ?? "1 site" : filters.sites.length ? `${filters.sites.length} sites` : "All Sites"}
            <ChevronDown />
          </button>
          {siteOpen && (
            <div className="absolute left-0 top-10 z-50 w-64 rounded-xl py-1.5 shadow-2xl overflow-hidden max-h-96 overflow-y-auto"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center justify-between px-3 py-1.5" style={{ borderBottom: "1px solid var(--border)" }}>
                <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Select sites</span>
                {filters.sites.length > 0 && (
                  <button onClick={() => setFilters({ ...filters, sites: [] })} className="text-[10px] hover:underline" style={{ color: "var(--accent-light)" }}>Clear</button>
                )}
              </div>
              {sites.length === 0 ? (
                <div className="px-3 py-3 text-xs" style={{ color: "var(--text-muted)" }}>No sites tracked yet — add some in Sources.</div>
              ) : (
                sites.map(s => (
                  <label key={s.id} className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover-surface transition-colors">
                    <input type="checkbox" checked={filters.sites.includes(s.id)} onChange={() => toggleSite(s.id)} className="accent-indigo-400 cursor-pointer" />
                    <SiteIcon site={s} size={14} />
                    <span className="text-xs flex-1 truncate" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>{s.name}</span>
                    {s.is_own_site && <span className="badge-own text-[9px] px-1 rounded">OURS</span>}
                    <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{s.articles_24h}</span>
                  </label>
                ))
              )}
            </div>
          )}
        </div>

        {/* Cohort */}
        {facets && facets.cohorts.length > 0 && (
          <select value={filters.cohort} onChange={e => setFilters({ ...filters, cohort: e.target.value })} className="select-custom text-xs shrink-0" aria-label="Cohort">
            <option value="">All cohorts</option>
            {facets.cohorts.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        )}

        {/* Date range */}
        <div className="flex items-center gap-1 shrink-0">
          <select value={filters.datePreset} aria-label="Date range"
            onChange={e => {
              const preset = e.target.value as DatePreset;
              setFilters(preset === "custom" ? { ...filters, datePreset: preset } : { ...filters, datePreset: preset, ...presetToRange(preset) });
            }}
            className="select-custom text-xs">
            {DATE_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
          {filters.datePreset === "custom" && (
            <>
              <input type="date" value={filters.dateFrom} onChange={e => setFilters({ ...filters, dateFrom: e.target.value })} className="select-custom text-xs" style={{ fontFamily: "JetBrains Mono, monospace", paddingRight: 8 }} aria-label="From date" />
              <span style={{ color: "var(--text-muted)" }} className="text-xs">→</span>
              <input type="date" value={filters.dateTo} onChange={e => setFilters({ ...filters, dateTo: e.target.value })} className="select-custom text-xs" style={{ fontFamily: "JetBrains Mono, monospace", paddingRight: 8 }} aria-label="To date" />
            </>
          )}
        </div>

        {/* Content type */}
        <select value={filters.contentType} onChange={e => setFilters({ ...filters, contentType: e.target.value })} className="select-custom text-xs shrink-0" aria-label="Content type">
          <option value="">All types</option>
          {Object.entries(CONTENT_TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>

        <button onClick={() => setFilters({ ...filters, hasYoutube: !filters.hasYoutube })} className={`filter-chip shrink-0 ${filters.hasYoutube ? "active" : ""}`} title="Only articles that embed a YouTube video">
          ▶ YT embed
        </button>
        <button onClick={() => setMore(m => !m)} className={`filter-chip shrink-0 ${more || hasMore ? "active" : ""}`} aria-expanded={more}>
          More filters{hasMore ? " •" : ""}
        </button>

        <div className="flex-1 min-w-0" />

        <select value={filters.sort} onChange={e => setFilters({ ...filters, sort: e.target.value as Filters["sort"] })} className="select-custom text-xs shrink-0" aria-label="Sort">
          <option value="newest">Sort: Latest activity</option>
          <option value="words">Sort: Longest</option>
          <option value="most_updated">Sort: Most updated</option>
        </select>

        <span className="text-xs shrink-0" style={{ color: "var(--text-muted)", fontFamily: "JetBrains Mono, monospace" }}>
          {shownCount < total ? `${shownCount} of ${total}` : `${total}`} articles
        </span>

        <a href={exportHref} className="flex items-center justify-center rounded-lg size-8 hover-surface shrink-0" style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }} title="Export this view as CSV" aria-label="Export CSV">
          <DownloadIcon />
        </a>

        <div className="flex rounded-lg overflow-hidden shrink-0" style={{ border: "1px solid var(--border)" }}>
          {(["grid", "list"] as const).map(m => (
            <button key={m} onClick={() => setViewMode(m)} aria-label={`${m} view`} aria-pressed={viewMode === m} className="p-2 transition-colors"
              style={{ background: viewMode === m ? "var(--bg-active)" : "var(--bg-elevated)", color: viewMode === m ? "var(--accent-light)" : "var(--text-muted)" }}>
              {m === "grid" ? <GridIcon /> : <ListIcon />}
            </button>
          ))}
        </div>
      </div>

      {(more || hasMore) && (
        <div className="flex flex-wrap items-center gap-2">
          <select value={filters.section} onChange={e => setFilters({ ...filters, section: e.target.value })} className="select-custom text-xs" aria-label="Category">
            <option value="">All categories</option>
            {(facets?.sections ?? []).map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
          </select>
          <select value={filters.author} onChange={e => setFilters({ ...filters, author: e.target.value })} className="select-custom text-xs" aria-label="Author">
            <option value="">All authors</option>
            {(facets?.authors ?? []).map(([a, n]) => <option key={a} value={a}>{a} ({n})</option>)}
          </select>
          <input type="number" min={0} step={100} placeholder="Min words" aria-label="Minimum word count" value={filters.minWords}
            onChange={e => setFilters({ ...filters, minWords: e.target.value })} className="select-custom text-xs w-28" style={{ fontFamily: "JetBrains Mono, monospace" }} />
          <button onClick={() => setFilters({ ...filters, hasAffiliate: !filters.hasAffiliate })} className={`filter-chip ${filters.hasAffiliate ? "active" : ""}`} title="Articles with Amazon/Flipkart affiliate links">
            ₹ Affiliate links
          </button>
          {hasMore && (
            <button onClick={() => setFilters({ ...filters, section: "", author: "", minWords: "", hasAffiliate: false })} className="text-[11px] hover:underline flex items-center gap-1" style={{ color: "var(--accent-light)" }}>
              <XIcon /> Clear these
            </button>
          )}
        </div>
      )}
    </div>
  );
}
