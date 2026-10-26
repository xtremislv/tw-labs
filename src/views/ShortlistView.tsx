import { useState } from "react";
import { api, ApiError, type ShortStatus, type ShortlistItem } from "../lib/api";
import { fmtRelative } from "../lib/format";
import { load, save } from "../lib/storage";
import { useAsync } from "../hooks/useAsync";
import { ExternalIcon, PlusIcon, TrashIcon } from "../components/icons";

const COLUMNS: { status: ShortStatus; label: string; color: string }[] = [
  { status: "idea", label: "Ideas", color: "var(--accent-light)" },
  { status: "assigned", label: "Assigned", color: "var(--tier-blue)" },
  { status: "in_progress", label: "In progress", color: "var(--warning)" },
  { status: "published", label: "Published", color: "var(--success)" },
  { status: "dropped", label: "Dropped", color: "var(--text-muted)" },
];
const KIND_LABEL: Record<ShortlistItem["kind"], string> = { article: "Article", story: "Story", video: "Video", post: "Post", idea: "Idea" };

function Card({ item, onChange, onDelete }: { item: ShortlistItem; onChange: (b: Partial<ShortlistItem>) => void; onDelete: () => void }) {
  const [notes, setNotes] = useState(item.notes ?? "");
  const [owner, setOwner] = useState(item.owner ?? "");
  return (
    <div className="video-card p-3 flex flex-col gap-2" draggable onDragStart={e => e.dataTransfer.setData("text/plain", String(item.id))}>
      <div className="flex items-start gap-2">
        <span className="badge-type text-[9px] px-1.5 py-0.5 rounded uppercase shrink-0">{KIND_LABEL[item.kind]}</span>
        <span className="flex-1" />
        {item.url && <a href={item.url} target="_blank" rel="noreferrer" className="p-1 rounded hover-surface" style={{ color: "var(--text-muted)" }} aria-label="Open source"><ExternalIcon size={11} /></a>}
        <button onClick={onDelete} className="p-1 rounded hover-surface" style={{ color: "var(--text-muted)" }} aria-label="Remove"><TrashIcon size={11} /></button>
      </div>
      <div className="text-sm font-semibold leading-snug line-clamp-3" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{item.title}</div>
      {item.source && <div className="text-[10px] font-mono truncate" style={{ color: "var(--text-muted)" }}>{item.source} · added {fmtRelative(item.created_at)}</div>}
      <div className="flex items-center gap-2">
        <input value={owner} onChange={e => setOwner(e.target.value)} onBlur={() => { if (owner !== (item.owner ?? "")) onChange({ owner }); }}
          placeholder="Owner" className="select-custom text-xs flex-1 min-w-0" style={{ padding: "4px 8px" }} aria-label="Owner" />
        <select value={item.status} onChange={e => onChange({ status: e.target.value as ShortStatus })} className="select-custom text-xs" style={{ padding: "4px 24px 4px 8px" }} aria-label="Status">
          {COLUMNS.map(c => <option key={c.status} value={c.status}>{c.label}</option>)}
        </select>
      </div>
      <textarea value={notes} onChange={e => setNotes(e.target.value)} onBlur={() => { if (notes !== (item.notes ?? "")) onChange({ notes }); }}
        placeholder="Angle, notes…" rows={2} className="select-custom text-xs resize-y" style={{ padding: "6px 8px", cursor: "text" }} aria-label="Notes" />
    </div>
  );
}

export function ShortlistView() {
  const { data, setData, loading, error, reload } = useAsync<ShortlistItem[]>(() => api.shortlist(), [], []);
  const [title, setTitle] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [showDropped, setShowDropped] = useState(() => load("webintel.shortlist.dropped", false));
  const [over, setOver] = useState<ShortStatus | null>(null);

  const update = async (item: ShortlistItem, body: Partial<ShortlistItem>) => {
    setData(d => d.map(x => (x.id === item.id ? { ...x, ...body } : x)));
    try {
      const n = await api.updateShortlist(item.id, body);
      setData(d => d.map(x => (x.id === n.id ? n : x)));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Update failed");
      reload();
    }
  };
  const remove = async (item: ShortlistItem) => {
    setData(d => d.filter(x => x.id !== item.id));
    try { await api.deleteShortlist(item.id); } catch { reload(); }
  };
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      const n = await api.addShortlist({ kind: "idea", title: title.trim() });
      setData(d => [n, ...d.filter(x => x.id !== n.id)]);
      setTitle("");
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : "Couldn't add");
    }
  };
  const cols = COLUMNS.filter(c => showDropped || c.status !== "dropped");

  return (
    <div className="flex-1 min-w-0 overflow-y-auto">
      <div className="sticky top-0 z-30 px-5 py-3 flex flex-wrap items-center gap-2" style={{ background: "var(--surface-translucent)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--border)" }}>
        <form onSubmit={add} className="flex items-center gap-2 flex-1 min-w-[240px] max-w-xl">
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Add your own idea…" title="Stories, videos and articles are added with their ☆ button" className="select-custom text-xs flex-1" />
          <button type="submit" disabled={!title.trim()} className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1"><PlusIcon />Add</button>
        </form>
        <span className="flex-1" />
        <button onClick={() => { setShowDropped(!showDropped); save("webintel.shortlist.dropped", !showDropped); }} className={`filter-chip ${showDropped ? "active" : ""}`}>Show dropped</button>
        <span className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>{data.length} items</span>
      </div>
      {(error || err) && <div className="px-5 pt-3 text-xs" style={{ color: "var(--tier-danger)" }}>{error || err}</div>}
      {loading && data.length === 0 ? (
        <div className="p-5 grid gap-4 grid-cols-4">{Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-40" />)}</div>
      ) : (
        <div className="p-5 grid gap-4 items-start" style={{ gridTemplateColumns: `repeat(${cols.length}, minmax(240px, 1fr))`, overflowX: "auto" }}>
          {cols.map(c => {
            const items = data.filter(x => x.status === c.status);
            return (
              <div key={c.status} className="flex flex-col gap-2 rounded-xl p-2 min-h-40 transition-colors"
                style={{ background: over === c.status ? "var(--accent-dim)" : "var(--bg-panel)", border: "1px solid var(--border)" }}
                onDragOver={e => { e.preventDefault(); setOver(c.status); }} onDragLeave={() => setOver(null)}
                onDrop={e => { e.preventDefault(); setOver(null); const it = data.find(x => x.id === Number(e.dataTransfer.getData("text/plain"))); if (it && it.status !== c.status) update(it, { status: c.status }); }}>
                <div className="flex items-center gap-2 px-1 py-1">
                  <span className="size-2 rounded-full" style={{ background: c.color }} />
                  <span className="label-caps flex-1">{c.label}</span>
                  <span className="text-[11px] font-mono" style={{ color: "var(--text-muted)" }}>{items.length}</span>
                </div>
                {items.map(it => <Card key={`${it.id}-${it.updated_at}`} item={it} onChange={b => update(it, b)} onDelete={() => remove(it)} />)}
                {items.length === 0 && <div className="text-[11px] text-center py-4" style={{ color: "var(--text-muted)" }}>Drop cards here</div>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
