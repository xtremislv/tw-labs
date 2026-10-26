import React, { useMemo, useState } from "react";
import { api, ApiError, type ShortlistItem, type Video } from "../lib/api";
import { fmtDate, fmtDuration, fmtViews, overlayRatioColor, ratioColor } from "../lib/format";
import { CommentIcon, HeartIcon, LinkIcon, MegaphoneIcon, StarIcon, TrendUpIcon, YTIcon, ZapIcon } from "./icons";

export type Metric = "average" | "median";

/** Same mini sparkline as TW-Labs: a flat-ish line that jumps by the ratio. */
export function Sparkline({ ratio, color }: { ratio: number; color: string }) {
  const pts = useMemo(() => {
    const seed = ratio * 100;
    const vals = [40, 55, 45, 70, 60, seed * 0.9, seed];
    const max = Math.max(...vals);
    return vals.map((v, i) => `${(i / (vals.length - 1)) * 60},${20 - (v / max) * 18}`).join(" ");
  }, [ratio]);
  return (
    <svg width="60" height="20" viewBox="0 0 60 20" aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Adds an item to the team shortlist. Works inside a link card (stops the click). */
export function ShortlistButton({ item, initial = false, compact = false }: {
  item: { kind: ShortlistItem["kind"]; ref_id?: string | null; title: string; url?: string | null; source?: string | null };
  initial?: boolean;
  compact?: boolean;
}) {
  const [done, setDone] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const click = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (done || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await api.addShortlist(item);
      setDone(true);
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : "Couldn't add");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button onClick={click} disabled={busy} title={err ?? (done ? "On the shortlist" : "Add to the team shortlist")}
      aria-label={done ? "On the shortlist" : "Add to shortlist"}
      className={compact ? "flex items-center justify-center rounded-md size-7 hover-surface shrink-0" : "flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs hover-surface shrink-0"}
      style={{ color: err ? "var(--tier-danger)" : done ? "var(--warning)" : "var(--text-muted)", border: "1px solid var(--border)" }}>
      <StarIcon filled={done} size={12} />
      {!compact && <span style={{ fontFamily: "Lora, serif" }}>{done ? "Shortlisted" : "Shortlist"}</span>}
    </button>
  );
}

function Velocity({ v }: { v: Video }) {
  const cps: [string, number | null, number | null][] = [["1h", v.h1_views, v.h1_ratio], ["3h", v.h3_views, v.h3_ratio], ["6h", v.h6_views, v.h6_ratio]];
  if (cps.every(c => c[1] == null)) return null;
  return (
    <div className="flex items-center gap-2 text-[10px] font-mono" title="Views at 1 h / 3 h / 6 h after upload, against this channel's usual pace at the same age">
      <span style={{ color: "var(--text-muted)" }}><ZapIcon size={10} /></span>
      {cps.map(([l, views, r]) => (
        <span key={l} style={{ color: views == null ? "var(--text-muted)" : ratioColor(r) }}>
          {l} {views == null ? "—" : r != null ? `${r.toFixed(1)}x` : fmtViews(views)}
        </span>
      ))}
    </div>
  );
}

export function VideoCardSkeleton({ mode }: { mode: "grid" | "list" }) {
  if (mode === "list") {
    return (
      <div className="video-card flex items-center gap-4 p-3">
        <div className="skeleton shrink-0 w-32 h-20" />
        <div className="flex-1 flex flex-col gap-2"><div className="skeleton h-3.5 w-3/4" /><div className="skeleton h-3 w-1/3" /></div>
      </div>
    );
  }
  return (
    <div className="video-card flex flex-col">
      <div className="skeleton w-full aspect-video" style={{ borderRadius: 0 }} />
      <div className="p-3 flex flex-col gap-2"><div className="skeleton h-3.5 w-5/6" /><div className="skeleton h-3 w-1/2" /></div>
    </div>
  );
}

export const VideoCard = React.memo(function VideoCard({ video, mode, metric, onShowArticles }: {
  video: Video;
  mode: "grid" | "list";
  metric: Metric;
  onShowArticles?: (v: Video) => void;
}) {
  const ratio = metric === "median" ? video.overperform_ratio_median : video.overperform_ratio;
  const baseline = metric === "median" ? video.median_views_baseline : video.avg_views_baseline;
  const color = ratioColor(ratio);
  const [thumbFailed, setThumbFailed] = useState(false);
  const thumb = thumbFailed ? null : video.thumbnail_url;
  const sponsorTitle = video.sponsor_segment_seconds != null ? `~${Math.round(video.sponsor_segment_seconds)}s sponsored segment (via SponsorBlock)` : "Sponsored segment detected (via SponsorBlock)";
  const shortlist = { kind: "video" as const, ref_id: video.id, title: video.title, url: video.url, source: video.channel_name };

  const embeds = video.embedded_in > 0 && (
    <button onClick={e => { e.preventDefault(); e.stopPropagation(); onShowArticles?.(video); }}
      className="badge-type text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1" title="Tracked articles that embed this video">
      <LinkIcon size={9} />in {video.embedded_in} article{video.embedded_in === 1 ? "" : "s"}
    </button>
  );

  if (mode === "list") {
    return (
      <a href={video.url} target="_blank" rel="noreferrer" className="video-card flex flex-wrap items-center gap-4 p-3 group">
        <div className="relative shrink-0 rounded-lg overflow-hidden w-32 h-20" style={{ background: "var(--bg-elevated)" }}>
          {thumb && <img src={thumb} alt="" className="size-full object-cover" loading="lazy" onError={() => setThumbFailed(true)} />}
          <div className="absolute bottom-1 right-1 text-[10px] px-1 rounded font-mono" style={{ background: "rgba(0,0,0,0.75)", color: "#fff" }}>{fmtDuration(video.duration_seconds)}</div>
          {video.format === "short" && <div className="absolute top-1 left-1 text-[9px] px-1 rounded font-mono" style={{ background: "rgba(0,0,0,0.75)", color: "#fff" }}>SHORT</div>}
        </div>
        <div className="flex-1 min-w-[160px]">
          <div className="text-sm font-semibold truncate mb-1" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{video.title}</div>
          <div className="flex items-center gap-3 flex-wrap text-xs" style={{ color: "var(--text-muted)" }}>
            <span style={{ fontFamily: "Lora, serif" }}>{video.channel_name}</span>
            <span className="font-mono">{fmtDate(video.published_at)}</span>
            <span className="flex items-center gap-1 font-mono" title="Likes"><HeartIcon />{fmtViews(video.likes)}</span>
            <span className="flex items-center gap-1 font-mono" title="Comments"><CommentIcon />{fmtViews(video.comments)}</span>
            <Velocity v={video} />
            {embeds}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 sm:gap-6 shrink-0">
          <div className="text-right">
            <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{fmtViews(video.views)}</div>
            <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>views</div>
          </div>
          <div className="text-right">
            <div className="text-sm font-bold font-mono flex items-center gap-1" style={{ color }}><TrendUpIcon />{ratio == null ? "—" : `${ratio.toFixed(1)}x`}</div>
            <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>{metric === "median" ? "vs median" : "vs avg"}</div>
          </div>
          <Sparkline ratio={ratio ?? 1} color={color} />
          {ratio != null && ratio >= 2 && <span className="badge-overperform text-[10px] px-2 py-0.5 rounded-full font-bold">OVP</span>}
          {video.has_sponsor_segment && <span className="badge-sponsor flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-bold" title={sponsorTitle}><MegaphoneIcon size={9} />SPONSORED</span>}
          <ShortlistButton item={shortlist} compact />
        </div>
      </a>
    );
  }

  return (
    <a href={video.url} target="_blank" rel="noreferrer" className="video-card group flex flex-col">
      <div className="relative w-full aspect-video overflow-hidden" style={{ background: "var(--bg-elevated)" }}>
        {thumb ? (
          <img src={thumb} alt="" className="size-full object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy" onError={() => setThumbFailed(true)} />
        ) : (
          <div className="size-full flex items-center justify-center" style={{ color: "var(--text-muted)" }}><YTIcon size={28} /></div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
        <div className="absolute bottom-2 right-2 text-[10px] px-1.5 py-0.5 rounded font-mono font-medium" style={{ background: "rgba(0,0,0,0.8)", color: "#fff" }}>{fmtDuration(video.duration_seconds)}</div>
        <div className="absolute top-2 left-2 flex gap-1">
          <span className="text-[10px] px-1.5 py-0.5 rounded-sm flex items-center gap-1 font-mono" style={{ background: "rgba(255,0,0,0.85)", color: "#fff" }}>
            <YTIcon size={9} />{video.format === "short" ? "SHORT" : "YT"}
          </span>
          {video.has_sponsor_segment && <span className="badge-sponsor text-[10px] px-1.5 py-0.5 rounded-sm flex items-center gap-1" style={{ background: "rgba(10,12,18,0.85)", color: "#fbbf24" }} title={sponsorTitle}><MegaphoneIcon size={9} />SPONSORED</span>}
        </div>
        <div className="absolute top-2 right-2">
          <span className="text-[10px] px-1.5 py-0.5 rounded-sm font-mono font-bold flex items-center gap-1"
            style={{ background: "rgba(10,12,18,0.92)", color: overlayRatioColor(ratio), border: `1px solid ${overlayRatioColor(ratio)}` }}>
            <TrendUpIcon />{ratio == null ? "New" : `${ratio.toFixed(1)}x`}
          </span>
        </div>
      </div>

      <div className="p-3 flex flex-col gap-2 flex-1">
        <div className="text-sm font-semibold leading-snug line-clamp-2" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{video.title}</div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs truncate" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>{video.channel_name}</span>
          <span className="text-[11px] font-mono shrink-0" style={{ color: "var(--text-muted)" }}>{fmtDate(video.published_at)}</span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="flex items-center gap-1 text-[11px] font-mono" style={{ color: "var(--text-muted)" }} title="Likes"><HeartIcon />{fmtViews(video.likes)}</span>
          <span className="flex items-center gap-1 text-[11px] font-mono" style={{ color: "var(--text-muted)" }} title="Comments"><CommentIcon />{fmtViews(video.comments)}</span>
          {embeds}
        </div>
        <Velocity v={video} />
        <div className="flex items-center gap-3 mt-auto pt-2" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="flex-1">
            <div className="text-[10px] mb-0.5" style={{ color: "var(--text-muted)" }}>Views</div>
            <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{fmtViews(video.views)}</div>
          </div>
          <div className="flex-1">
            <div className="text-[10px] mb-0.5" style={{ color: "var(--text-muted)" }}>{metric === "median" ? "Median" : "Avg"}</div>
            <div className="text-sm font-mono" style={{ color: "var(--text-muted)" }}>{fmtViews(baseline == null ? null : Math.round(baseline))}</div>
          </div>
          <Sparkline ratio={ratio ?? 1} color={color} />
          <ShortlistButton item={shortlist} compact />
        </div>
      </div>
    </a>
  );
});
