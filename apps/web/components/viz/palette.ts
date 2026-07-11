/* One severity/threat palette, shared by every view.
 *
 * The same amber->rose ramp colours a hotspot, a high-PageRank graph node, and a
 * large money flow. That is what makes the console read as one instrument instead
 * of four charts that happen to sit on the same page — a "high" looks like a high
 * everywhere. */
export const SEV = {
  low: "#5fd3a6",
  med: "#f5c26b",
  high: "#f6799a",
} as const;

export const ACCENT = "#7cc4ff";
export const GRID = "rgba(148,178,255,0.10)";
export const TEXT_DIM = "#93a0c2";

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
  textStyle: { color: TEXT_DIM, fontFamily: "ui-sans-serif, Inter, system-ui" },
  tooltip: {
    backgroundColor: "rgba(16,22,38,0.94)",
    borderColor: "rgba(148,178,255,0.22)",
    textStyle: { color: "#e8edfb", fontSize: 12 },
    extraCssText: "backdrop-filter: blur(10px); border-radius: 10px;",
  },
} as const;
