/* ============================================================================
 * METRIC LANGUAGE
 *
 * The system is mathematically involved. The officer reading it is not required
 * to be, and a headline number with no unit attached — "0.010", "1.00", "2.5" —
 * asks them to be. So every figure this console puts in a primary position is
 * translated here, once, into what it MEANS, with the measurement kept
 * underneath as the secondary line.
 *
 *   BAD   "0.010"                 GOOD  "Strongest connection"
 *                                        Network influence · 0.010
 *   BAD   "1.00 peak density"     GOOD  "Severe concentration"
 *                                        Relative density · 1.00
 *   BAD   "2.5 mean FIRs/day"     GOOD  "≈74 cases projected"
 *                                        Expected daily range · 2.1–2.9
 *
 * Nothing here invents precision the underlying number does not have, and
 * nothing here hides the number: a band is a reading of a figure that is still
 * printed next to it.
 * ========================================================================== */

/** A quantity as the officer says it, plus the measurement it came from. */
export type Reading = { headline: string; measure: string };

const CONNECTED = ["Peripheral", "Connected", "Well connected", "Central to this network"];

/** Graph centrality, 0-1 after normalisation against the measured maximum.
 *  Deliberately says "connected", never "dangerous" — PageRank measures a
 *  position in the graph on screen, and the platform computes no threat score
 *  for these nodes. */
export function influenceReading(normalised: number, raw: number): Reading {
  const i = normalised >= 0.75 ? 3 : normalised >= 0.45 ? 2 : normalised >= 0.18 ? 1 : 0;
  return { headline: CONNECTED[i], measure: `Network influence · ${raw.toFixed(3)}` };
}

const DENSITY = ["Low concentration", "Moderate concentration", "Elevated concentration", "Severe concentration"];

/** Hotspot density, 0-1 relative to the strongest cell in the same analysis.
 *  "Relative" is load-bearing and stays in the measurement line: 1.00 is the
 *  busiest place in THIS result, not an absolute crime rate. */
export function densityReading(intensity: number): Reading {
  const i = intensity >= 0.8 ? 3 : intensity >= 0.55 ? 2 : intensity >= 0.3 ? 1 : 0;
  return { headline: DENSITY[i], measure: `Relative density · ${intensity.toFixed(2)}` };
}

/** A forecast series of [date, point, lower, upper]. An officer plans against a
 *  total over a period, not against a mean per day — so the projection leads and
 *  the daily rate becomes the range underneath it. */
export function forecastReading(series: [string, number, number, number][]): Reading & { days: number } {
  const days = series.length;
  const total = series.reduce((a, p) => a + (p[1] ?? 0), 0);
  const lo = series.length ? Math.min(...series.map((p) => p[2] ?? 0)) : 0;
  const hi = series.length ? Math.max(...series.map((p) => p[3] ?? 0)) : 0;
  return {
    days,
    headline: `≈${Math.round(total)} cases projected`,
    measure: `Expected daily range · ${lo.toFixed(1)}–${hi.toFixed(1)}`,
  };
}

/** Money, in the units an Indian charge sheet is written in. */
export function rupees(n: number): string {
  if (!Number.isFinite(n)) return "₹0";
  return n >= 1e7 ? `₹${(n / 1e7).toFixed(2)} Cr`
       : n >= 1e5 ? `₹${(n / 1e5).toFixed(2)} L`
       : `₹${Math.round(n).toLocaleString("en-IN")}`;
}

/** "1 case" / "12 cases", without the "(s)" that reads as a form field. */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}

/** How closely two records' wording matches. Never phrased as truth: a high
 *  text match means the retrieval found similar words, which is a reason to
 *  look, not a reason to believe. */
export function matchReading(similarity: number): Reading {
  const h = similarity >= 0.8 ? "Closely related record"
          : similarity >= 0.6 ? "Related record"
          : "Loosely related record";
  return { headline: h, measure: `Text match · ${Math.round(similarity * 100)}%` };
}
