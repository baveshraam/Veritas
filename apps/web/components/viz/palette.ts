/* Visualization colour, derived from the same tokens as the rest of the console
 * (globals.css). Charts are part of the product, not four libraries that happen
 * to share a page, so nothing here invents a hue.
 *
 * TWO SCALES, AND THEY MEAN DIFFERENT THINGS.
 *
 *   SEVERITY  green -> amber -> red. Used ONLY where the quantity really is
 *             "how bad": hotspot density, transfer magnitude in a laundering
 *             trail. A high looks like a high everywhere it appears.
 *
 *   INFLUENCE steel -> blue. Used for graph centrality.
 *
 * They were the same scale, and that was a category error with a visible cost:
 * every associate in a co-offending network rendered somewhere on the red end,
 * so a graph of twenty ordinary co-accused looked like twenty dangerous people.
 * PageRank measures how connected somebody is inside the network on screen. It
 * is not a threat score, the platform does not compute one for these nodes, and
 * colouring it in crimson asserted one anyway. */

export const SEV = {
  low: "#3f9d6d",
  med: "#d4883c",
  high: "#dc5b5f",
} as const;

export const ACCENT = "#c9a44c";     // identity + selection. Never a severity.
export const PRIMARY = "#4084d8";    // neutral analytical
export const VIOLET = "#8b82d8";     // model output

// A located case reads as ink on paper — cartographic navy against the light
// basemap, outside the warm severity ramp a hotspot is drawn in, and outside
// gold, which is reserved for the selected mark.
export const MAP_POINT = "#1e4a78";

export const GRID = "rgba(255,255,255,0.055)";
export const TEXT_DIM = "#9aabbd";
export const TEXT_FAINT = "#64768a";
export const SURFACE = "#151c25";

/** Map a 0-1 intensity onto the SEVERITY ramp. Only for quantities that mean
 *  "how bad". */
export function ramp(t: number): string {
  const x = clamp(t);
  return x < 0.5 ? mix(SEV.low, SEV.med, x / 0.5) : mix(SEV.med, SEV.high, (x - 0.5) / 0.5);
}

/** Map a 0-1 centrality onto the INFLUENCE ramp: quiet steel for a peripheral
 *  node, saturated blue for a hub. Reads as "more connected", not "more
 *  dangerous", which is the only claim the data supports. */
export function influence(t: number): string {
  return mix("#5b7288", PRIMARY, clamp(t));
}

function clamp(t: number): number {
  return Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
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
    backgroundColor: SURFACE,
    borderColor: "#2a3746",
    borderWidth: 1,
    padding: [8, 11],
    textStyle: { color: "#e8eef5", fontSize: 12 },
    extraCssText: "border-radius: 6px; box-shadow: 0 12px 30px rgba(0,0,0,0.45);",
  },
} as const;
