import { useState } from "react";

/** A site's favicon, falling back to its initial in a tinted square. */
export function SiteIcon({ site, size = 16 }: { site: { name: string; icon_url?: string | null; site_icon_url?: string | null }; size?: number }) {
  const [failed, setFailed] = useState(false);
  const url = site.icon_url ?? site.site_icon_url ?? null;
  if (url && !failed) {
    return <img src={url} alt="" width={size} height={size} className="rounded-sm shrink-0 object-contain" style={{ width: size, height: size }} onError={() => setFailed(true)} loading="lazy" />;
  }
  return (
    <span className="rounded-sm shrink-0 flex items-center justify-center font-bold" aria-hidden
      style={{ width: size, height: size, fontSize: size * 0.6, background: "var(--accent-dim)", color: "var(--accent-light)", fontFamily: "Lora, serif" }}>
      {site.name.slice(0, 1).toUpperCase()}
    </span>
  );
}
