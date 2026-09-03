/* Visualization colour, derived from the same tokens as the rest of the console
 * (globals.css). Charts are part of the product, not four libraries that happen
 * to share a page, so nothing here invents a hue — every value is read back off
 * the live stylesheet, which is also what makes the charts follow the theme
 * without a second palette to keep in sync.
 *
 * TWO SCALES, AND THEY MEAN DIFFERENT THINGS.
 *
 *   SEVERITY  green -> amber -> red. Used ONLY where the quantity really is
 *             "how bad": hotspot density, transfer magnitude in a laundering
 *             trail. A high looks like a high everywhere it appears.
 *
 *   INFLUENCE quiet slate -> blue. Used for graph centrality.
 *
 * They were the same scale, and that was a category error with a visible cost:
 * every associate in a co-offending network rendered somewhere on the red end,
 * so a graph of twenty ordinary co-accused looked like twenty dangerous people.
 * PageRank measures how connected somebody is inside the network on screen. It
 * is not a threat score, the platform does not compute one for these nodes, and
 * colouring it in crimson asserted one anyway. */

/** One token, resolved against :root. ECharts and MapLibre both need a concrete
 *  colour string, so the CSS custom property has to be read rather than passed. */
function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export const SEV = () => ({
  low: token("--ok", "#1c7a4c"),
  med: token("--amber", "#9c6410"),
  high: token("--red", "#b8362e"),
});

export const ACCENT = () => token("--gold", "#96701c");      // identity + selection
export const PRIMARY = () => token("--pri", "#1f6ed0");      // neutral analytical
export const VIOLET = () => token("--violet", "#574bb0");    // model output
export const MAP_POINT = () => token("--map-point", "#1e4a78");

// A fixed qualitative set for CATEGORY, never MAGNITUDE — crime type has no
// inherent order, so nothing here is a ramp. Kept clear of severity's
// green/amber/red and influence's slate/blue so a category dot is never
// mistaken for either scale.
const CATEGORY = [
  "#4e79a7", "#f28e2b", "#59a14f", "#af7aa1", "#76b7b2", "#edc949",
  "#ff9da7", "#9c755f", "#5b8c5a", "#7b6888", "#c9a227", "#3d7a91",
];

/** Deterministic colour for an open-ended category string (crime type, station,
 *  …) — same input always gets the same colour, spread across CATEGORY by a
 *  cheap string hash rather than a hand-maintained type->colour table. */
export function categorical(key: string | null | undefined): string {
  if (!key) return MAP_POINT();
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return CATEGORY[h % CATEGORY.length];
}

export const GRID = () => token("--chart-grid", "rgba(22,32,43,0.07)");
export const TEXT = () => token("--t-1", "#16202b");
export const TEXT_DIM = () => token("--t-2", "#41505f");
export const TEXT_FAINT = () => token("--t-3", "#6a7787");
export const SURFACE = () => token("--n-1", "#ffffff");
export const LINE = () => token("--line-2", "#d2d8df");
/** The backing plate behind a graph label, so text stays legible where the
 *  force layout cannot separate two nodes. */
export const LABEL_PLATE = () => token("--float", "rgba(255,255,255,0.94)");

/** Map a 0-1 intensity onto the SEVERITY ramp. Only for quantities that mean
 *  "how bad". */
export function ramp(t: number): string {
  const s = SEV();
  const x = clamp(t);
  return x < 0.5 ? mix(s.low, s.med, x / 0.5) : mix(s.med, s.high, (x - 0.5) / 0.5);
}

/** The three severity stops as a CSS gradient, for a legend swatch. */
export function sevGradient(): string {
  const s = SEV();
  return `linear-gradient(90deg, ${s.low}, ${s.med}, ${s.high})`;
}

/** Map a 0-1 centrality onto the INFLUENCE ramp: quiet slate for a peripheral
 *  node, saturated blue for a hub. Reads as "more connected", not "more
 *  dangerous", which is the only claim the data supports. */
export function influence(t: number): string {
  return mix(token("--t-4", "#97a2ad"), PRIMARY(), clamp(t));
}

export function influenceGradient(): string {
  return `linear-gradient(90deg, ${token("--t-4", "#97a2ad")}, ${PRIMARY()})`;
}

function clamp(t: number): number {
  return Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
}

/** Blends two colours. Accepts #rgb, #rrggbb or any rgb()/rgba() string, because
 *  a CSS custom property can legally hold any of them and a token read gives
 *  back whatever the author wrote. */
function parse(c: string): [number, number, number] {
  if (c.startsWith("#")) {
    const h = c.length === 4 ? `#${c[1]}${c[1]}${c[2]}${c[2]}${c[3]}${c[3]}` : c;
    return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
  }
  const m = c.match(/[\d.]+/g) ?? ["0", "0", "0"];
  return [Number(m[0]) || 0, Number(m[1]) || 0, Number(m[2]) || 0];
}

function mix(a: string, b: string, t: number): string {
  const pa = parse(a);
  const pb = parse(b);
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function rgba(color: string, alpha: number): string {
  const p = parse(color);
  return `rgba(${p[0]},${p[1]},${p[2]},${alpha})`;
}

/** Chart chrome, resolved at render time so it follows the theme. */
export function chartBase() {
  return {
    backgroundColor: "transparent",
    // Fast enough to read as "the chart appeared", slow enough not to pop.
    // The default second-long draw-on is a demo flourish on a workstation, and
    // it makes a screenshot of a fresh answer look like a half-loaded chart.
    animationDuration: 260,
    animationEasing: "cubicOut",
    textStyle: {
      color: TEXT_DIM(),
      fontFamily: "var(--font-sans), ui-sans-serif, system-ui",
    },
    tooltip: {
      backgroundColor: SURFACE(),
      borderColor: LINE(),
      borderWidth: 1,
      padding: [8, 11] as [number, number],
      textStyle: { color: TEXT(), fontSize: 12 },
      extraCssText: `border-radius: 6px; box-shadow: ${token("--shadow-pop", "0 8px 24px rgba(20,30,42,0.12)")};`,
    },
  };
}
