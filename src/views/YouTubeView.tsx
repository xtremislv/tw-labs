import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type Article, type Channel, type Post, type Site, type Video, type VideoQuery, type YouTubeStatus } from "../lib/api";
import { fmtDate, fmtRelative, fmtViews } from "../lib/format";
import { istDate } from "../lib/format";
import { load, save } from "../lib/storage";
import { useAsync } from "../hooks/useAsync";
import { ChevronDown, CommentIcon, ExternalIcon, GridIcon, HeartIcon, ListIcon, MegaphoneIcon, PlusIcon, RefreshIcon, SearchIcon, TrashIcon, XIcon, YTIcon } from "../components/icons";
import { ShortlistButton, VideoCard, VideoCardSkeleton, type Metric } from "../components/VideoCard";
import { SiteIcon } from "../components/SiteIcon";

type Tab = "Videos" | "Posts" | "Channels";
type Preset = "today" | "3d" | "7d" | "2w" | "1m" | "3m" | "all";
const PRESETS: { value: Preset; label: string; days: number | null }[] = [
  { value: "today", label: "Today", days: 0 },
  { value: "3d", label: "Last 3 days", days: 3 },
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "2w", label: "Last 2 weeks", days: 14 },
  { value: "1m", label: "Last 30 days", days: 30 },
  { value: "3m", label: "Last 90 days", days: 90 },
  { value: "all", label: "All time", days: null },
];
const VIEW_STEPS = [0, 1_000, 10_000, 50_000, 100_000, 500_000, 1_000_000];
const PAGE = 48;

interface YTFilters {
  channels: number[];
  preset: Preset;
  minViews: number;
  format: "all" | "long" | "short";
  metric: Metric;
  sort: NonNullable<VideoQuery["sort_by"]>;
  sponsored: boolean;
  q: string;
}
const DEFAULTS: YTFilters = { channels: [], preset: "1m", minViews: 0, format: "all", metric: "median", sort: "ratio", sponsored: false, q: "" };

function toQuery(f: YTFilters, cohort: string): VideoQuery {
  const days = PRESETS.find(p => p.value === f.preset)?.days;
  return {
    channels: f.channels.length ? f.channels : undefined,
    cohort: cohort || undefined,
    date_from: days == null ? undefined : istDate(new Date(Date.now() - days * 86400_000)),
    views_threshold: f.minViews || undefined,
    format: f.format,
    sort_by: f.sort,
    metric: f.metric,
    has_sponsor: f.sponsored || undefined,
    q: f.q || undefined,
  };
}

function Avatar({ url, name, size = 28 }: { url: string | null; name: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (url && !failed) return <img src={url} alt="" className="rounded-full shrink-0 object-cover" style={{ width: size, height: size }} onError={() => setFailed(true)} loading="lazy" />;
  return (
    <span className="rounded-full shrink-0 flex items-center justify-center font-bold" style={{ width: size, height: size, fontSize: size * 0.4, background: "var(--accent-dim)", color: "var(--accent-light)", fontFamily: "Lora, serif" }}>
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

// ── Filter bar (same controls and order as TW-Labs) ────────────────────────
function VideoFilterBar({ f, setF, channels, mode, setMode, shown, total, ovp, threshold }: {
  f: YTFilters; setF: (f: YTFilters) => void; channels: Channel[]; mode: "grid" | "list"; setMode: (m: "grid" | "list") => void;
  shown: number; total: number; ovp: number; threshold: number;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState(f.q);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => setQ(f.q), [f.q]);
  useEffect(() => {
    if (q === f.q) return;
    const t = setTimeout(() => setF({ ...f, q }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const toggle = (id: number) => setF({ ...f, channels: f.channels.includes(id) ? f.channels.filter(c => c !== id) : [...f.channels, id] });

  return (
    <div className="sticky top-0 z-30 px-5 py-3 flex flex-wrap items-center gap-2" style={{ background: "var(--surface-translucent)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--border)" }}>
      <div className="relative shrink-0">
        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "var(--text-muted)" }}><SearchIcon /></span>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search titles…" aria-label="Search videos" className="select-custom text-xs w-44" style={{ paddingLeft: 28 }} />
      </div>

      <div className="relative shrink-0" ref={ref}>
        <button onClick={() => setOpen(o => !o)} aria-expanded={open} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs"
          style={{ background: "var(--bg-elevated)", color: f.channels.length ? "var(--accent-light)" : "var(--text-muted)", border: `1px solid ${f.channels.length ? "var(--accent)" : "var(--border)"}` }}>
          {f.channels.length === 1 ? channels.find(c => c.id === f.channels[0])?.name ?? "1 channel" : f.channels.length ? `${f.channels.length} channels` : "All Channels"}
          <ChevronDown />
        </button>
        {open && (
          <div className="absolute left-0 top-10 z-50 w-64 rounded-xl py-1.5 shadow-2xl max-h-96 overflow-y-auto" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
            <div className="flex items-center justify-between px-3 py-1.5" style={{ borderBottom: "1px solid var(--border)" }}>
              <span className="label-caps">Select channels</span>
              {f.channels.length > 0 && <button onClick={() => setF({ ...f, channels: [] })} className="text-[10px] hover:underline" style={{ color: "var(--accent-light)" }}>Clear</button>}
            </div>
            {channels.length === 0 && <div className="px-3 py-3 text-xs" style={{ color: "var(--text-muted)" }}>No channels yet — add some in the Channels tab.</div>}
            {channels.map(c => (
              <label key={c.id} className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover-surface">
                <input type="checkbox" checked={f.channels.includes(c.id)} onChange={() => toggle(c.id)} className="accent-indigo-400" />
                <Avatar url={c.avatar_url} name={c.name} size={16} />
                <span className="text-xs flex-1 truncate" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>{c.name}</span>
                <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{c.video_count}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <select className="select-custom text-xs" value={f.preset} onChange={e => setF({ ...f, preset: e.target.value as Preset })} aria-label="Date range">
        {PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
      </select>

      <select className="select-custom text-xs" value={f.minViews} onChange={e => setF({ ...f, minViews: Number(e.target.value) })} aria-label="Minimum views">
        {VIEW_STEPS.map(v => <option key={v} value={v}>{v === 0 ? "Any views" : `${fmtViews(v)}+ views`}</option>)}
      </select>

      <div className="seg" role="group" aria-label="Format">
        {(["all", "long", "short"] as const).map(x => <button key={x} aria-pressed={f.format === x} onClick={() => setF({ ...f, format: x })}>{x === "all" ? "All" : x === "long" ? "Long" : "Shorts"}</button>)}
      </div>

      <div className="seg" role="group" aria-label="Baseline" title="Compare each video with the channel's recent average or median">
        {(["average", "median"] as const).map(x => <button key={x} aria-pressed={f.metric === x} onClick={() => setF({ ...f, metric: x })}>{x === "average" ? "Avg" : "Median"}</button>)}
      </div>

      <select className="select-custom text-xs" value={f.sort} onChange={e => setF({ ...f, sort: e.target.value as YTFilters["sort"] })} aria-label="Sort">
        <option value="ratio">Overperformance</option>
        <option value="views">Most views</option>
        <option value="date">Newest</option>
        <option value="engagement">Engagement</option>
        <option value="velocity">Early velocity</option>
      </select>

      <button onClick={() => setF({ ...f, sponsored: !f.sponsored })} className={`filter-chip shrink-0 ${f.sponsored ? "active" : ""}`} title="Only videos SponsorBlock flagged as sponsored">
        <MegaphoneIcon size={11} />Sponsored
      </button>

      <div className="flex-1" />
      <span className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>
        {shown}/{total} · <span style={{ color: "var(--warning)" }}>{ovp}</span> ≥{threshold}x
      </span>
      <div className="seg" role="group" aria-label="Layout">
        <button aria-pressed={mode === "grid"} onClick={() => setMode("grid")} aria-label="Grid"><GridIcon /></button>
        <button aria-pressed={mode === "list"} onClick={() => setMode("list")} aria-label="List"><ListIcon /></button>
      </div>
    </div>
  );
}

// ── Articles that embed a video (small modal) ─────────────────────────────
function EmbedsModal({ video, onClose, onOpenArticle }: { video: Video; onClose: () => void; onOpenArticle: (id: number) => void }) {
  const { data, loading, error } = useAsync<Article[]>(() => api.videoArticles(video.id), [video.id], []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "var(--scrim)" }} onClick={onClose}>
      <div className="panel w-full max-w-lg max-h-[80vh] overflow-y-auto p-4 flex flex-col gap-3 drawer" onClick={e => e.stopPropagation()} role="dialog" aria-label="Articles embedding this video">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="label-caps mb-1">Embedded in</div>
            <div className="text-sm font-semibold line-clamp-2" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{video.title}</div>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-1.5 rounded-md hover-surface" style={{ color: "var(--text-muted)" }}><XIcon size={12} /></button>
        </div>
        {loading ? <div className="skeleton h-16" /> : error ? <div className="text-xs" style={{ color: "var(--tier-danger)" }}>{error}</div> : data.length === 0 ? (
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>No tracked article embeds this video any more.</div>
        ) : data.map(a => (
          <button key={a.id} onClick={() => { onOpenArticle(a.id); onClose(); }} className="flex items-center gap-2.5 text-left rounded-lg p-2 hover-surface">
            <SiteIcon site={{ name: a.site_name, icon_url: a.site_icon_url }} size={16} />
            <span className="flex-1 min-w-0">
              <span className="block text-xs truncate" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{a.title}</span>
              <span className="block text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{a.site_name} · {fmtRelative(a.published_at ?? a.first_seen_at)}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Videos tab ─────────────────────────────────────────────────────────────
function VideosTab({ channels, cohort, threshold, onOpenArticle, onGoChannels, tick }: { channels: Channel[]; cohort: string; threshold: number; onOpenArticle: (id: number) => void; onGoChannels: () => void; tick: number }) {
  const [f, setFRaw] = useState<YTFilters>(() => ({ ...DEFAULTS, ...load<Partial<YTFilters>>("webintel.yt.filters", {}) }));
  const setF = (n: YTFilters) => { setFRaw(n); save("webintel.yt.filters", n); };
  const [mode, setMode] = useState<"grid" | "list">(() => load("webintel.yt.mode", "grid"));
  useEffect(() => save("webintel.yt.mode", mode), [mode]);
  const [items, setItems] = useState<Video[]>([]);
  const [total, setTotal] = useState(0);
  const [ovp, setOvp] = useState(0);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [embeds, setEmbeds] = useState<Video | null>(null);
  const query = useMemo(() => toQuery(f, cohort), [f, cohort]);

  useEffect(() => {
    let off = false;
    setLoading(true);
    setError(null);
    api.videos({ ...query, limit: PAGE, offset: 0 })
      .then(r => { if (!off) { setItems(r.items); setTotal(r.total); setOvp(r.overperform_count); setLoading(false); } })
      .catch(e => { if (!off) { setError(e instanceof Error ? e.message : "Couldn't load videos"); setLoading(false); } });
    return () => { off = true; };
  }, [query, tick]);

  const loadMore = async () => {
    setMore(true);
    try {
      const r = await api.videos({ ...query, limit: PAGE, offset: items.length });
      setItems(p => [...p, ...r.items.filter(n => !p.some(x => x.id === n.id))]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load more");
    } finally {
      setMore(false);
    }
  };

  return (
    <>
      <VideoFilterBar f={f} setF={setF} channels={channels} mode={mode} setMode={setMode} shown={items.length} total={total} ovp={ovp} threshold={threshold} />
      {error ? (
        <div className="p-8 text-center text-sm" style={{ color: "var(--tier-danger)" }}>{error}</div>
      ) : !loading && items.length === 0 ? (
        <div className="p-10 flex flex-col items-center gap-3 text-center">
          {channels.length === 0 ? (
            <>
              <div className="text-base font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>No channels tracked yet</div>
              <p className="text-sm max-w-sm" style={{ color: "var(--text-muted)" }}>Add a competitor's YouTube channel and its recent uploads, overperformance and sponsor flags show up here.</p>
              <button onClick={onGoChannels} className="btn-primary text-sm px-4 py-2">Add a channel</button>
            </>
          ) : (
            <>
              <div className="text-base font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>Nothing matches these filters</div>
              <button onClick={() => setF(DEFAULTS)} className="underline text-sm" style={{ color: "var(--accent-light)" }}>Reset filters</button>
            </>
          )}
        </div>
      ) : (
        <div className="p-5">
          <div className={mode === "grid" ? "grid gap-4" : "flex flex-col gap-2"} style={mode === "grid" ? { gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))" } : undefined}>
            {loading ? Array.from({ length: 12 }, (_, i) => <VideoCardSkeleton key={i} mode={mode} />)
              : items.map(v => <VideoCard key={v.id} video={v} mode={mode} metric={f.metric} onShowArticles={setEmbeds} />)}
          </div>
          {!loading && items.length < total && (
            <div className="flex justify-center pt-5">
              <button onClick={loadMore} disabled={more} className="filter-chip" style={{ padding: "8px 18px" }}>{more ? "Loading…" : `Load more (${total - items.length} left)`}</button>
            </div>
          )}
        </div>
      )}
      {embeds && <EmbedsModal video={embeds} onClose={() => setEmbeds(null)} onOpenArticle={onOpenArticle} />}
    </>
  );
}

// ── Posts tab ──────────────────────────────────────────────────────────────
function PostCard({ p }: { p: Post }) {
  const [imgFailed, setImgFailed] = useState(false);
  const maxPoll = p.poll_options?.length ?? 0;
  return (
    <div className="video-card flex flex-col">
      <div className="flex items-center gap-2.5 p-3 pb-2">
        <Avatar url={p.channel_avatar_url} name={p.channel_name} size={28} />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold truncate" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{p.channel_name}</div>
          <div className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{p.published_at ? fmtRelative(p.published_at) : p.published_text ?? fmtRelative(p.first_seen_at)}</div>
        </div>
        {p.post_type && <span className="badge-type text-[9px] px-1.5 py-0.5 rounded uppercase">{p.post_type}</span>}
      </div>
      {p.text && <div className="px-3 text-sm whitespace-pre-line line-clamp-6" style={{ color: "var(--text-secondary)" }}>{p.text}</div>}
      {maxPoll > 0 && (
        <div className="px-3 pt-2 flex flex-col gap-1.5">
          {p.poll_options!.map((o, i) => (
            <div key={i} className="text-xs rounded-md px-2.5 py-1.5" style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}>{String(o)}</div>
          ))}
        </div>
      )}
      {p.image_url && !imgFailed && <img src={p.image_url} alt="" className="mt-2 w-full max-h-64 object-cover" loading="lazy" onError={() => setImgFailed(true)} />}
      {p.video_id && (
        <a href={`https://www.youtube.com/watch?v=${p.video_id}`} target="_blank" rel="noreferrer" className="mx-3 mt-2 text-xs flex items-center gap-1.5 hover:underline" style={{ color: "var(--accent-light)" }}>
          <YTIcon size={12} />Linked video
        </a>
      )}
      <div className="flex items-center gap-3 p-3 mt-auto">
        <span className="flex items-center gap-1 text-[11px] font-mono" style={{ color: "var(--text-muted)" }}><HeartIcon />{fmtViews(p.likes)}</span>
        <span className="flex items-center gap-1 text-[11px] font-mono" style={{ color: "var(--text-muted)" }}><CommentIcon />{fmtViews(p.comments)}</span>
        <span className="flex-1" />
        <ShortlistButton item={{ kind: "post", ref_id: p.id, title: (p.text ?? "Community post").slice(0, 200), url: p.url, source: p.channel_name }} compact />
        {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="p-1.5 rounded-md hover-surface" style={{ color: "var(--text-muted)" }} aria-label="Open on YouTube"><ExternalIcon /></a>}
      </div>
    </div>
  );
}

function PostsTab({ channels, apifySet, tick }: { channels: Channel[]; apifySet: boolean; tick: number }) {
  const [ch, setCh] = useState<number | "">("");
  const [days, setDays] = useState(14);
  const { data, loading, error } = useAsync<Post[]>(() => api.posts({ channels: ch === "" ? undefined : [ch], days }), [ch, days, tick], []);
  return (
    <>
      <div className="sticky top-0 z-30 px-5 py-3 flex flex-wrap items-center gap-2" style={{ background: "var(--surface-translucent)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--border)" }}>
        <select className="select-custom text-xs" value={ch} onChange={e => setCh(e.target.value ? Number(e.target.value) : "")} aria-label="Channel">
          <option value="">All channels</option>
          {channels.filter(c => c.track_posts).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="select-custom text-xs" value={days} onChange={e => setDays(Number(e.target.value))} aria-label="Date range">
          {[3, 7, 14, 30, 90].map(d => <option key={d} value={d}>Last {d} days</option>)}
        </select>
        <span className="flex-1" />
        <span className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>{data.length} posts</span>
      </div>
      {!apifySet && (
        <div className="mx-5 mt-4 panel p-3 text-xs" style={{ color: "var(--text-muted)" }}>
          Community posts come from Apify. Add <code className="font-mono">APIFY_API_TOKEN</code> in Render → webintel-api → Environment to switch them on (once a day at 07:00 IST).
        </div>
      )}
      {error ? <div className="p-8 text-center text-sm" style={{ color: "var(--tier-danger)" }}>{error}</div> : (
        <div className="p-5 grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
          {loading ? Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton h-48" />)
            : data.length === 0 ? <div className="text-sm col-span-full text-center p-8" style={{ color: "var(--text-muted)" }}>No community posts in this window.</div>
            : data.map(p => <PostCard key={p.id} p={p} />)}
        </div>
      )}
    </>
  );
}

// ── Channels tab ───────────────────────────────────────────────────────────
function ChannelsTab({ channels, sites, loading, reload, apiKeySet }: { channels: Channel[]; sites: Site[]; loading: boolean; reload: () => void; apiKeySet: boolean }) {
  const [handle, setHandle] = useState("");
  const [cohort, setCohort] = useState("");
  const [siteId, setSiteId] = useState<number | "">("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const cohorts = Array.from(new Set([...channels.map(c => c.cohort), ...sites.map(s => s.cohort)].filter(Boolean))) as string[];

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!handle.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await api.addChannel({ handle: handle.trim(), cohort: cohort.trim() || undefined, site_id: siteId === "" ? null : siteId });
      setHandle("");
      reload();
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : "Couldn't add the channel");
    } finally {
      setBusy(false);
    }
  };
  const patch = async (c: Channel, body: Parameters<typeof api.updateChannel>[1]) => {
    try { await api.updateChannel(c.id, body); reload(); } catch (x) { setErr(x instanceof ApiError ? x.message : "Update failed"); }
  };
  const remove = async (c: Channel) => {
    if (!window.confirm(`Stop tracking ${c.name}? Its videos and posts are removed from the dashboard.`)) return;
    try { await api.deleteChannel(c.id); reload(); } catch (x) { setErr(x instanceof ApiError ? x.message : "Delete failed"); }
  };

  return (
    <div className="p-5 flex flex-col gap-4 max-w-5xl">
      <form onSubmit={add} className="panel p-4 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 flex-1 min-w-[220px]">
          <span className="label-caps">Channel</span>
          <input value={handle} onChange={e => setHandle(e.target.value)} placeholder="@handle, channel URL or UC… id" className="select-custom text-sm" disabled={!apiKeySet} />
        </label>
        <label className="flex flex-col gap-1 w-36">
          <span className="label-caps">Cohort</span>
          <input value={cohort} onChange={e => setCohort(e.target.value)} list="yt-cohorts" placeholder="optional" className="select-custom text-sm" />
          <datalist id="yt-cohorts">{cohorts.map(c => <option key={c} value={c} />)}</datalist>
        </label>
        <label className="flex flex-col gap-1 w-48">
          <span className="label-caps">Linked website</span>
          <select value={siteId} onChange={e => setSiteId(e.target.value ? Number(e.target.value) : "")} className="select-custom text-sm">
            <option value="">None</option>
            {sites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <button type="submit" disabled={busy || !apiKeySet || !handle.trim()} className="btn-primary text-sm px-4 py-2 flex items-center gap-1.5"><PlusIcon />{busy ? "Adding…" : "Add channel"}</button>
        {!apiKeySet && <div className="w-full text-xs" style={{ color: "var(--warning)" }}>Add <code className="font-mono">YOUTUBE_API_KEY</code> in Render → webintel-api → Environment first.</div>}
        {err && <div className="w-full text-xs" style={{ color: "var(--tier-danger)" }}>{err}</div>}
      </form>

      {loading && channels.length === 0 ? <div className="skeleton h-24" /> : channels.length === 0 ? (
        <div className="text-sm text-center p-6" style={{ color: "var(--text-muted)" }}>No channels yet. Each channel costs about 3 API units a day, so 40 channels fit easily in the free quota.</div>
      ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
          {channels.map(c => (
            <div key={c.id} className="video-card p-4 flex flex-col gap-3" style={{ opacity: c.is_active ? 1 : 0.6 }}>
              <div className="flex items-center gap-3">
                <Avatar url={c.avatar_url} name={c.name} size={40} />
                <div className="flex-1 min-w-0">
                  <a href={`https://www.youtube.com/${c.handle.startsWith("@") ? c.handle : `channel/${c.external_id}`}`} target="_blank" rel="noreferrer"
                    className="text-sm font-semibold truncate block hover:underline" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{c.name}</a>
                  <div className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>{c.handle} · {fmtViews(c.subscriber_count)} subs</div>
                </div>
                <button onClick={() => remove(c)} aria-label={`Remove ${c.name}`} className="p-1.5 rounded-md hover-surface" style={{ color: "var(--text-muted)" }}><TrashIcon /></button>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                {[["Videos", String(c.video_count)], ["Median (10)", fmtViews(c.median_views_last10)], ["Last upload", c.last_published_at ? fmtDate(c.last_published_at) : "—"]].map(([l, v]) => (
                  <div key={l} className="rounded-lg py-1.5" style={{ background: "var(--bg-elevated)" }}>
                    <div className="text-[9px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>{l}</div>
                    <div className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>{v}</div>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input defaultValue={c.cohort ?? ""} placeholder="Cohort" list="yt-cohorts" className="select-custom text-xs w-28"
                  onBlur={e => { if ((e.target.value || null) !== c.cohort) patch(c, { cohort: e.target.value }); }} />
                <select value={c.site_id ?? ""} onChange={e => patch(c, e.target.value ? { site_id: Number(e.target.value) } : { clear_site: true })} className="select-custom text-xs flex-1 min-w-0" aria-label="Linked website">
                  <option value="">No linked site</option>
                  {sites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => patch(c, { track_posts: !c.track_posts })} className={`filter-chip ${c.track_posts ? "active" : ""}`}>Posts {c.track_posts ? "on" : "off"}</button>
                <button onClick={() => patch(c, { is_active: !c.is_active })} className={`filter-chip ${c.is_active ? "active" : ""}`}>{c.is_active ? "Tracking" : "Paused"}</button>
                <span className="flex-1" />
                <span className="text-[10px] font-mono" style={{ color: c.last_error ? "var(--tier-danger)" : "var(--text-muted)" }} title={c.last_error ?? undefined}>
                  {c.last_error ? "Error" : c.last_scraped_at ? `checked ${fmtRelative(c.last_scraped_at)}` : "first scrape queued"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── View ───────────────────────────────────────────────────────────────────
export function YouTubeView({ sites, cohort, onOpenArticle }: { sites: Site[]; cohort: string; onOpenArticle: (id: number) => void }) {
  const [tab, setTab] = useState<Tab>(() => load<Tab>("webintel.yt.tab", "Videos"));
  useEffect(() => save("webintel.yt.tab", tab), [tab]);
  const chAsync = useAsync<Channel[]>(() => api.channels(), [], []);
  const [status, setStatus] = useState<YouTubeStatus | null>(null);
  const [tick, setTick] = useState(0);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.ytStatus().then(setStatus).catch(() => {}); }, [tick]);
  useEffect(() => { if (!msg) return; const t = setTimeout(() => setMsg(null), 6000); return () => clearTimeout(t); }, [msg]);

  const refresh = async () => {
    setBusy(true);
    try {
      await api.ytRefresh(tab === "Posts");
      setMsg({ text: tab === "Posts" ? "Fetching community posts — about a minute" : "Refreshing every channel — about a minute", ok: true });
      setTimeout(() => { setTick(t => t + 1); chAsync.reload(); }, 50_000);
    } catch (e) {
      setMsg({ text: e instanceof ApiError ? e.message : "Refresh failed", ok: false });
    } finally {
      setBusy(false);
    }
  };

  const quotaPct = status ? Math.min(100, Math.round((status.quota_used_today / Math.max(1, status.quota_budget)) * 100)) : 0;

  return (
    <div className="flex-1 min-w-0 overflow-y-auto">
      <div className="px-5 pt-3 flex flex-wrap items-center gap-3">
        <div className="seg" role="tablist">
          {(["Videos", "Posts", "Channels"] as Tab[]).map(t => (
            <button key={t} role="tab" aria-pressed={tab === t} aria-selected={tab === t} onClick={() => setTab(t)}>
              {t}{t === "Channels" && chAsync.data.length ? ` · ${chAsync.data.length}` : ""}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        {status && (
          <span className="flex items-center gap-2 text-[11px] font-mono" style={{ color: "var(--text-muted)" }} title="YouTube Data API units used today (resets 12:30 IST)">
            Quota
            <span className="w-20 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-active)" }}>
              <span className="block h-full" style={{ width: `${quotaPct}%`, background: quotaPct > 85 ? "var(--tier-danger)" : "var(--accent)" }} />
            </span>
            {status.quota_used_today.toLocaleString()}/{status.quota_budget.toLocaleString()}
            <span>· scraped {fmtRelative(status.last_scrape_at)}</span>
          </span>
        )}
        {msg && <span className="text-[11px] px-2 py-1 rounded-md" style={{ color: msg.ok ? "var(--accent-light)" : "var(--tier-danger)", border: `1px solid ${msg.ok ? "var(--accent)" : "var(--tier-danger)"}` }}>{msg.text}</span>}
        {tab !== "Channels" && (
          <button onClick={refresh} disabled={busy || !status?.api_key_set} className="flex items-center gap-1.5 rounded-lg h-8 px-3 hover-surface disabled:opacity-50" style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}>
            <span className={busy ? "animate-spin" : undefined}><RefreshIcon size={12} /></span>
            <span className="text-xs" style={{ fontFamily: "Lora, serif" }}>{tab === "Posts" ? "Fetch posts" : "Refresh YouTube"}</span>
          </button>
        )}
      </div>
      {status && !status.api_key_set && tab !== "Channels" && (
        <div className="mx-5 mt-3 panel p-3 text-xs" style={{ color: "var(--text-muted)" }}>
          YouTube tracking is off until <code className="font-mono">YOUTUBE_API_KEY</code> is set in Render → webintel-api → Environment. The DEPLOYMENT guide has the 3-minute setup.
        </div>
      )}
      <div className="mt-3">
        {tab === "Videos" && <VideosTab channels={chAsync.data} cohort={cohort} threshold={status?.overperform_threshold ?? 2} onOpenArticle={onOpenArticle} onGoChannels={() => setTab("Channels")} tick={tick} />}
        {tab === "Posts" && <PostsTab channels={chAsync.data} apifySet={status?.apify_set ?? true} tick={tick} />}
        {tab === "Channels" && <ChannelsTab channels={chAsync.data} sites={sites} loading={chAsync.loading} reload={() => { chAsync.reload(); setTick(t => t + 1); }} apiKeySet={status?.api_key_set ?? true} />}
      </div>
    </div>
  );
}
