import React from "react";

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean }> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: unknown) {
    console.error("Unhandled error in the dashboard UI:", error);
  }
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "0.75rem", padding: "2rem", textAlign: "center", background: "var(--bg-base, #0f131c)", color: "var(--text-primary, #dfe2ef)" }}>
        <div style={{ fontSize: "1.05rem", fontWeight: 600, fontFamily: "Lora, serif" }}>Something went wrong</div>
        <div style={{ fontSize: "0.875rem", color: "var(--text-muted, #908fa0)", maxWidth: "28rem" }}>
          The dashboard hit an unexpected error. Reloading the page usually fixes this.
        </div>
        <button onClick={() => window.location.reload()} style={{ marginTop: "0.5rem", padding: "0.5rem 1.25rem", borderRadius: "0.5rem", border: "1px solid var(--border)", background: "var(--accent-dim)", color: "var(--accent-light)", fontSize: "0.875rem", fontWeight: 600, cursor: "pointer" }}>
          Reload page
        </button>
      </div>
    );
  }
}
