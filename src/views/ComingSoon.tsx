const COPY: Record<string, { phase: string; lines: string[] }> = {
  "Topic Radar": {
    phase: "Phase 4 · weeks 7–8",
    lines: [
      "Stories covered by 3 or more competitors in the last 24 h, ranked by how fast they spread.",
      "A Gap flag when techwiser.com hasn't covered a story yet.",
      "Alert rules for Slack / Telegram and a 9:30 AM daily digest.",
    ],
  },
  "Site Analytics": {
    phase: "Phase 2 · weeks 4–5",
    lines: [
      "One card per site: Similarweb rank, Tranco, Cloudflare Radar, Open PageRank and Core Web Vitals.",
      "Publishing pace (articles/day), content-type mix, update rate and top authors — already being collected.",
      "Article traction signals: CrUX presence, Reddit / Hacker News mentions, Google ranking for shortlisted stories.",
    ],
  },
  YouTube: {
    phase: "Phase 3 · week 6",
    lines: [
      "The TW-Labs YouTube tracker, ported: overperformance, velocity checkpoints, SponsorBlock.",
      "Community posts via Apify.",
      "Channels linked to their websites, and YouTube embeds in articles matched to tracked channels.",
    ],
  },
};

export function ComingSoon({ section }: { section: string }) {
  const c = COPY[section];
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="max-w-md rounded-xl p-6 flex flex-col gap-3" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
        <span className="badge-type text-[10px] px-2 py-0.5 rounded-sm font-bold self-start">{c?.phase.toUpperCase()}</span>
        <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{section} is next on the roadmap</h2>
        <ul className="flex flex-col gap-2 text-sm list-disc pl-4" style={{ color: "var(--text-secondary)" }}>
          {c?.lines.map(l => <li key={l}>{l}</li>)}
        </ul>
      </div>
    </div>
  );
}
