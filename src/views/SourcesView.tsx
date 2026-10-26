import { useEffect, useState } from "react";
import { api, ApiError, type Health, type Site, type SiteDetail, type SitemapCheck } from "../lib/api";
import { SOURCE_LABEL, fmtDateTime, fmtRelative } from "../lib/format";
import { useAsync } from "../hooks/useAsync";
import { ChevronDown, PauseIcon, PlayIcon, PlusIcon, RefreshIcon, TrashIcon } from "../components/icons";
import { SiteIcon } from "../components/SiteIcon";

const HEALTH: Record<Health, { label: string; color: string }> = {
  ok: { label: "Healthy", color: "var(--success)" },
  warning: { label: "Check sources", color: "var(--warning)" },
  error: { label: "Failing", color: "var(--tier-danger)" },
  pending: { label: "Setting up…", color: "var(--tier-blue)" },
};

function HealthDot({ health }: { health: Health }) {
  const h = HEALTH[health];
  return (
    <span className="flex items-center gap-1.5 text-[11px]" style={{ color: h.color }}>
      <span className={`size-2 rounded-full ${health === "pending" ? "animate-pulse" : ""}`} style={{ background: h.color }} />
      {h.label}
    </span>
  );
}

function AddSiteForm({ onAdded }: { onAdded: () => void }) {
  const [url, setUrl] = useState("");
  const [cohort, setCohort] = useState("");
  const [own, setOwn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await api.addSite({ url: url.trim(), cohort: cohort.trim() || undefined, is_own_site: own });
      setUrl("");
      setOwn(false);
      onAdded();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Couldn't add that site.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="rounded-xl p-4 flex flex-col gap-3" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
      <div>
        <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>Track a website</h2>
        <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
          Paste the site's address. Web Intel finds its sitemaps, RSS and WordPress feeds automatically, then imports the last 30 days.
        </p>
      </div>
      <div className="flex flex-wrap gap-2 items-end">
        <label className="flex flex-col gap-1 flex-1 min-w-[220px]">
          <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Website</span>
          <input value={url} onChange={e => setUrl(e.target.value)} placeholder="example.com" className="select-custom text-sm" autoComplete="off" />
        </label>
        <label className="flex flex-col gap-1 w-44">
          <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Cohort (optional)</span>
          <input value={cohort} onChange={e => setCohort(e.target.value)} placeholder="Tech news" className="select-custom text-sm" list="cohort-suggestions" />
        </label>
        <label className="flex items-center gap-2 text-xs pb-2 cursor-pointer" style={{ color: "var(--text-secondary)" }} title="Mark techwiser.com as our own site, used as the benchmark">
          <input type="checkbox" checked={own} onChange={e => setOwn(e.target.checked)} className="accent-indigo-400" />
          This is our site
        </label>
        <button type="submit" disabled={busy || !url.trim()} className="btn-primary text-sm px-4 py-2 flex items-center gap-1.5">
          <PlusIcon />{busy ? "Adding…" : "Add site"}
        </button>
      </div>
      {err && <div className="text-xs" style={{ color: "var(--tier-danger)" }}>{err}</div>}
    </form>
  );
}

function SiteRowDetail({ siteId }: { siteId: number }) {
  const detail = useAsync<SiteDetail | null>(() => api.site(siteId), [siteId], null);
  const jobs = useAsync(() => api.jobs(siteId), [siteId], []);
  if (detail.loading && !detail.data) return <div className="p-4"><div className="skeleton h-20 w-full" /></div>;
  if (detail.error) return <div className="p-4 text-xs" style={{ color: "var(--tier-danger)" }}>{detail.error}</div>;
  const d = detail.data!;
  return (
    <div className="px-4 pb-4 flex flex-col gap-4">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ color: "var(--text-muted)" }} className="text-left">
              <th className="py-1.5 pr-3 font-normal">Source</th>
              <th className="py-1.5 pr-3 font-normal">Role</th>
              <th className="py-1.5 pr-3 font-normal">Last OK</th>
              <th className="py-1.5 pr-3 font-normal">Items</th>
              <th className="py-1.5 font-normal">Status</th>
            </tr>
          </thead>
          <tbody>
            {d.sources.map((s, i) => {
              const fast = s.kind !== "sitemap" && d.fast_source === s.kind;
              return (
                <tr key={s.id} style={{ borderTop: "1px solid var(--border)", color: "var(--text-secondary)" }}>
                  <td className="py-2 pr-3">
                    <div>{SOURCE_LABEL[s.kind]}</div>
                    <a href={s.url} target="_blank" rel="noreferrer" className="font-mono text-[10px] hover:underline break-all" style={{ color: "var(--text-muted)" }}>{s.url}</a>
                  </td>
                  <td className="py-2 pr-3 whitespace-nowrap">
                    {fast ? <span className="badge-new text-[9px] px-1.5 py-0.5 rounded-sm font-bold">FAST · 15 MIN</span>
                      : s.kind === "sitemap" ? <span style={{ color: "var(--text-muted)" }}>Backstop · 6 h</span>
                      : <span style={{ color: "var(--text-muted)" }}>Fallback #{i}</span>}
                  </td>
                  <td className="py-2 pr-3 font-mono whitespace-nowrap" title={fmtDateTime(s.last_ok_at)}>{fmtRelative(s.last_ok_at)}</td>
                  <td className="py-2 pr-3 font-mono">{s.last_item_count ?? "—"}</td>
                  <td className="py-2">
                    {s.consecutive_errors > 0
                      ? <span style={{ color: s.consecutive_errors >= 3 ? "var(--tier-danger)" : "var(--warning)" }} title={s.last_error ?? ""}>{s.consecutive_errors} error{s.consecutive_errors > 1 ? "s" : ""}: {s.last_error?.slice(0, 60)}</span>
                      : <span style={{ color: "var(--success)" }}>OK</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {d.sources.length === 0 && <div className="text-xs py-2" style={{ color: "var(--text-muted)" }}>No sources found yet.</div>}
      </div>

      {d.discovery_log.length > 0 && (
        <details>
          <summary className="text-[11px] cursor-pointer" style={{ color: "var(--text-muted)" }}>Discovery log</summary>
          <pre className="text-[10px] font-mono mt-2 p-2 rounded-lg whitespace-pre-wrap" style={{ background: "var(--bg-elevated)", color: "var(--text-muted)" }}>{d.discovery_log.join("\n")}</pre>
        </details>
      )}

      <div>
        <div className="text-[10px] uppercase tracking-widest mb-1.5" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Recent runs</div>
        <div className="flex flex-col gap-1">
          {jobs.data.slice(0, 8).map(j => (
            <div key={j.id} className="flex items-center gap-3 text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>
              <span style={{ color: j.ok === false ? "var(--tier-danger)" : j.ok ? "var(--success)" : "var(--warning)" }}>●</span>
              <span className="w-16">{j.job}</span>
              <span className="w-20">{fmtRelative(j.started_at)}</span>
              <span>+{j.items_new} new · {j.items_updated} rechecks · {j.items_processed} listed</span>
              {j.error && <span className="truncate" style={{ color: "var(--tier-danger)" }} title={j.error}>{j.error}</span>}
            </div>
          ))}
          {jobs.data.length === 0 && <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>No runs yet.</span>}
        </div>
      </div>
    </div>
  );
}

function SitemapCheckPanel({ siteId }: { siteId: number }) {
  const [res, setRes] = useState<SitemapCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try { setRes(await api.sitemapCheck(siteId)); } catch (e) { setErr(e instanceof Error ? e.message : "Check failed"); } finally { setBusy(false); }
  };
  return (
    <div className="px-4 pb-4 flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button onClick={run} disabled={busy} className="filter-chip">{busy ? "Reading sitemaps… (up to a minute)" : "Check today's sitemaps"}</button>
        <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>Reads every sitemap updated on the latest date, adds anything missing and shows what's covered.</span>
      </div>
      {err && <div className="text-[11px]" style={{ color: "var(--tier-danger)" }}>{err}</div>}
      {res && (
        <div className="rounded-lg p-3 text-[11px] flex flex-col gap-2" style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)" }}>
          {res.error ? <div style={{ color: "var(--tier-danger)" }}>{res.error}</div> : (
            <>
              <div className="font-mono" style={{ color: "var(--text-muted)" }}>{res.index_url} · latest date {res.latest_day ?? "—"} · {res.added_now ?? 0} added just now</div>
              {res.children.map(c => (
                <div key={c.url} className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2 font-mono">
                    <a href={c.url} target="_blank" rel="noreferrer" className="hover:underline" style={{ color: "var(--accent-light)" }}>{c.url.split("/").pop()}</a>
                    {c.error ? <span style={{ color: "var(--tier-danger)" }}>{c.error}</span> : (
                      <span>{c.urls} URLs · {c.latest_day_urls} dated {c.day} · <b style={{ color: c.visible === c.latest_day_urls ? "var(--success)" : "var(--warning)" }}>{c.visible}/{c.latest_day_urls} in the feed</b></span>
                    )}
                  </div>
                  {c.missing.map(m => (
                    <div key={m.url} className="pl-3 font-mono truncate" style={{ color: "var(--text-muted)" }} title={m.url}>✗ {m.url.replace(/^https?:\/\/[^/]+/, "")} — {m.reason}</div>
                  ))}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function SiteRow({ site, onChanged, onShowFeed }: { site: Site; onChanged: () => void; onShowFeed: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [cohortEdit, setCohortEdit] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>, done: string) {
    setMsg(null);
    try {
      await fn();
      setMsg(done);
      onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed");
    }
  }

  return (
    <div className="rounded-xl overflow-hidden" style={{ background: "var(--bg-card)", border: "1px solid var(--border)", opacity: site.paused ? 0.65 : 1 }}>
      <div className="p-4 flex flex-wrap items-center gap-4">
        <button onClick={() => setOpen(o => !o)} className="flex items-center gap-3 min-w-0 flex-1 text-left" aria-expanded={open}>
          <SiteIcon site={site} size={28} />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{site.name}</span>
              {site.is_own_site && <span className="badge-own text-[9px] px-1.5 py-0.5 rounded-sm font-bold">OUR SITE</span>}
              {site.paused && <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>(paused)</span>}
            </div>
            <div className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>
              {site.domain}{site.fast_source ? ` · via ${SOURCE_LABEL[site.fast_source]}` : ""}
            </div>
          </div>
          <span style={{ color: "var(--text-muted)", transform: open ? "rotate(180deg)" : "none", transition: "transform .15s" }}><ChevronDown /></span>
        </button>

        <div className="flex items-center gap-5 text-center">
          <button onClick={() => onShowFeed(site.id)} className="hover:underline" title="Show this site's articles">
            <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{site.articles_24h}</div>
            <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>24 h</div>
          </button>
          <div>
            <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{site.articles_7d}</div>
            <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>7 days</div>
          </div>
          <div>
            <div className="text-sm font-bold font-mono" style={{ color: "var(--warning)" }}>{site.updates_7d}</div>
            <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>edits 7 d</div>
          </div>
          <div className="w-24 text-left">
            <HealthDot health={site.health} />
            <div className="text-[10px] font-mono mt-0.5" style={{ color: "var(--text-muted)" }} title={fmtDateTime(site.last_poll_ok_at)}>
              {site.health === "pending" ? (site.queued ? `${site.queued} queued` : site.backfill_status) : `checked ${fmtRelative(site.last_poll_ok_at)}`}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button onClick={() => act(() => api.pollSite(site.id), "Check queued — results in under a minute")} className="p-2 rounded-lg hover-surface" title="Check now" aria-label="Check now" style={{ color: "var(--text-muted)" }}><RefreshIcon size={13} /></button>
          <button onClick={() => act(() => api.updateSite(site.id, { paused: !site.paused }), site.paused ? "Resumed" : "Paused")} className="p-2 rounded-lg hover-surface" title={site.paused ? "Resume tracking" : "Pause tracking"} aria-label={site.paused ? "Resume" : "Pause"} style={{ color: "var(--text-muted)" }}>
            {site.paused ? <PlayIcon /> : <PauseIcon />}
          </button>
          <button onClick={() => { if (confirm(`Stop tracking ${site.name} and delete its ${site.articles_7d}+ stored articles?`)) act(() => api.deleteSite(site.id), "Removed"); }}
            className="p-2 rounded-lg hover-surface" title="Remove site" aria-label="Remove site" style={{ color: "var(--tier-danger)" }}><TrashIcon /></button>
        </div>
      </div>

      {(msg || site.last_error) && (
        <div className="px-4 pb-3 -mt-2 text-[11px]" style={{ color: msg ? "var(--accent-light)" : "var(--tier-danger)" }}>{msg ?? site.last_error}</div>
      )}

      {open && (
        <div style={{ borderTop: "1px solid var(--border)" }}>
          <div className="px-4 py-3 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
            <span>Cohort:</span>
            {cohortEdit === null ? (
              <button onClick={() => setCohortEdit(site.cohort ?? "")} className="filter-chip">{site.cohort ?? "none — set"}</button>
            ) : (
              <form onSubmit={e => { e.preventDefault(); act(() => api.updateSite(site.id, { cohort: cohortEdit }), "Saved"); setCohortEdit(null); }} className="flex gap-1">
                <input autoFocus value={cohortEdit} onChange={e => setCohortEdit(e.target.value)} className="select-custom text-xs w-36" list="cohort-suggestions" />
                <button className="btn-primary text-xs px-2">Save</button>
              </form>
            )}
            <span className="ml-auto" />
            <button onClick={() => act(() => api.rediscover(site.id), "Re-scanning feeds…")} className="filter-chip">Re-scan feeds</button>
            <button onClick={() => act(() => api.updateSite(site.id, { is_own_site: !site.is_own_site }), "Saved")} className="filter-chip">{site.is_own_site ? "Unmark as our site" : "Mark as our site"}</button>
          </div>
          <SitemapCheckPanel siteId={site.id} />
          <SiteRowDetail siteId={site.id} />
        </div>
      )}
    </div>
  );
}

export function SourcesView({ sites, loading, error, onRetry, onChanged, onShowFeed }: {
  sites: Site[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onChanged: () => void;
  onShowFeed: (siteId: number) => void;
}) {
  // Poll while any site is still being set up, so "Setting up…" flips to
  // healthy on its own.
  const settingUp = sites.some(s => s.health === "pending");
  useEffect(() => {
    if (!settingUp) return;
    const t = setInterval(onChanged, 8000);
    return () => clearInterval(t);
  }, [settingUp, onChanged]);

  const cohorts = Array.from(new Set(sites.map(s => s.cohort).filter(Boolean))) as string[];

  return (
    <div className="p-5 flex flex-col gap-4 max-w-5xl w-full mx-auto">
      <datalist id="cohort-suggestions">{cohorts.map(c => <option key={c} value={c} />)}</datalist>
      <AddSiteForm onAdded={onChanged} />
      <div className="flex items-center justify-between">
        <h2 className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>
          Tracked sites · {sites.length}
        </h2>
      </div>
      {error ? (
        <div className="text-sm" style={{ color: "var(--tier-danger)" }}>{error} <button onClick={onRetry} className="underline" style={{ color: "var(--accent-light)" }}>Retry</button></div>
      ) : loading && sites.length === 0 ? (
        <div className="flex flex-col gap-2">{[0, 1, 2].map(i => <div key={i} className="skeleton h-16 w-full" />)}</div>
      ) : sites.length === 0 ? (
        <div className="rounded-xl p-8 text-center text-sm" style={{ border: "1px dashed var(--border)", color: "var(--text-muted)" }}>
          No sites yet. Add your first competitor above — and techwiser.com as "our site" for the benchmark.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {sites.map(s => <SiteRow key={s.id} site={s} onChanged={onChanged} onShowFeed={onShowFeed} />)}
        </div>
      )}
    </div>
  );
}
