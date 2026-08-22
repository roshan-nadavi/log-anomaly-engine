import type { Config } from "tailwindcss";
import { colors } from "./lib/colors";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: colors.bg,
        panel: colors.panel,
        surface2: colors.surface2,
        edge: colors.edge,
        "edge-strong": colors.edgeStrong,
        selected: colors.selected,
        accent: colors.accent,
        muted: colors.muted,
        axis: colors.axis,
        status: colors.status,
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
