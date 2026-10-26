import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type Article, type Facets, type Site, type SystemStatus } from "./lib/api";
import { CONTENT_TYPE_LABEL, currentMonthLabel, fmtRelative } from "./lib/format";
import { activeFilterCount, defaultFilters, filtersToSearch, presetToRange, searchToFilters, toQuery, type Filters } from "./lib/filters";
import { load, save } from "./lib/storage";
import { useAsync } from "./hooks/useAsync";
import { ArticleCard, ArticleCardSkeleton } from "./components/ArticleCard";
import { ArticleDrawer } from "./components/ArticleDrawer";
import { FilterBar, type ViewMode } from "./components/FilterBar";
import { BookmarkIcon, HomeIcon, MenuIcon, RefreshIcon, XIcon } from "./components/icons";
import { Sidebar, type SavedView, type Section } from "./components/Sidebar";
import { ComingSoon } from "./views/ComingSoon";
import { SourcesView } from "./views/SourcesView";
import { LoginScreen } from "./views/LoginScreen";
import { YouTubeView } from "./views/YouTubeView";
import { RadarView } from "./views/RadarView";
import { ShortlistView } from "./views/ShortlistView";
import { AlertsView } from "./views/AlertsView";

const PAGE = 48;
const SECTIONS: Section[] = ["Live Feed", "Topic Radar", "YouTube", "Shortlist", "Alerts", "Site Analytics", "Sources"];
const slug = (s: Section) => s.toLowerCase().replace(/\s+/g, "-");

type Theme = "light" | "dark";

function initialTheme(): Theme {
  const stored = load<Theme | null>("webintel.theme", null);
  if (stored === "light" || stored === "dark") return stored;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function initialSection(): Section {
  const h = window.location.hash.replace("#", "");
  return SECTIONS.find(s => slug(s) === h) ?? "Live Feed";
}

function initialArticle(): number | null {
  const a = Number(new URLSearchParams(window.location.search).get("a"));
  return Number.isFinite(a) && a > 0 ? a : null;
}

function Dashboard({ authRequired }: { authRequired: boolean }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);
  const [section, setSection] = useState<Section>(initialSection);
  const [filters, setFilters] = useState<Filters>(() => searchToFilters(window.location.search));
  const [viewMode, setViewMode] = useState<ViewMode>(() => load<ViewMode>("webintel.viewMode", "grid"));
  const [openArticle, setOpenArticle] = useState<number | null>(initialArticle);
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => load<SavedView[]>("webintel.savedViews", []));
  const searchRef = useRef<HTMLInputElement>(null);

  // "Unread" = first seen by the tracker after your previous visit. The
  // snapshot stays fixed for this session so the dots don't vanish while
  // you're reading; the stored value moves forward when you leave.
  const [lastSeen, setLastSeen] = useState<number>(() => load<number>("webintel.lastSeen", Date.now() - 24 * 3600_000));
  useEffect(() => {
    const mark = () => save("webintel.lastSeen", Date.now());
    const onVis = () => { if (document.visibilityState === "hidden") mark(); };
    window.addEventListener("pagehide", mark);
    document.addEventListener("visibilitychange", onVis);
    return () => { window.removeEventListener("pagehide", mark); document.removeEventListener("visibilitychange", onVis); };
  }, []);

  // Theme
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
  }, [theme]);
  const toggleTheme = () => setTheme(t => { const n = t === "light" ? "dark" : "light"; save("webintel.theme", n); return n; });
  useEffect(() => save("webintel.viewMode", viewMode), [viewMode]);
  useEffect(() => { document.title = `${section} · TW-Labs Web Intel`; }, [section]);

  // URL ← state (filters in ?query, section in #hash, open article as ?a=)
  useEffect(() => {
    const qs = filtersToSearch(filters);
    const params = new URLSearchParams(qs);
    if (openArticle) params.set("a", String(openArticle));
    const s = params.toString();
    const url = `${window.location.pathname}${s ? `?${s}` : ""}#${slug(section)}`;
    window.history.replaceState(null, "", url);
  }, [filters, section, openArticle]);

  // Back/forward and #links switch sections.
  useEffect(() => {
    const onHash = () => { const h = window.location.hash.replace("#", ""); const s = SECTIONS.find(x => slug(x) === h); if (s) setSection(s); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Keyboard: Ctrl/Cmd+K or "/" focuses search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.("input, textarea, select");
      if (((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") || (e.key === "/" && !typing)) {
        e.preventDefault();
        setSection("Live Feed");
        setTimeout(() => searchRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Data
  const sitesAsync = useAsync<Site[]>(() => api.sites(), [], []);
  const sites = sitesAsync.data;
  const reloadSites = sitesAsync.reload;
  const facetsAsync = useAsync<Facets | null>(() => api.facets(filters.sites), [filters.sites.join(",")], null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const fetchStatus = useCallback(() => { api.status().then(setStatus).catch(() => {}); }, []);
  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, 60_000);
    return () => clearInterval(t);
  }, [fetchStatus]);

  const [articles, setArticles] = useState<Article[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const query = useMemo(() => toQuery(filters), [filters]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.articles({ ...query, limit: PAGE, offset: 0 })
      .then(r => { if (!cancelled) { setArticles(r.items); setTotal(r.total); setLoading(false); } })
      .catch(e => { if (!cancelled) { setError(e instanceof Error ? e.message : "Couldn't load articles"); setLoading(false); } });
    return () => { cancelled = true; };
  }, [query, tick]);

  // Quietly pick up new articles every 2 minutes while the feed is open.
  useEffect(() => {
    if (section !== "Live Feed") return;
    const t = setInterval(() => { if (document.visibilityState === "visible" && articles.length <= PAGE) setTick(x => x + 1); }, 120_000);
    return () => clearInterval(t);
  }, [section, articles.length]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const r = await api.articles({ ...query, limit: PAGE, offset: articles.length });
      setArticles(prev => [...prev, ...r.items.filter(n => !prev.some(p => p.id === n.id))]);
      setTotal(r.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load more");
    } finally {
      setLoadingMore(false);
    }
  };

  const isUnread = useCallback((a: Article) => !a.is_backfill && new Date(a.first_seen_at).getTime() > lastSeen, [lastSeen]);
  const unreadCount = useMemo(() => articles.filter(isUnread).length, [articles, isUnread]);

  // Refresh
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "err" } | null>(null);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 5000); return () => clearTimeout(t); }, [toast]);
  const refresh = async () => {
    setRefreshing(true);
    try {
      await api.refresh();
      setToast({ text: "Checking every site now — new articles appear in about a minute", kind: "ok" });
      setTimeout(() => { setTick(x => x + 1); fetchStatus(); reloadSites(); }, 45_000);
    } catch (e) {
      setToast({ text: e instanceof ApiError ? e.message : "Refresh failed", kind: "err" });
    } finally {
      setRefreshing(false);
    }
  };

  const goHome = () => { setSection("Live Feed"); setFilters(defaultFilters()); setOpenArticle(null); };

  const saveView = () => {
    const name = window.prompt("Name this view", filters.q || (filters.sites.length === 1 ? sites.find(s => s.id === filters.sites[0])?.name : "") || "My view");
    if (!name?.trim()) return;
    const next = [...savedViews.filter(v => v.name !== name.trim()), { name: name.trim(), search: filtersToSearch(filters) }];
    setSavedViews(next);
    save("webintel.savedViews", next);
    setToast({ text: `Saved "${name.trim()}"`, kind: "ok" });
  };
  const deleteView = (name: string) => { const next = savedViews.filter(v => v.name !== name); setSavedViews(next); save("webintel.savedViews", next); };

  const chips: { label: string; clear: () => void }[] = [];
  if (filters.sites.length) chips.push({ label: filters.sites.length === 1 ? sites.find(s => s.id === filters.sites[0])?.name ?? "1 site" : `${filters.sites.length} sites`, clear: () => setFilters({ ...filters, sites: [] }) });
  if (filters.cohort) chips.push({ label: filters.cohort, clear: () => setFilters({ ...filters, cohort: "" }) });
  if (filters.status !== "all") chips.push({ label: filters.status, clear: () => setFilters({ ...filters, status: "all" }) });
  if (filters.contentType) chips.push({ label: CONTENT_TYPE_LABEL[filters.contentType] ?? filters.contentType, clear: () => setFilters({ ...filters, contentType: "" }) });
  if (filters.q) chips.push({ label: `"${filters.q}"`, clear: () => setFilters({ ...filters, q: "" }) });
  if (filters.section) chips.push({ label: filters.section, clear: () => setFilters({ ...filters, section: "" }) });
  if (filters.author) chips.push({ label: filters.author, clear: () => setFilters({ ...filters, author: "" }) });
  if (filters.hasYoutube) chips.push({ label: "YT embed", clear: () => setFilters({ ...filters, hasYoutube: false }) });

  const subtitle = section === "Live Feed"
    ? `New & updated competitor articles · ${currentMonthLabel()}`
    : section === "Sources" ? "Sites, feeds and tracker health"
    : section === "Topic Radar" ? "Stories several competitors are covering, and the ones techwiser.com hasn't"
    : section === "YouTube" ? "Competitor channels · overperformance, velocity, sponsors and community posts"
    : section === "Shortlist" ? "Ideas the team picked from the feed, radar and YouTube"
    : section === "Alerts" ? "Slack / Telegram alerts, daily digest and integrations"
    : "Coming soon";

  return (
    <div className="flex h-full w-full overflow-hidden" style={{ background: "var(--bg-base)", fontFamily: "Inter, sans-serif" }}>
      <Sidebar
        open={sidebarOpen}
        active={section}
        setActive={s => { setSection(s); if (window.innerWidth < 768) setSidebarOpen(false); }}
        unread={unreadCount}
        sites={sites}
        savedViews={savedViews}
        onOpenView={v => { setFilters(searchToFilters(v.search)); setSection("Live Feed"); }}
        onDeleteView={deleteView}
        onPickCohort={c => { setFilters({ ...filters, cohort: c }); if (section !== "Topic Radar" && section !== "YouTube") setSection("Live Feed"); }}
        activeCohort={filters.cohort}
        status={status}
        theme={theme}
        onToggleTheme={toggleTheme}
        onLogout={authRequired ? () => { api.logout().finally(() => window.location.reload()); } : undefined}
      />

      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="flex items-center justify-between gap-3 px-5 py-3 shrink-0" style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-panel)" }}>
          <div className="flex items-center gap-3 min-w-0">
            <button onClick={() => setSidebarOpen(o => !o)} aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
              className="flex items-center justify-center rounded-lg size-8 transition-colors hover-surface shrink-0" style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}>
              <MenuIcon />
            </button>
            <button onClick={goHome} title="Home — Live Feed with every filter cleared" aria-label="Home — Live Feed with every filter cleared"
              className="flex items-center justify-center rounded-lg size-8 transition-colors hover-surface shrink-0"
              style={{ color: section === "Live Feed" ? "var(--accent-light)" : "var(--text-muted)", border: `1px solid ${section === "Live Feed" ? "var(--accent)" : "var(--border)"}` }}>
              <HomeIcon />
            </button>
            <div className="min-w-0">
              <h1 className="text-sm font-bold leading-none" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{section}</h1>
              <p className="text-[11px] mt-0.5 truncate" style={{ color: "var(--text-muted)" }}>{subtitle}</p>
            </div>
          </div>

          <div className="flex items-center gap-2 min-w-0">
            {section === "Live Feed" && (
              <div className="hidden lg:flex items-center gap-1.5 flex-wrap justify-end">
                {chips.map(c => (
                  <span key={c.label} className="filter-chip active">
                    {c.label}
                    <button className="p-1 -m-1" aria-label={`Clear ${c.label}`} onClick={c.clear}><XIcon /></button>
                  </span>
                ))}
              </div>
            )}
            {section === "Live Feed" && activeFilterCount(filters) > 0 && (
              <button onClick={saveView} className="flex items-center gap-1.5 rounded-lg h-9 px-3 hover-surface shrink-0" style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }} title="Save these filters to the sidebar">
                <BookmarkIcon size={13} /><span className="text-xs hidden sm:inline" style={{ fontFamily: "Lora, serif" }}>Save view</span>
              </button>
            )}
            {toast && (
              <span className="text-[11px] px-2 py-1 rounded-md hidden md:inline max-w-xs truncate" style={{ color: toast.kind === "ok" ? "var(--accent-light)" : "var(--tier-danger)", background: "var(--bg-base)", border: `1px solid ${toast.kind === "ok" ? "var(--accent)" : "var(--tier-danger)"}` }}>
                {toast.text}
              </span>
            )}
            {(section === "Live Feed" || section === "Topic Radar" || section === "Sources") && <button onClick={refresh} disabled={refreshing} title={status?.last_poll_at ? `Last checked ${fmtRelative(status.last_poll_at)}` : "Check every site right now"}
              className="flex items-center gap-1.5 rounded-lg h-9 px-3 transition-colors hover-surface disabled:opacity-50 shrink-0" style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}>
              <span className={refreshing ? "animate-spin" : undefined}><RefreshIcon /></span>
              <span className="text-xs hidden sm:inline" style={{ fontFamily: "Lora, serif" }}>{refreshing ? "Refreshing…" : "Refresh now"}</span>
            </button>}
          </div>
        </header>

        <main className="flex flex-1 min-h-0 overflow-hidden">
          {section === "Sources" ? (
            <div className="flex-1 overflow-y-auto">
              <SourcesView sites={sites} loading={sitesAsync.loading} error={sitesAsync.error} onRetry={reloadSites}
                onChanged={() => { reloadSites(); fetchStatus(); }}
                onShowFeed={id => { setFilters({ ...defaultFilters(), sites: [id], datePreset: "7d", ...presetToRange("7d") }); setSection("Live Feed"); }} />
            </div>
          ) : section === "YouTube" ? (
            <YouTubeView sites={sites} cohort={filters.cohort} onOpenArticle={setOpenArticle} />
          ) : section === "Topic Radar" ? (
            <RadarView cohort={filters.cohort} onOpenArticle={setOpenArticle} onGoSources={() => setSection("Sources")} />
          ) : section === "Shortlist" ? (
            <ShortlistView />
          ) : section === "Alerts" ? (
            <AlertsView sites={sites} />
          ) : section !== "Live Feed" ? (
            <ComingSoon section={section} />
          ) : (
            <>
              <div className="flex-1 min-w-0 overflow-y-auto">
                <FilterBar filters={filters} setFilters={setFilters} sites={sites} facets={facetsAsync.data} viewMode={viewMode} setViewMode={setViewMode}
                  shownCount={articles.length} total={total} exportHref={api.exportUrl(query)} searchRef={searchRef} />

                {unreadCount > 0 && !loading && (
                  <div className="px-5 pt-3 flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
                    <span className="unread-dot" /> {unreadCount} new since your last visit
                    <button onClick={() => { const now = Date.now(); setLastSeen(now); save("webintel.lastSeen", now); }} className="underline" style={{ color: "var(--accent-light)" }}>Mark all read</button>
                  </div>
                )}

                {error ? (
                  <div className="p-8 text-center text-sm" style={{ color: "var(--tier-danger)" }}>
                    {error} <button onClick={() => setTick(x => x + 1)} className="underline ml-1" style={{ color: "var(--accent-light)" }}>Retry</button>
                  </div>
                ) : !loading && articles.length === 0 ? (
                  <div className="p-10 flex flex-col items-center gap-3 text-center">
                    {sites.length === 0 && !sitesAsync.loading ? (
                      <>
                        <div className="text-base font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>No sites tracked yet</div>
                        <p className="text-sm max-w-sm" style={{ color: "var(--text-muted)" }}>Add a competitor's website and its last 30 days of articles appear here within a few minutes.</p>
                        <button onClick={() => setSection("Sources")} className="btn-primary text-sm px-4 py-2">Add a site</button>
                      </>
                    ) : (
                      <>
                        <div className="text-base font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>Nothing matches these filters</div>
                        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                          {status && status.queue_pending > 0 ? `${status.queue_pending} articles are still being read — check back shortly, or ` : "Try a wider date range, or "}
                          <button onClick={() => setFilters(defaultFilters())} className="underline" style={{ color: "var(--accent-light)" }}>clear all filters</button>.
                        </p>
                      </>
                    )}
                  </div>
                ) : (
                  <div className="p-5">
                    <div className={viewMode === "grid" ? "grid gap-4" : "flex flex-col gap-2"} style={viewMode === "grid" ? { gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" } : undefined}>
                      {loading
                        ? Array.from({ length: 12 }, (_, i) => <ArticleCardSkeleton key={i} mode={viewMode} />)
                        : articles.map(a => <ArticleCard key={a.id} article={a} mode={viewMode} unread={isUnread(a)} selected={openArticle === a.id} onOpen={setOpenArticle} />)}
                    </div>
                    {!loading && articles.length < total && (
                      <div className="flex justify-center pt-5">
                        <button onClick={loadMore} disabled={loadingMore} className="filter-chip" style={{ padding: "8px 18px" }}>
                          {loadingMore ? "Loading…" : `Load more (${total - articles.length} left)`}
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
          {openArticle != null && section !== "Sources" && <ArticleDrawer key={openArticle} articleId={openArticle} onClose={() => setOpenArticle(null)} onOpenOther={setOpenArticle} />}
        </main>
      </div>
    </div>
  );
}

type AuthState = "checking" | "login" | "ok";

/** Shows the login screen when the backend has DASHBOARD_PASSWORD set and
 * there's no valid session; otherwise the dashboard. */
export default function App() {
  const [state, setState] = useState<AuthState>("checking");
  const [authRequired, setAuthRequired] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);

  const check = useCallback(() => {
    setCheckError(null);
    api.me()
      .then(r => { setAuthRequired(r.auth_required); setState(r.authenticated ? "ok" : "login"); })
      .catch(e => setCheckError(e instanceof Error ? e.message : "Can't reach the server"));
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", initialTheme());
    check();
    const onUnauthorized = () => setState("login");
    window.addEventListener("webintel:unauthorized", onUnauthorized);
    return () => window.removeEventListener("webintel:unauthorized", onUnauthorized);
  }, [check]);

  // On Render's free plan the backend may be asleep: retry quietly every
  // 10 s while it wakes (about a minute) instead of showing a dead end.
  useEffect(() => {
    if (!checkError) return;
    const t = setInterval(check, 10_000);
    return () => clearInterval(t);
  }, [checkError, check]);

  if (checkError) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 p-6 text-center" style={{ background: "var(--bg-base)", color: "var(--text-secondary)", fontFamily: "Inter, sans-serif" }}>
        <span className="size-3 rounded-full animate-pulse" style={{ background: "var(--accent)" }} />
        <div className="text-sm font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>Waking up the server…</div>
        <div className="text-xs max-w-xs" style={{ color: "var(--text-muted)" }}>
          On the free plan the backend can fall asleep; it takes about a minute to start. This page retries on its own.
        </div>
        <button onClick={check} className="filter-chip" style={{ padding: "6px 14px" }}>Try now</button>
      </div>
    );
  }
  if (state === "checking") return <div className="h-full" style={{ background: "var(--bg-base)" }} />;
  if (state === "login") return <LoginScreen onLoggedIn={() => setState("ok")} />;
  return <Dashboard authRequired={authRequired} />;
}
