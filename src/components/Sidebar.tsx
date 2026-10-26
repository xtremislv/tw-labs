import type { Site, SystemStatus } from "../lib/api";
import { fmtRelative } from "../lib/format";
import { BellIcon, BookmarkIcon, ChartIcon, ChecklistIcon, FeedIcon, GlobeIcon, MoonIcon, RadarIcon, SunIcon, XIcon, YTIcon } from "./icons";

export type Section = "Live Feed" | "Topic Radar" | "YouTube" | "Shortlist" | "Alerts" | "Site Analytics" | "Sources";

export interface SavedView {
  name: string;
  search: string;
}

const NAV: { label: Section; icon: React.ReactElement; soon?: string }[] = [
  { label: "Live Feed", icon: <FeedIcon /> },
  { label: "Topic Radar", icon: <RadarIcon /> },
  { label: "YouTube", icon: <YTIcon /> },
  { label: "Shortlist", icon: <ChecklistIcon /> },
  { label: "Alerts", icon: <BellIcon /> },
  { label: "Site Analytics", icon: <ChartIcon />, soon: "Phase 2" },
  { label: "Sources", icon: <GlobeIcon /> },
];

const COHORT_COLORS = ["#8083ff", "#4ade80", "#facc15", "#38bdf8", "#fb923c", "#f472b6"];

interface Props {
  open: boolean;
  active: Section;
  setActive: (s: Section) => void;
  unread: number;
  sites: Site[];
  savedViews: SavedView[];
  onOpenView: (v: SavedView) => void;
  onDeleteView: (name: string) => void;
  onPickCohort: (cohort: string) => void;
  activeCohort: string;
  status: SystemStatus | null;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onLogout?: () => void;
}

export function Sidebar({ open, active, setActive, unread, sites, savedViews, onOpenView, onDeleteView, onPickCohort, activeCohort, status, theme, onToggleTheme, onLogout }: Props) {
  const cohorts = new Map<string, number>();
  for (const s of sites) if (s.cohort) cohorts.set(s.cohort, (cohorts.get(s.cohort) ?? 0) + 1);
  const failing = sites.filter(s => s.health === "error" || s.health === "warning").length;

  return (
    <aside className="sidebar-slide flex flex-col h-full shrink-0 overflow-hidden"
      style={{ width: open ? 240 : 0, opacity: open ? 1 : 0, background: "var(--bg-panel)", borderRight: "1px solid var(--border)", pointerEvents: open ? "auto" : "none" }}>
      {/* Brand */}
      <div className="flex items-center gap-2.5 px-4 py-4 shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
        <img src="/tw-logo.png" alt="TW-Labs" className="size-8" />
        <div>
          <div className="text-sm font-bold leading-none" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>
            TW<span style={{ color: "var(--accent-light)" }}>-Labs</span>
          </div>
          <div className="text-[10px] mt-1 tracking-widest uppercase" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Web Intel</div>
        </div>
      </div>

      {/* Nav */}
      <div className="px-2 shrink-0">
        <div className="text-[10px] tracking-widest uppercase px-3 py-2" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Web & Articles</div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(link => {
            const isActive = active === link.label;
            const badge = link.label === "Live Feed" ? unread : link.label === "Sources" ? failing : 0;
            return (
              <button key={link.label} onClick={() => setActive(link.label)}
                className="flex items-center gap-3 px-3 py-2 rounded-lg w-full text-left transition-all"
                aria-current={isActive ? "page" : undefined}
                style={{ background: isActive ? "var(--accent)" : "transparent", color: isActive ? "var(--on-accent)" : link.soon ? "var(--text-muted)" : "var(--text-secondary)" }}>
                {link.icon}
                <span className="text-sm flex-1" style={{ fontFamily: "Lora, serif" }}>{link.label}</span>
                {link.soon && <span className="text-[9px] font-mono opacity-80">{link.soon}</span>}
                {badge > 0 && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full font-bold" title={link.label === "Sources" ? "Sites with failing feeds" : "New since your last visit"}
                    style={{ background: link.label === "Sources" ? "rgba(250,204,21,0.2)" : "#a40217", color: link.label === "Sources" ? "var(--warning)" : "#ffaea8" }}>
                    {badge > 99 ? "99+" : badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="px-2 mt-2 flex-1 min-h-0 overflow-y-auto">
        {/* Saved views */}
        <div className="flex items-center gap-2 px-3 py-2">
          <BookmarkIcon size={11} />
          <span className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Saved Views</span>
        </div>
        {savedViews.length === 0 ? (
          <div className="px-3 pb-2 text-xs" style={{ color: "var(--text-muted)" }}>Set filters in the Live Feed, then "Save view" to keep them here.</div>
        ) : (
          savedViews.map(v => (
            <div key={v.name} className="group flex items-center rounded-lg hover-surface">
              <button onClick={() => onOpenView(v)} className="flex-1 text-left px-3 py-1.5 text-sm truncate" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>{v.name}</button>
              <button onClick={() => onDeleteView(v.name)} aria-label={`Delete saved view ${v.name}`} className="px-2 opacity-0 group-hover:opacity-100 focus:opacity-100" style={{ color: "var(--text-muted)" }}><XIcon /></button>
            </div>
          ))
        )}

        {/* Cohorts */}
        <div className="text-[10px] tracking-widest uppercase px-3 py-2 mt-2" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Cohorts</div>
        {cohorts.size === 0 ? (
          <div className="px-3 py-1 text-xs" style={{ color: "var(--text-muted)" }}>Tag sites with a cohort in Sources to group them here.</div>
        ) : (
          Array.from(cohorts.entries()).map(([c, n], i) => (
            <button key={c} onClick={() => onPickCohort(activeCohort === c ? "" : c)}
              className="flex items-center gap-3 px-3 py-1.5 rounded-lg w-full text-left hover-surface transition-colors"
              style={{ background: activeCohort === c ? "var(--accent-dim)" : undefined }}>
              <div className="size-2 rounded-sm shrink-0" style={{ background: COHORT_COLORS[i % COHORT_COLORS.length] }} />
              <span className="text-sm flex-1" style={{ color: activeCohort === c ? "var(--accent-light)" : "var(--text-secondary)", fontFamily: "Lora, serif" }}>{c}</span>
              <span className="text-sm" style={{ color: "var(--text-muted)", fontFamily: "JetBrains Mono, monospace" }}>{n}</span>
            </button>
          ))
        )}
      </div>

      {/* Theme */}
      <div className="px-2 pt-2 shrink-0">
        <button onClick={onToggleTheme} className="w-full rounded-xl p-3 flex items-center justify-between" style={{ background: "var(--bg-card)" }} aria-label="Toggle light/dark theme">
          <span className="flex items-center gap-2 text-[10px] tracking-widest uppercase" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>
            {theme === "light" ? <SunIcon /> : <MoonIcon />}
            {theme === "light" ? "Light Mode" : "Dark Mode"}
          </span>
          <span className="w-8 h-4 rounded-full relative transition-colors" style={{ background: theme === "light" ? "var(--accent)" : "var(--bg-active)" }}>
            <span className="absolute top-0.5 size-3 rounded-full bg-white transition-all" style={{ left: theme === "light" ? 18 : 2 }} />
          </span>
        </button>
      </div>

      {/* Tracker status */}
      <div className="p-2 shrink-0">
        <div className="rounded-xl p-3 flex flex-col gap-1.5" style={{ background: "var(--bg-card)" }}>
          <div className="flex items-center justify-between">
            <h2 className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>Tracker</h2>
            <span className="flex items-center gap-1.5 text-[11px]" style={{ color: status?.worker_alive ? "var(--success)" : "var(--tier-danger)" }}>
              <span className="size-1.5 rounded-full" style={{ background: "currentColor" }} />
              {status == null ? "—" : status.worker_alive ? "Running" : "Worker down"}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-1 text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>
            <span>{status?.articles_24h ?? "—"} new 24h</span>
            <span>{status?.updates_24h ?? "—"} edits 24h</span>
            <span>{status?.sites ?? "—"} sites</span>
            <span>{status?.queue_pending ?? "—"} queued</span>
          </div>
          <div className="flex items-center justify-between text-[10px]" style={{ color: "var(--text-muted)" }}>
            <span>Last check {fmtRelative(status?.last_poll_at)}</span>
            {onLogout && <button onClick={onLogout} className="hover:underline" style={{ color: "var(--accent-light)" }}>Log out</button>}
          </div>
        </div>
      </div>
    </aside>
  );
}
