import { useState } from "react";
import { api, ApiError } from "../lib/api";

export function LoginScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.login(password);
      onLoggedIn();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Couldn't log in.");
      setBusy(false);
    }
  }

  return (
    <div className="h-full w-full flex items-center justify-center p-6" style={{ background: "var(--bg-base)", fontFamily: "Inter, sans-serif" }}>
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl p-6 flex flex-col gap-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2.5">
          <img src="/tw-logo.png" alt="" className="size-9" />
          <div>
            <div className="text-base font-bold leading-none" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>
              TW<span style={{ color: "var(--accent-light)" }}>-Labs</span> Web Intel
            </div>
            <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Team login</div>
          </div>
        </div>
        <label className="flex flex-col gap-1.5">
          <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Password</span>
          <input type="password" autoFocus autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} className="select-custom text-sm" />
        </label>
        {err && <div className="text-xs" style={{ color: "var(--tier-danger)" }}>{err}</div>}
        <button type="submit" disabled={busy || !password} className="btn-primary text-sm py-2">{busy ? "Checking…" : "Log in"}</button>
      </form>
    </div>
  );
}
