import { useState } from "react";
import { api, ApiError, type AlertRule, type AlertRuleInput, type Channel, type Integrations, type Site } from "../lib/api";
import { CONTENT_TYPE_LABEL, fmtRelative } from "../lib/format";
import { useAsync } from "../hooks/useAsync";
import { BellIcon, PenIcon, PlusIcon, RefreshIcon, SendIcon, TrashIcon, XIcon } from "../components/icons";

function Pill({ on, label, hint }: { on: boolean; label: string; hint: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg p-2.5" style={{ background: "var(--bg-elevated)" }}>
      <span className="size-2 rounded-full mt-1.5 shrink-0" style={{ background: on ? "var(--success)" : "var(--text-muted)" }} />
      <div className="min-w-0">
        <div className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>{label} <span className="font-normal" style={{ color: on ? "var(--success)" : "var(--text-muted)" }}>· {on ? "connected" : "not set"}</span></div>
        <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{hint}</div>
      </div>
    </div>
  );
}

const EMPTY: AlertRuleInput = { name: "", kind: "article", keywords: [], site_ids: [], channel_ids: [], content_types: [], include_updates: false, min_ratio: null, destinations: ["slack"], enabled: true };

function toInput(r: AlertRule): AlertRuleInput {
  return { name: r.name, kind: r.kind, keywords: r.keywords ?? [], site_ids: r.site_ids ?? [], channel_ids: r.channel_ids ?? [], content_types: r.content_types ?? [],
    include_updates: r.include_updates, min_ratio: r.min_ratio, destinations: r.destinations, enabled: r.enabled };
}

function Multi<T extends string | number>({ options, value, onChange, empty }: { options: { v: T; label: string }[]; value: T[]; onChange: (v: T[]) => void; empty: string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      <button type="button" onClick={() => onChange([])} className={`filter-chip ${value.length === 0 ? "active" : ""}`}>{empty}</button>
      {options.map(o => (
        <button type="button" key={String(o.v)} onClick={() => onChange(value.includes(o.v) ? value.filter(x => x !== o.v) : [...value, o.v])}
          className={`filter-chip ${value.includes(o.v) ? "active" : ""}`}>{o.label}</button>
      ))}
    </div>
  );
}

function RuleForm({ initial, sites, channels, onSave, onCancel }: { initial: AlertRuleInput; sites: Site[]; channels: Channel[]; onSave: (r: AlertRuleInput) => Promise<void>; onCancel: () => void }) {
  const [r, setR] = useState<AlertRuleInput>(initial);
  const [kw, setKw] = useState(initial.keywords.join(", "));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await onSave({ ...r, keywords: kw.split(",").map(s => s.trim()).filter(Boolean) });
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : "Couldn't save");
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="panel p-4 flex flex-col gap-3">
      <div className="flex flex-wrap gap-3 items-end">
        <label className="flex flex-col gap-1 flex-1 min-w-[200px]">
          <span className="label-caps">Rule name</span>
          <input value={r.name} onChange={e => setR({ ...r, name: e.target.value })} required placeholder="e.g. Pixel launches" className="select-custom text-sm" />
        </label>
        <div className="flex flex-col gap-1">
          <span className="label-caps">Watch</span>
          <div className="seg">
            <button type="button" aria-pressed={r.kind === "article"} onClick={() => setR({ ...r, kind: "article" })}>Articles</button>
            <button type="button" aria-pressed={r.kind === "video"} onClick={() => setR({ ...r, kind: "video" })}>YouTube videos</button>
          </div>
        </div>
      </div>
      <label className="flex flex-col gap-1">
        <span className="label-caps">Keywords (comma-separated, any match · empty = everything)</span>
        <input value={kw} onChange={e => setKw(e.target.value)} placeholder="pixel 11, galaxy s27, one ui 9" className="select-custom text-sm" />
      </label>
      {r.kind === "article" ? (
        <>
          <div className="flex flex-col gap-1.5"><span className="label-caps">Sites</span>
            <Multi options={sites.map(s => ({ v: s.id, label: s.name }))} value={r.site_ids} onChange={v => setR({ ...r, site_ids: v })} empty="All sites" /></div>
          <div className="flex flex-col gap-1.5"><span className="label-caps">Content types</span>
            <Multi options={Object.entries(CONTENT_TYPE_LABEL).map(([v, label]) => ({ v, label }))} value={r.content_types} onChange={v => setR({ ...r, content_types: v })} empty="Any type" /></div>
          <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
            <input type="checkbox" checked={r.include_updates} onChange={e => setR({ ...r, include_updates: e.target.checked })} className="accent-indigo-400" />
            Also alert when a matching article is updated
          </label>
        </>
      ) : (
        <>
          <div className="flex flex-col gap-1.5"><span className="label-caps">Channels</span>
            <Multi options={channels.map(c => ({ v: c.id, label: c.name }))} value={r.channel_ids} onChange={v => setR({ ...r, channel_ids: v })} empty="All channels" /></div>
          <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
            Only when a video reaches
            <select value={r.min_ratio ?? ""} onChange={e => setR({ ...r, min_ratio: e.target.value ? Number(e.target.value) : null })} className="select-custom text-xs">
              <option value="">any ratio</option>
              {[1.5, 2, 3, 5].map(x => <option key={x} value={x}>{x}x</option>)}
            </select>
            its channel median
          </label>
        </>
      )}
      <div className="flex flex-col gap-1.5"><span className="label-caps">Send to</span>
        <Multi options={[{ v: "slack" as const, label: "Slack" }, { v: "telegram" as const, label: "Telegram" }]} value={r.destinations} onChange={v => setR({ ...r, destinations: v.length ? v : r.destinations })} empty="—" /></div>
      {err && <div className="text-xs" style={{ color: "var(--tier-danger)" }}>{err}</div>}
      <div className="flex items-center gap-2">
        <button type="submit" disabled={busy || !r.name.trim()} className="btn-primary text-sm px-4 py-2">{busy ? "Saving…" : "Save rule"}</button>
        <button type="button" onClick={onCancel} className="filter-chip" style={{ padding: "8px 14px" }}>Cancel</button>
        <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>Existing matches are skipped; only new items from now on are sent.</span>
      </div>
    </form>
  );
}

function describe(r: AlertRule, sites: Site[], channels: Channel[]): string {
  const parts: string[] = [];
  parts.push(r.keywords?.length ? `“${r.keywords.join("”, “")}”` : r.kind === "article" ? "every article" : "every video");
  if (r.kind === "article") {
    if (r.site_ids?.length) parts.push(`on ${r.site_ids.map(id => sites.find(s => s.id === id)?.name ?? `#${id}`).join(", ")}`);
    if (r.content_types?.length) parts.push(`(${r.content_types.map(t => CONTENT_TYPE_LABEL[t] ?? t).join(", ")})`);
    if (r.include_updates) parts.push("+ updates");
  } else {
    if (r.channel_ids?.length) parts.push(`on ${r.channel_ids.map(id => channels.find(c => c.id === id)?.name ?? `#${id}`).join(", ")}`);
    if (r.min_ratio) parts.push(`at ${r.min_ratio}x+`);
  }
  return parts.join(" ");
}

export function AlertsView({ sites }: { sites: Site[] }) {
  const integ = useAsync<Integrations | null>(() => api.integrations(), [], null);
  const rules = useAsync<AlertRule[]>(() => api.rules(), [], []);
  const channels = useAsync<Channel[]>(() => api.channels(), [], []);
  const [editing, setEditing] = useState<AlertRule | "new" | null>(null);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [digest, setDigest] = useState<{ title: string; lines: string[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const i = integ.data;

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    setMsg(null);
    try { await fn(); setMsg({ text: ok, ok: true }); } catch (x) { setMsg({ text: x instanceof ApiError ? x.message : "Failed", ok: false }); } finally { setBusy(null); }
  };
  const save = async (r: AlertRuleInput) => {
    if (editing === "new") await api.addRule(r);
    else if (editing) await api.updateRule(editing.id, r);
    setEditing(null);
    rules.reload();
  };
  const toggle = (r: AlertRule) => run(`t${r.id}`, async () => { await api.updateRule(r.id, { ...toInput(r), enabled: !r.enabled }); rules.reload(); }, r.enabled ? "Rule paused" : "Rule on");
  const del = (r: AlertRule) => { if (window.confirm(`Delete "${r.name}"?`)) run(`d${r.id}`, async () => { await api.deleteRule(r.id); rules.reload(); }, "Rule deleted"); };
  const noDest = i != null && !i.slack && !i.telegram;

  return (
    <div className="flex-1 min-w-0 overflow-y-auto">
      <div className="p-5 grid gap-5 max-w-6xl" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))" }}>
        {/* Rules */}
        <section className="flex flex-col gap-3" style={{ gridColumn: "1 / -1" }}>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold flex items-center gap-2" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}><BellIcon size={14} />Alert rules</h2>
            <span className="flex-1" />
            {msg && <span className="text-[11px] px-2 py-1 rounded-md" style={{ color: msg.ok ? "var(--accent-light)" : "var(--tier-danger)", border: `1px solid ${msg.ok ? "var(--accent)" : "var(--tier-danger)"}` }}>{msg.text}</span>}
            {editing == null && <button onClick={() => setEditing("new")} className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1"><PlusIcon />New rule</button>}
          </div>
          {noDest && <div className="panel p-3 text-xs" style={{ color: "var(--warning)" }}>No destination is connected yet, so rules can be saved but nothing is sent. Add a Slack webhook or a Telegram bot on Render (see the right-hand panel).</div>}
          {editing != null && (
            <RuleForm key={editing === "new" ? "new" : editing.id} initial={editing === "new" ? EMPTY : toInput(editing)} sites={sites} channels={channels.data} onSave={save} onCancel={() => setEditing(null)} />
          )}
          {rules.loading && rules.data.length === 0 ? <div className="skeleton h-16" /> : rules.data.length === 0 && editing == null ? (
            <div className="panel p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>
              No rules yet. A rule sends a Slack or Telegram message when a competitor publishes on a topic, or a tracked video takes off.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {rules.data.map(r => (
                <div key={r.id} className="video-card p-3 flex flex-wrap items-center gap-3" style={{ opacity: r.enabled ? 1 : 0.6 }}>
                  <span className="badge-type text-[9px] px-1.5 py-0.5 rounded uppercase">{r.kind === "article" ? "Articles" : "YouTube"}</span>
                  <div className="flex-1 min-w-[200px]">
                    <div className="text-sm font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{r.name}</div>
                    <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{describe(r, sites, channels.data)} → {r.destinations.join(" + ")}</div>
                  </div>
                  <span className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>{r.fire_count} sent{r.last_fired_at ? ` · last ${fmtRelative(r.last_fired_at)}` : ""}</span>
                  <button onClick={() => toggle(r)} disabled={busy === `t${r.id}`} className={`filter-chip ${r.enabled ? "active" : ""}`}>{r.enabled ? "On" : "Paused"}</button>
                  <button onClick={() => setEditing(r)} className="p-1.5 rounded-md hover-surface" style={{ color: "var(--text-muted)" }} aria-label={`Edit ${r.name}`}><PenIcon size={12} /></button>
                  <button onClick={() => del(r)} className="p-1.5 rounded-md hover-surface" style={{ color: "var(--text-muted)" }} aria-label={`Delete ${r.name}`}><TrashIcon /></button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Integrations */}
        <section className="panel p-4 flex flex-col gap-3">
          <h2 className="label-caps">Connections</h2>
          {integ.loading && !i ? <div className="skeleton h-40" /> : i && (
            <>
              <Pill on={i.slack} label="Slack" hint="SLACK_WEBHOOK_URL — an incoming webhook for your team channel" />
              <Pill on={i.telegram} label="Telegram" hint="TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID" />
              <Pill on={i.youtube} label="YouTube Data API" hint="YOUTUBE_API_KEY — videos, baselines, velocity" />
              <Pill on={i.apify} label="Apify" hint="APIFY_API_TOKEN — community posts" />
              <Pill on={i.search_console || i.ga4} label="Search Console / GA4" hint="GOOGLE_SERVICE_ACCOUNT_JSON + GSC_SITE_URL / GA4_PROPERTY_ID" />
              <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>Set these in Render → webintel-api → Environment. The service restarts by itself and picks them up.</div>
              <div className="flex flex-wrap gap-2">
                <button disabled={!i.slack || busy === "slack"} onClick={() => run("slack", () => api.testAlert("slack"), "Test sent to Slack")} className="filter-chip disabled:opacity-40"><SendIcon size={11} />Test Slack</button>
                <button disabled={!i.telegram || busy === "tg"} onClick={() => run("tg", () => api.testAlert("telegram"), "Test sent to Telegram")} className="filter-chip disabled:opacity-40"><SendIcon size={11} />Test Telegram</button>
              </div>
            </>
          )}
        </section>

        {/* Digest */}
        <section className="panel p-4 flex flex-col gap-3">
          <h2 className="label-caps">Daily digest</h2>
          {i && (
            <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {i.digest_enabled ? <>Sent every day at <b className="font-mono">{i.digest_time_ist} IST</b> to every connected destination.</> : "The daily digest is switched off (DIGEST_ENABLED=false)."}
              <div className="text-[11px] mt-1" style={{ color: "var(--text-muted)" }}>Last sent: {i.digest_last_sent ? fmtRelative(i.digest_last_sent) : "never"}</div>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => run("prev", async () => setDigest(await api.digestPreview()), "Preview ready")} disabled={busy === "prev"} className="filter-chip">Preview</button>
            <button onClick={() => run("send", async () => { await api.digestSend(); integ.reload(); }, "Digest sent")} disabled={busy === "send" || noDest} className="filter-chip disabled:opacity-40"><SendIcon size={11} />Send now</button>
          </div>
          {digest && (
            <div className="rounded-lg p-3 text-xs flex flex-col gap-1 relative" style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)" }}>
              <button onClick={() => setDigest(null)} className="absolute top-2 right-2 p-1" style={{ color: "var(--text-muted)" }} aria-label="Close preview"><XIcon /></button>
              <div className="font-semibold pr-6" style={{ color: "var(--text-primary)" }}>{digest.title}</div>
              {digest.lines.length === 0 ? <div style={{ color: "var(--text-muted)" }}>Nothing to report yet.</div> : digest.lines.map((l, k) => <div key={k} className="whitespace-pre-wrap">{l}</div>)}
            </div>
          )}
        </section>

        {/* Benchmark */}
        <section className="panel p-4 flex flex-col gap-3">
          <h2 className="label-caps">TechWiser benchmark (optional)</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Pulls 28-day clicks, impressions and position from Search Console and views from GA4 for techwiser.com articles, and shows them in each article's drawer. Runs daily at 06:15 IST.
          </p>
          {i?.benchmark_last_sync && (
            <div className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>
              Last sync {fmtRelative(i.benchmark_last_sync.at)} · {i.benchmark_last_sync.matched} articles matched · {i.benchmark_last_sync.gsc_pages} GSC / {i.benchmark_last_sync.ga4_pages} GA4 pages
            </div>
          )}
          <button disabled={!i || (!i.search_console && !i.ga4) || busy === "bench"} onClick={() => run("bench", async () => { const r = await api.benchmarkSync(); integ.reload(); if (r.skipped) throw new ApiError(422, r.skipped); }, "Benchmark synced")}
            className="filter-chip self-start disabled:opacity-40"><RefreshIcon size={11} />Sync now</button>
        </section>
      </div>
    </div>
  );
}
