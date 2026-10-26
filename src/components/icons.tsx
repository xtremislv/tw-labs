// Small stroke icons (Lucide-style geometry, drawn inline so there's no icon
// dependency). All take `size` and inherit `currentColor`.
type P = { size?: number };
const base = (size: number) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true });

export const FeedIcon = ({ size = 15 }: P) => <svg {...base(size)}><path d="M4 11a9 9 0 0 1 9 9" /><path d="M4 4a16 16 0 0 1 16 16" /><circle cx="5" cy="19" r="1" /></svg>;
export const RadarIcon = ({ size = 15 }: P) => <svg {...base(size)}><path d="M19.07 4.93A10 10 0 1 0 22 12" /><path d="M16.24 7.76A6 6 0 1 0 18 12" /><path d="M12 12 19 5" /><circle cx="12" cy="12" r="1.5" /></svg>;
export const ChartIcon = ({ size = 15 }: P) => <svg {...base(size)}><path d="M3 3v18h18" /><path d="M7 15v2" /><path d="M11 11v6" /><path d="M15 7v10" /><path d="M19 12v5" /></svg>;
export const YTIcon = ({ size = 15 }: P) => <svg {...base(size)}><rect x="2" y="5" width="20" height="14" rx="4" /><path d="m10 9 5 3-5 3z" /></svg>;
export const BookmarkIcon = ({ size = 15 }: P) => <svg {...base(size)}><path d="M19 21 12 16 5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></svg>;
export const GlobeIcon = ({ size = 15 }: P) => <svg {...base(size)}><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20" /></svg>;
export const BellIcon = ({ size = 15 }: P) => <svg {...base(size)}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>;
export const MenuIcon = ({ size = 15 }: P) => <svg {...base(size)}><path d="M4 6h16M4 12h16M4 18h16" /></svg>;
export const HomeIcon = ({ size = 15 }: P) => <svg {...base(size)}><path d="m3 10 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M9 22V12h6v10" /></svg>;
export const RefreshIcon = ({ size = 14 }: P) => <svg {...base(size)}><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5" /></svg>;
export const SunIcon = ({ size = 13 }: P) => <svg {...base(size)}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>;
export const MoonIcon = ({ size = 13 }: P) => <svg {...base(size)}><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9" /></svg>;
export const GridIcon = ({ size = 14 }: P) => <svg {...base(size)}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>;
export const ListIcon = ({ size = 14 }: P) => <svg {...base(size)}><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg>;
export const ChevronDown = ({ size = 12 }: P) => <svg {...base(size)}><path d="m6 9 6 6 6-6" /></svg>;
export const XIcon = ({ size = 10 }: P) => <svg {...base(size)} strokeWidth={2.5}><path d="M18 6 6 18M6 6l12 12" /></svg>;
export const SearchIcon = ({ size = 13 }: P) => <svg {...base(size)}><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>;
export const ExternalIcon = ({ size = 12 }: P) => <svg {...base(size)}><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>;
export const DownloadIcon = ({ size = 13 }: P) => <svg {...base(size)}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5" /><path d="M12 15V3" /></svg>;
export const PlusIcon = ({ size = 12 }: P) => <svg {...base(size)}><path d="M12 5v14M5 12h14" /></svg>;
export const TrashIcon = ({ size = 12 }: P) => <svg {...base(size)}><path d="M3 6h18" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>;
export const PauseIcon = ({ size = 12 }: P) => <svg {...base(size)}><rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" /></svg>;
export const PlayIcon = ({ size = 12 }: P) => <svg {...base(size)}><path d="m6 3 14 9-14 9z" /></svg>;
export const ClockIcon = ({ size = 11 }: P) => <svg {...base(size)}><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>;
export const PenIcon = ({ size = 11 }: P) => <svg {...base(size)}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>;
export const WordsIcon = ({ size = 11 }: P) => <svg {...base(size)}><path d="M4 6h16M4 12h16M4 18h10" /></svg>;
export const StarIcon = ({ size = 12, filled = false }: P & { filled?: boolean }) => <svg {...base(size)} fill={filled ? "currentColor" : "none"}><path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8-6.2-3.2L5.8 21 7 14.2 2 9.3l6.9-1z" /></svg>;
export const LinkIcon = ({ size = 12 }: P) => <svg {...base(size)}><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7" /><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7" /></svg>;
