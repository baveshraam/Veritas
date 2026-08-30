"use client";
import type { Citation } from "@/lib/types";

/* ============================================================================
 * THE FINDING
 *
 * An answer is not a chat message. It is a claim, the records the claim rests
 * on, and a note about how it was assembled — and the engine already writes it
 * in exactly that shape:
 *
 *     Based on 3 records in the system:
 *       [1] FIR 100222… — Hurt, filed 30 Jun 2026, status Under Investigation.
 *       [2] …
 *
 *     Every statement above is drawn directly from the cited records; no
 *     inference has been added.
 *
 * Rendered as one paragraph, that shape is invisible and the officer reads a
 * wall. Rendered as what it is, the claims are scannable, the count is a
 * caption rather than the first thing on screen, and the provenance sentence
 * becomes a footnote instead of competing with the evidence.
 *
 * NOTHING IS DROPPED. Every line the engine produced is on screen; only its
 * weight changes. Where the reasoning model wrote a fluent answer instead, the
 * shape does not match and the text renders as ordinary prose.
 * ========================================================================== */

const PREAMBLE = /^Based on \d[\d,]* (?:record|case)s? in the system:?$/i;
const FOOTNOTE = /^(Every statement above|No inference|Nothing above)/i;
const CLAIM = /^\s*\[(\d+)\]\s*(.*)$/;
const KANNADA = /[ಀ-೿]/;

/** Renders "[n]" markers as real, clickable controls.
 *
 *  The engine writes "[1]" as plain text; left as text, the citation is
 *  decorative. Splitting on the marker and binding each chip to its evidence is
 *  what turns "cited" into "checkable". */
function withCitations(
  text: string,
  onCite: (evidenceId: string) => void,
  citations: Citation[],
  active: string | null,
) {
  return text.split(/(\[\d+\])/g).map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (!m) return <span key={i}>{p}</span>;
    const idx = Number(m[1]);
    const cite = citations.find((c) => c.index === idx);
    if (!cite) return <span key={i}>{p}</span>;
    return <Chip key={i} idx={idx} cite={cite} active={active} onCite={onCite} />;
  });
}

function Chip({
  idx, cite, active, onCite,
}: { idx: number; cite: Citation; active: string | null; onCite: (id: string) => void }) {
  return (
    <button
      // The evidence thread reads this to find the claim end of its line.
      data-cite={cite.evidence_id}
      className={`cite ${active === cite.evidence_id ? "lit" : ""}`}
      title={`Source ${idx}: ${cite.label}`}
      onClick={() => onCite(cite.evidence_id)}
    >
      {idx}
    </button>
  );
}

export default function Finding({
  text, citations, active, onCite,
}: {
  text: string;
  citations: Citation[];
  active: string | null;
  onCite: (evidenceId: string) => void;
}) {
  const lines = text.split("\n");
  const kn = KANNADA.test(text);

  const blocks: React.ReactNode[] = [];
  let prose: string[] = [];

  const flush = (key: string) => {
    const body = prose.join("\n").trim();
    prose = [];
    if (body) {
      blocks.push(
        <p className="finding-p" key={key}>
          {withCitations(body, onCite, citations, active)}
        </p>,
      );
    }
  };

  lines.forEach((line, i) => {
    const t = line.trim();
    if (!t) { flush(`p${i}`); return; }

    if (PREAMBLE.test(t)) {
      flush(`p${i}`);
      blocks.push(<div className="finding-caption" key={`c${i}`}>{t.replace(/:$/, "")}</div>);
      return;
    }
    if (FOOTNOTE.test(t)) {
      flush(`p${i}`);
      blocks.push(<div className="finding-footnote" key={`f${i}`}>{t}</div>);
      return;
    }
    const m = t.match(CLAIM);
    if (m) {
      flush(`p${i}`);
      const cite = citations.find((c) => c.index === Number(m[1]));
      blocks.push(
        <div className="claim" key={`k${i}`}>
          {cite
            ? <Chip idx={Number(m[1])} cite={cite} active={active} onCite={onCite} />
            : <span className="cite" aria-hidden>{m[1]}</span>}
          <span className="claim-body">
            {withCitations(m[2], onCite, citations, active)}
          </span>
        </div>,
      );
      return;
    }
    prose.push(line);
  });
  flush("tail");

  return (
    <div className="finding-body" lang={kn ? "kn" : undefined}>
      {blocks}
    </div>
  );
}
