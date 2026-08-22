// Single source of truth for the dashboard palette. Tailwind classes
// (bg-panel, text-status-danger, ...) come from this via tailwind.config.ts;
// components that can't use Tailwind classes (Recharts props, raw SVG
// fill/stroke) import `colors` directly instead of hardcoding hex.
//
// Elevation model, not just border-vs-background: `bg` (page) < `panel`
// (raised card) < `surface2` (nested/overlay content) is a monotonic
// lightness ramp, so depth reads from tonal steps rather than borders
// alone. None of the surfaces go below ~10% lightness — near-black bases
// are what make a dark UI read as an unstyled default rather than a
// designed one.
export const colors = {
  bg: "#18181b",
  panel: "#1f1f23",
  surface2: "#28282e",
  edge: "#312f36",
  edgeStrong: "#48454e",
  selected: "#1c2e2b",
  text: "#eaeaec",
  accent: "#3fcdbf",
  muted: "#96969a",
  axis: "#7a7a80",
  status: {
    ok: "#4cb782",
    info: "#8b8fd6",
    warn: "#d9a441",
    high: "#d97b45",
    danger: "#d9555a",
  },
} as const;
