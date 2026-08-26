/* One severity/threat palette, shared by every view.
 *
 * The same amber->rose ramp colours a hotspot, a high-PageRank graph node, and a
 * large money flow. That is what makes the console read as one instrument instead
 * of four charts that happen to sit on the same page — a "high" looks like a high
 * everywhere. */
export const SEV = {
  low: "#35c08a",
  med: "#ee8b4b",
  high: "#f2555a",
} as const;

export const ACCENT = "#d8a657";
export const GRID = "rgba(255,255,255,0.07)";
export const TEXT_DIM = "#9fb1be";
export const TEXT_FAINT = "#63757f";

/** Map a 0-1 intensity onto the shared ramp. */
export function ramp(t: number): string {
  const x = Math.max(0, Math.min(1, t));
  if (x < 0.5) return mix(SEV.low, SEV.med, x / 0.5);
  return mix(SEV.med, SEV.high, (x - 0.5) / 0.5);
}

function mix(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function rgba(hex: string, alpha: number): string {
  const p = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgba(${p[0]},${p[1]},${p[2]},${alpha})`;
}

export const CHART_BASE = {
  backgroundColor: "transparent",
  textStyle: {
    color: TEXT_DIM,
    fontFamily: "var(--font-sans), ui-sans-serif, system-ui",
  },
  tooltip: {
    backgroundColor: "rgba(12,19,25,0.95)",
    borderColor: "rgba(255,255,255,0.14)",
    textStyle: { color: "#e9eff4", fontSize: 12 },
    extraCssText: "backdrop-filter: blur(10px); border-radius: 10px;",
  },
} as const;
