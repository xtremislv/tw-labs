import React, { useState } from "react";
import type { Article } from "../lib/api";
import { CONTENT_TYPE_LABEL, fmtDateTime, fmtNum, fmtRelative } from "../lib/format";
import { ClockIcon, PenIcon, WordsIcon } from "./icons";
import { SiteIcon } from "./SiteIcon";
import type { ViewMode } from "./FilterBar";

const RECENT_MS = 24 * 3600_000;

/** New = published in the last 24 h and found by live polling (not the
 * initial 30-day import). Updated = we detected a real content edit. */
export function articleBadges(a: Article) {
  const updated = a.update_count > 0 && a.last_updated_at != null;
  const fresh = !a.is_backfill && a.published_at != null && Date.now() - new Date(a.published_at).getTime() < RECENT_MS;
  return { updated, fresh };
}

function Badges({ a, small }: { a: Article; small?: boolean }) {
  const { updated, fresh } = articleBadges(a);
  const cls = `${small ? "text-[9px]" : "text-[10px]"} px-1.5 py-0.5 rounded-sm font-bold`;
  return (
    <>
      {updated && <span className={`badge-updated ${cls}`} title={a.latest_change ?? "Content edited after publishing"}>UPDATED{a.update_count > 1 ? ` ×${a.update_count}` : ""}</span>}
      {fresh && !updated && <span className={`badge-new ${cls}`}>NEW</span>}
      {a.content_type && a.content_type !== "news" && <span className={`badge-type ${cls}`}>{CONTENT_TYPE_LABEL[a.content_type]?.toUpperCase()}</span>}
    </>
  );
}

function Thumb({ a, className }: { a: Article; className: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={`relative overflow-hidden ${className}`} style={{ background: "var(--bg-elevated)" }}>
      {a.thumbnail_url && !failed ? (
        <img src={a.thumbnail_url} alt="" className="size-full object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
      ) : (
        <div className="size-full flex items-center justify-center"><SiteIcon site={{ name: a.site_name, icon_url: a.site_icon_url }} size={28} /></div>
      )}
    </div>
  );
}

interface CardProps {
  article: Article;
  mode: ViewMode;
  unread: boolean;
  selected: boolean;
  onOpen: (id: number) => void;
}

export const ArticleCard = React.memo(function ArticleCard({ article: a, mode, unread, selected, onOpen }: CardProps) {
  const when = a.update_count > 0 && a.last_updated_at ? a.last_updated_at : a.published_at;
  const whenLabel = a.update_count > 0 && a.last_updated_at ? "Updated" : "Published";
  const open = () => onOpen(a.id);
  const keyOpen = (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };

  if (mode === "list") {
    return (
      <div role="button" tabIndex={0} onClick={open} onKeyDown={keyOpen} className={`video-card flex items-center gap-4 p-3 cursor-pointer group ${selected ? "selected" : ""}`}>
        <Thumb a={a} className="shrink-0 rounded-lg w-28 h-[4.5rem] hidden sm:block" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {unread && <span className="unread-dot" title="New since your last visit" />}
            <div className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{a.title}</div>
          </div>
          <div className="flex items-center gap-2 flex-wrap text-xs" style={{ color: "var(--text-muted)" }}>
            <SiteIcon site={{ name: a.site_name, icon_url: a.site_icon_url }} size={13} />
            <span style={{ fontFamily: "Lora, serif" }}>{a.site_name}</span>
            {a.author && <><span>·</span><span className="truncate max-w-[10rem]">{a.author}</span></>}
            {a.section && <><span>·</span><span>{a.section}</span></>}
            {a.latest_change && <><span>·</span><span className="truncate max-w-[18rem]" style={{ color: "var(--warning)" }}>{a.latest_change}</span></>}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0"><Badges a={a} /></div>
        <div className="text-right shrink-0 w-20 hidden md:block">
          <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{fmtNum(a.word_count)}</div>
          <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>words</div>
        </div>
        <div className="text-right shrink-0 w-24">
          <div className="text-xs font-mono" style={{ color: "var(--text-secondary)" }} title={fmtDateTime(when)}>{fmtRelative(when)}</div>
          <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>{whenLabel}</div>
        </div>
      </div>
    );
  }

  return (
    <div role="button" tabIndex={0} onClick={open} onKeyDown={keyOpen} className={`video-card cursor-pointer group flex flex-col ${selected ? "selected" : ""}`}>
      <div className="relative">
        <Thumb a={a} className="w-full aspect-video" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent pointer-events-none" />
        <div className="absolute top-2 left-2 flex gap-1 flex-wrap"><Badges a={a} small /></div>
        {(a.youtube_ids?.length ?? 0) > 0 && (
          <span className="absolute bottom-2 right-2 text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: "rgba(0,0,0,0.8)", color: "#fff" }} title="Embeds YouTube video(s)">▶ {a.youtube_ids!.length}</span>
        )}
      </div>
      <div className="p-3 flex flex-col gap-2 flex-1">
        <div className="flex items-start gap-2">
          {unread && <span className="unread-dot mt-1.5" title="New since your last visit" />}
          <div className="text-sm font-semibold leading-snug line-clamp-2" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{a.title}</div>
        </div>
        <div className="flex items-center gap-1.5 min-w-0">
          <SiteIcon site={{ name: a.site_name, icon_url: a.site_icon_url }} size={13} />
          <span className="text-xs truncate" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>{a.site_name}</span>
          {a.section && <span className="text-xs truncate" style={{ color: "var(--text-muted)" }}>· {a.section}</span>}
        </div>
        {a.latest_change && (
          <div className="text-[11px] leading-snug line-clamp-2" style={{ color: "var(--warning)" }}>↻ {a.latest_change}</div>
        )}
        <div className="flex items-center gap-3 mt-auto pt-2 text-[11px] font-mono" style={{ borderTop: "1px solid var(--border)", color: "var(--text-muted)" }}>
          <span className="flex items-center gap-1" title={`${whenLabel} ${fmtDateTime(when)}`}><ClockIcon />{fmtRelative(when)}</span>
          <span className="flex items-center gap-1" title="Word count"><WordsIcon />{fmtNum(a.word_count)}</span>
          {a.author && <span className="flex items-center gap-1 truncate min-w-0" title="Author"><PenIcon /><span className="truncate">{a.author}</span></span>}
        </div>
      </div>
    </div>
  );
});

export function ArticleCardSkeleton({ mode }: { mode: ViewMode }) {
  if (mode === "list") {
    return (
      <div className="video-card flex items-center gap-4 p-3">
        <div className="skeleton w-28 h-[4.5rem] hidden sm:block" />
        <div className="flex-1 flex flex-col gap-2"><div className="skeleton h-4 w-3/4" /><div className="skeleton h-3 w-1/3" /></div>
      </div>
    );
  }
  return (
    <div className="video-card flex flex-col">
      <div className="skeleton w-full aspect-video" style={{ borderRadius: 0 }} />
      <div className="p-3 flex flex-col gap-2"><div className="skeleton h-4 w-full" /><div className="skeleton h-4 w-2/3" /><div className="skeleton h-3 w-1/3 mt-2" /></div>
    </div>
  );
}
