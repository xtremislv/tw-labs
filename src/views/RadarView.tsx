import { useEffect, useState } from "react";
import { api, type Radar, type Story } from "../lib/api";
import { fmtRelative, fmtViews, ratioColor } from "../lib/format";
import { load, save } from "../lib/storage";
import { useAsync } from "../hooks/useAsync";
import { ChevronDown, ClockIcon, SearchIcon, YTIcon } from "../components/icons";
import { ShortlistButton } from "../components/VideoCard";
import { SiteIcon } from "../components/SiteIcon";

const WINDOWS = [
  { h: 12, label: "Last 12 h" },
  { h: 24, label: "Last 24 h" },
  { h: 48, label: "Last 48 h" },
  { h: 72, label: "Last 3 days" },
  { h: 168, label: "Last 7 days" },
];

interface RadarFilters { hours: number; minSites: number; gapsOnly: boolean; q: string }

function spread(s: Story): string | null {
  if (s.hours_to_3_sites == null) return null;
  const h = s.hours_to_3_sites;
  return h < 1 ? `3 sites in ${Math.max(1, Math.round(h * 60))} min` : `3 sites in ${h < 10 ? h.toFixed(1) : Math.round(h)} h`;
}

function StoryCard({ s, onOpenArticle }: { s: Story; onOpenArticle: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const sp = spread(s);
  const fast = s.hours_to_3_sites != null && s.hours_to_3_sites <= 3;
  return (
    <div className="video-card flex flex-col">
      <div className="p-4 flex flex-col gap-3">
        <div className="flex items-start gap-3">
          <div className="flex flex-col items-center justify-center rounded-lg shrink-0 w-12 h-12" style={{ background: "var(--bg-elevated)" }} title="Sites that covered this story">
            <span className="text-lg font-bold font-mono leading-none" style={{ color: s.gap ? "var(--tier-danger)" : "var(--accent-light)" }}>{s.competitor_site_count}</span>
            <span className="text-[8px] uppercase tracking-wider mt-0.5" style={{ color: "var(--text-muted)" }}>sites</span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold leading-snug line-clamp-2" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{s.label}</div>
            <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
              {s.gap === true && <span className="badge-gap text-[10px] px-1.5 py-0.5 rounded font-bold">GAP · not on our site</span>}
              {s.covered_by_us === true && <span className="badge-covered text-[10px] px-1.5 py-0.5 rounded font-bold">COVERED</span>}
              {sp && <span className={`text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1 ${fast ? "badge-overperform" : "badge-type"}`}><ClockIcon size={9} />{sp}</span>}
              <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{s.article_count} articles · first {fmtRelative(s.first_at)} · latest {fmtRelative(s.last_at)}</span>
            </div>
          </div>
          <ShortlistButton initial={s.shortlisted} item={{ kind: "story", ref_id: s.key, title: s.label, url: s.articles[0]?.url ?? null, source: `${s.competitor_site_count} sites` }} />
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          {s.sites.map(site => (
            <span key={site.id} className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded" title={site.name}
              style={{ background: site.is_own_site ? "rgba(56,189,248,0.14)" : "var(--bg-elevated)", color: site.is_own_site ? "var(--tier-blue)" : "var(--text-secondary)" }}>
              <SiteIcon site={site} size={12} />{site.name}
            </span>
          ))}
        </div>

        {s.terms.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {s.terms.slice(0, 6).map(t => <span key={t} className="text-[10px] font-mono px-1.5 rounded" style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}>{t}</span>)}
          </div>
        )}

        {s.videos.length > 0 && (
          <div className="flex flex-col gap-1.5 pt-2" style={{ borderTop: "1px solid var(--border)" }}>
            <span className="label-caps flex items-center gap-1.5"><YTIcon size={11} />On tracked channels</span>
            {s.videos.slice(0, 3).map(v => (
              <a key={v.id} href={`https://www.youtube.com/watch?v=${v.id}`} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-md p-1 hover-surface">
                {v.thumbnail_url ? <img src={v.thumbnail_url} alt="" className="w-16 h-9 rounded object-cover shrink-0" loading="lazy" /> : <span className="w-16 h-9 rounded shrink-0" style={{ background: "var(--bg-elevated)" }} />}
                <span className="flex-1 min-w-0">
                  <span className="block text-xs truncate" style={{ color: "var(--text-primary)" }}>{v.title}</span>
                  <span className="block text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{v.channel_name} · {fmtViews(v.views)} views{v.ratio != null && <> · <span style={{ color: ratioColor(v.ratio) }}>{v.ratio.toFixed(1)}x</span></>}</span>
                </span>
              </a>
            ))}
          </div>
        )}
      </div>

      <button onClick={() => setOpen(o => !o)} className="flex items-center justify-between px-4 py-2 text-xs hover-surface" style={{ borderTop: "1px solid var(--border)", color: "var(--text-muted)" }} aria-expanded={open}>
        <span style={{ fontFamily: "Lora, serif" }}>{open ? "Hide" : "Show"} {s.article_count} articles</span>
        <span style={{ transform: open ? "rotate(180deg)" : undefined, transition: "transform .15s" }}><ChevronDown /></span>
      </button>
      {open && (
        <div className="flex flex-col pb-2">
          {s.articles.map(a => (
            <button key={a.id} onClick={() => onOpenArticle(a.id)} className="flex items-center gap-2.5 px-4 py-2 text-left hover-surface">
              <SiteIcon site={{ name: a.site_name, icon_url: a.site_icon_url }} size={14} />
              <span className="flex-1 min-w-0 text-xs truncate" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>{a.title}</span>
              <span className="text-[10px] font-mono shrink-0" style={{ color: "var(--text-muted)" }}>{fmtRelative(a.published_at ?? a.first_seen_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function RadarView({ cohort, onOpenArticle, onGoSources }: { cohort: string; onOpenArticle: (id: number) => void; onGoSources: () => void }) {
  const [f, setFRaw] = useState<RadarFilters>(() => ({ hours: 48, minSites: 2, gapsOnly: false, q: "", ...load<Partial<RadarFilters>>("webintel.radar", {}) }));
  const setF = (n: RadarFilters) => { setFRaw(n); save("webintel.radar", { ...n, q: "" }); };
  const [q, setQ] = useState(f.q);
  useEffect(() => { const t = setTimeout(() => { if (q !== f.q) setF({ ...f, q }); }, 300); return () => clearTimeout(t); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [q]);
  const { data, loading, error, reload } = useAsync<Radar | null>(
    () => api.radar({ hours: f.hours, min_sites: f.minSites, gaps_only: f.gapsOnly, cohort: cohort || undefined, q: f.q || undefined }),
    [f.hours, f.minSites, f.gapsOnly, f.q, cohort], null);
  useEffect(() => { const t = setInterval(() => { if (document.visibilityState === "visible") reload(); }, 180_000); return () => clearInterval(t); }, [reload]);

  return (
    <div className="flex-1 min-w-0 overflow-y-auto">
      <div className="sticky top-0 z-30 px-5 py-3 flex flex-wrap items-center gap-2" style={{ background: "var(--surface-translucent)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--border)" }}>
        <div className="relative shrink-0">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "var(--text-muted)" }}><SearchIcon /></span>
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Filter stories…" aria-label="Filter stories" className="select-custom text-xs w-44" style={{ paddingLeft: 28 }} />
        </div>
        <select className="select-custom text-xs" value={f.hours} onChange={e => setF({ ...f, hours: Number(e.target.value) })} aria-label="Window">
          {WINDOWS.map(w => <option key={w.h} value={w.h}>{w.label}</option>)}
        </select>
        <select className="select-custom text-xs" value={f.minSites} onChange={e => setF({ ...f, minSites: Number(e.target.value) })} aria-label="Minimum sites">
          {[2, 3, 4, 5].map(n => <option key={n} value={n}>{n}+ sites</option>)}
        </select>
        <button onClick={() => setF({ ...f, gapsOnly: !f.gapsOnly })} className={`filter-chip ${f.gapsOnly ? "active" : ""}`} disabled={data != null && !data.own_site_configured}
          title={data && !data.own_site_configured ? "Mark techwiser.com as your own site in Sources to see gaps" : "Only stories techwiser.com hasn't covered"}>
          Gaps only{data ? ` · ${data.gaps}` : ""}
        </button>
        {cohort && <span className="filter-chip active">{cohort}</span>}
        <span className="flex-1" />
        <span className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>{data ? `${data.total} stories` : ""}</span>
      </div>

      {data && !data.own_site_configured && (
        <div className="mx-5 mt-4 panel p-3 text-xs flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
          Gap detection needs your own site. Add techwiser.com in Sources and tick "This is our site" (or use "Mark as our site").
          <button onClick={onGoSources} className="underline" style={{ color: "var(--accent-light)" }}>Open Sources</button>
        </div>
      )}

      {error ? (
        <div className="p-8 text-center text-sm" style={{ color: "var(--tier-danger)" }}>{error} <button onClick={reload} className="underline ml-1" style={{ color: "var(--accent-light)" }}>Retry</button></div>
      ) : loading && !data ? (
        <div className="p-5 grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))" }}>{Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton h-44" />)}</div>
      ) : data && data.stories.length === 0 ? (
        <div className="p-10 text-center flex flex-col items-center gap-2">
          <div className="text-base font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>No shared stories in this window</div>
          <p className="text-sm max-w-md" style={{ color: "var(--text-muted)" }}>A story appears here once {f.minSites}+ tracked sites publish about the same thing. Try a longer window or fewer sites.</p>
        </div>
      ) : data && (
        <div className="p-5 grid gap-4 items-start" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", opacity: loading ? 0.6 : 1 }}>
          {data.stories.map(s => <StoryCard key={s.key} s={s} onOpenArticle={onOpenArticle} />)}
        </div>
      )}
    </div>
  );
}
