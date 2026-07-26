"use client";
import { useEffect, useState } from "react";

/** The evidence thread — draws a line from the cited claim to the record it rests on.
 *
 *  "Every claim traces to a record" is the platform's entire argument. Everywhere else
 *  it is asserted in prose; here it is the one thing you can watch happen. Selecting a
 *  citation traces a brass curve from the chip in the answer across to its card in the
 *  evidence rail.
 *
 *  Purely presentational: it reads geometry from the DOM and renders an overlay that
 *  never takes pointer events, so it cannot affect what it is describing. If either
 *  end is off-screen — the rail is hidden under 1280px — it draws nothing rather than
 *  pointing at a place the record is not. */
export default function EvidenceThread({ evidenceId }: { evidenceId: string | null }) {
  const [geom, setGeom] =
    useState<{ d: string; x: number; y: number; x0: number; y0: number } | null>(null);

  useEffect(() => {
    if (!evidenceId) {
      setGeom(null);
      return;
    }

    const measure = () => {
      const chip = document.querySelector<HTMLElement>(`[data-cite="${CSS.escape(evidenceId)}"]`);
      const card = document.getElementById(`ev-${evidenceId}`);
      if (!chip || !card) return setGeom(null);

      const a = chip.getBoundingClientRect();
      const b = card.getBoundingClientRect();
      // Both ends must actually be visible; the rail is display:none on narrow screens
      // and a rect of zero area would otherwise anchor the curve at the origin.
      if (!a.width || !b.width) return setGeom(null);

      // Leave from the EDGE of the conversation pane, not from the chip itself. Drawn
      // chip-first the line runs straight back across the sentence it is citing and
      // reads as a strikethrough — the one thing it must not look like. The chip is
      // already marked by its lit state, so the claim end is not ambiguous.
      const pane = chip.closest(".pane")?.getBoundingClientRect();
      if (!pane) return setGeom(null);
      const x1 = pane.right + 3;
      // Clamp to the pane so a citation scrolled out of view does not anchor the
      // line somewhere the claim is not.
      const y1 = Math.min(Math.max(a.top + a.height / 2, pane.top + 8), pane.bottom - 8);
      const x2 = b.left - 3;
      const y2 = b.top + Math.min(22, b.height / 2);
      // A flat-ish cubic: the curve should read as a link between two panes, not as an
      // arc drawing attention to itself.
      const dx = Math.max(40, (x2 - x1) * 0.45);
      setGeom({
        d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
        x0: x1, y0: y1, x: x2, y: y2,
      });
    };

    measure();
    // The card scrolls into view after selection, so re-measure until it settles.
    const t = setTimeout(measure, 260);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [evidenceId]);

  if (!geom) return null;

  return (
    <svg className="thread-layer" aria-hidden="true">
      {/* stroke-dasharray drives the draw-on animation and needs the path length; an
          over-estimate simply starts the dash further off-screen, which is invisible. */}
      <path className="thread-path" d={geom.d} style={{ ["--len" as string]: "1400" }} />
      <circle className="thread-end" cx={geom.x0} cy={geom.y0} r="2.5" />
      <circle className="thread-end" cx={geom.x} cy={geom.y} r="3" />
    </svg>
  );
}
