import { useEffect, useState } from "react";
import { api, type ArticleDetail, type Video } from "../lib/api";
import { CONTENT_TYPE_LABEL, SOURCE_LABEL, fmtDateTime, fmtNum, fmtRelative, fmtViews, ratioColor } from "../lib/format";
import { ShortlistButton } from "./VideoCard";
import { useAsync } from "../hooks/useAsync";
import { ExternalIcon, LinkIcon, XIcon } from "./icons";
import { SiteIcon } from "./SiteIcon";

function Stat({ label, value, title }: { label: string; value: React.ReactNode; title?: string }) {
  return (
    <div className="rounded-lg px-3 py-2" style={{ background: "var(--bg-elevated)" }} title={title}>
      <div className="text-[10px] uppercase tracking-wider mb-0.5" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>{label}</div>
      <div className="text-sm font-mono font-semibold" style={{ color: "var(--text-primary)" }}>{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>{title}</h3>
      {children}
    </section>
  );
}

export function ArticleDrawer({ articleId, onClose, onOpenOther }: { articleId: number; onClose: () => void; onOpenOther: (id: number) => void }) {
  const { data: a, loading, error, reload } = useAsync<ArticleDetail | null>(() => api.article(articleId), [articleId], null);
  const [copied, setCopied] = useState<string | null>(null);
  // Embedded videos that belong to tracked channels (with their stats).
  const ytKey = a?.youtube_ids?.join(",") ?? "";
  const tracked = useAsync<Video[]>(() => (ytKey ? api.videosByIds(ytKey.split(",")) : Promise.resolve([])), [ytKey], []);
  const trackedById = new Map(tracked.data.map(v => [v.id, v]));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      setCopied("Couldn't copy");
    }
  };

  const brief = a
    ? [
        `${a.title}`,
        `${a.site_name} · ${a.author ?? "unknown author"} · ${fmtDateTime(a.published_at)}`,
        a.url,
        a.excerpt ? `\n${a.excerpt}` : "",
        a.headings?.length ? `\nSections: ${a.headings.slice(0, 8).join(" / ")}` : "",
        a.also_covered_by.length ? `\nAlso covered by: ${a.also_covered_by.map(o => o.site_name).join(", ")}` : "",
      ].filter(Boolean).join("\n")
    : "";

  return (
    <>
      <div className="fixed inset-0 z-40 md:hidden" style={{ background: "var(--scrim)" }} onClick={onClose} />
      <aside className="drawer fixed md:static right-0 top-0 bottom-0 z-50 w-full sm:w-[440px] md:w-[420px] lg:w-[460px] shrink-0 flex flex-col overflow-hidden"
        style={{ background: "var(--bg-panel)", borderLeft: "1px solid var(--border)" }} aria-label="Article details">
        <div className="flex items-center justify-between px-4 py-3 shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
          <span className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Article</span>
          <div className="flex items-center gap-1">
            {copied && <span className="text-[11px] mr-1" style={{ color: "var(--accent-light)" }}>{copied}</span>}
            <button onClick={onClose} aria-label="Close article" className="p-1.5 rounded-md hover-surface" style={{ color: "var(--text-muted)" }}><XIcon size={14} /></button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">
          {loading && !a ? (
            <div className="flex flex-col gap-3"><div className="skeleton w-full aspect-video" /><div className="skeleton h-5 w-5/6" /><div className="skeleton h-4 w-1/2" /></div>
          ) : error ? (
            <div className="text-sm" style={{ color: "var(--tier-danger)" }}>
              {error} <button onClick={reload} className="underline ml-1" style={{ color: "var(--accent-light)" }}>Retry</button>
            </div>
          ) : a ? (
            <>
              {a.thumbnail_url && <img src={a.thumbnail_url} alt="" className="w-full aspect-video object-cover rounded-lg" referrerPolicy="no-referrer" onError={e => (e.currentTarget.style.display = "none")} />}
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
                  <SiteIcon site={{ name: a.site_name, icon_url: a.site_icon_url }} size={14} />
                  <span style={{ fontFamily: "Lora, serif" }}>{a.site_name}</span>
                  {a.section && <span>· {a.section}</span>}
                  {a.content_type && <span className="badge-type text-[9px] px-1.5 py-0.5 rounded-sm font-bold">{CONTENT_TYPE_LABEL[a.content_type]?.toUpperCase()}</span>}
                </div>
                <h2 className="text-lg font-semibold leading-snug" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{a.title}</h2>
                {a.excerpt && <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{a.excerpt}</p>}
                <div className="flex flex-wrap gap-2 pt-1">
                  <a href={a.url} target="_blank" rel="noreferrer" className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5"><ExternalIcon />Open original</a>
                  <button onClick={() => copy(a.url, "Link copied")} className="text-xs px-3 py-1.5 rounded-lg hover-surface flex items-center gap-1.5" style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}><LinkIcon />Copy link</button>
                  <ShortlistButton key={a.id} item={{ kind: "article", ref_id: String(a.id), title: a.title ?? a.url, url: a.url, source: a.site_name }} />
                  <button onClick={() => copy(brief, "Brief copied")} className="text-xs px-3 py-1.5 rounded-lg hover-surface" style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }} title="Title, source, link, summary and outline — ready to paste into a pitch">Copy brief</button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <Stat label="Published" value={fmtRelative(a.published_at)} title={fmtDateTime(a.published_at)} />
                <Stat label="Last edit" value={a.last_updated_at ? fmtRelative(a.last_updated_at) : "—"} title={a.last_updated_at ? fmtDateTime(a.last_updated_at) : "No content edits detected"} />
                <Stat label="Words" value={fmtNum(a.word_count)} />
                <Stat label="Author" value={<span className="font-sans text-xs">{a.author ?? "—"}</span>} />
                <Stat label="Images" value={a.image_count ?? "—"} />
                <Stat label="Affiliate links" value={a.affiliate_link_count ?? "—"} title="Amazon / Flipkart / deal-network links inside the article" />
              </div>

              {(a.own_clicks_28d != null || a.own_views_28d != null) && (
                <Section title="Our performance · last 28 days">
                  <div className="grid grid-cols-2 gap-2">
                    <Stat label="Search clicks" value={fmtNum(a.own_clicks_28d)} />
                    <Stat label="Impressions" value={fmtNum(a.own_impressions_28d)} />
                    <Stat label="Avg position" value={a.own_position != null ? a.own_position.toFixed(1) : "—"} />
                    <Stat label="Page views (GA4)" value={fmtNum(a.own_views_28d)} />
                  </div>
                </Section>
              )}

              {a.versions.length > 0 && (
                <Section title={`Edit history · ${a.versions.length}`}>
                  <ol className="flex flex-col gap-2">
                    {a.versions.map(v => (
                      <li key={v.id} className="rounded-lg p-3 text-xs flex flex-col gap-1" style={{ background: "var(--bg-elevated)", borderLeft: "3px solid var(--warning)" }}>
                        <div className="font-mono" style={{ color: "var(--text-muted)" }}>{fmtDateTime(v.seen_at)}</div>
                        <div style={{ color: "var(--text-primary)" }}>{v.summary}</div>
                        {v.old_title && v.new_title && v.old_title !== v.new_title && (
                          <div style={{ color: "var(--text-secondary)" }}><s style={{ color: "var(--text-muted)" }}>{v.old_title}</s><br />→ {v.new_title}</div>
                        )}
                        {v.old_word_count != null && v.new_word_count != null && (
                          <div className="font-mono" style={{ color: "var(--text-muted)" }}>{v.old_word_count} → {v.new_word_count} words</div>
                        )}
                      </li>
                    ))}
                  </ol>
                </Section>
              )}

              {a.also_covered_by.length > 0 && (
                <Section title={`Also covered by · ${a.also_covered_by.length}`}>
                  <div className="flex flex-col gap-1">
                    {a.also_covered_by.map(o => (
                      <button key={o.id} onClick={() => onOpenOther(o.id)} className="text-left rounded-lg px-3 py-2 hover-surface flex items-start gap-2" style={{ border: "1px solid var(--border)" }}>
                        <SiteIcon site={{ name: o.site_name, icon_url: o.site_icon_url }} size={14} />
                        <span className="flex-1 min-w-0">
                          <span className="block text-xs leading-snug" style={{ color: "var(--text-primary)" }}>{o.title}</span>
                          <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{o.site_name} · {fmtRelative(o.published_at)}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                </Section>
              )}

              {(a.headings?.length ?? 0) > 0 && (
                <Section title="Outline (H2s)">
                  <ul className="flex flex-col gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                    {a.headings!.map((h, i) => <li key={i} className="pl-3" style={{ borderLeft: "2px solid var(--border)" }}>{h}</li>)}
                  </ul>
                </Section>
              )}

              {(a.youtube_ids?.length ?? 0) > 0 && (
                <Section title="Embedded YouTube videos">
                  <div className="flex flex-col gap-1">
                    {a.youtube_ids!.map(id => {
                      const v = trackedById.get(id);
                      return v ? (
                        <a key={id} href={v.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-lg p-1.5 hover-surface" style={{ border: "1px solid var(--border)" }}>
                          {v.thumbnail_url ? <img src={v.thumbnail_url} alt="" className="w-20 h-11 rounded object-cover shrink-0" loading="lazy" /> : null}
                          <span className="flex-1 min-w-0">
                            <span className="block text-xs truncate" style={{ color: "var(--text-primary)" }}>{v.title}</span>
                            <span className="block text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>
                              {v.channel_name} · {fmtViews(v.views)} views
                              {v.overperform_ratio_median != null && <> · <span style={{ color: ratioColor(v.overperform_ratio_median) }}>{v.overperform_ratio_median.toFixed(1)}x</span></>}
                            </span>
                          </span>
                          <span className="badge-own text-[9px] px-1 rounded shrink-0">TRACKED</span>
                        </a>
                      ) : (
                        <a key={id} href={`https://www.youtube.com/watch?v=${id}`} target="_blank" rel="noreferrer" className="text-xs font-mono hover:underline flex items-center gap-1.5" style={{ color: "var(--accent-light)" }}>
                          <ExternalIcon />youtube.com/watch?v={id}
                        </a>
                      );
                    })}
                  </div>
                </Section>
              )}

              {(a.tags?.length ?? 0) > 0 && (
                <Section title="Tags">
                  <div className="flex flex-wrap gap-1">{a.tags!.map(t => <span key={t} className="filter-chip" style={{ cursor: "default", fontSize: 11 }}>{t}</span>)}</div>
                </Section>
              )}

              <Section title="Tracking">
                <div className="text-[11px] font-mono flex flex-col gap-0.5" style={{ color: "var(--text-muted)" }}>
                  <span>First seen {fmtDateTime(a.first_seen_at)}{a.is_backfill ? " (initial import)" : ""}</span>
                  {a.discovered_via && <span>Found via {SOURCE_LABEL[a.discovered_via] ?? a.discovered_via}</span>}
                  {a.modified_at && <span>Site's own "modified" date: {fmtDateTime(a.modified_at)}</span>}
                  {a.enrich_status !== "ok" && <span>Status: {a.enrich_status === "pending" ? "waiting to be read" : a.enrich_status}</span>}
                </div>
              </Section>
            </>
          ) : null}
        </div>
      </aside>
    </>
  );
}
