"use client";
import { useEffect, useState } from "react";
import { explainEvidence } from "@/lib/api";
import type { Derivation, DerivationBasis } from "@/lib/types";

/* ============================================================================
 * WHY IS THIS HERE?
 *
 * One render of the provenance chain, used everywhere a result can be pointed
 * at — the evidence inspector, a graph node, a case on the map, an event on the
 * timeline. One component rather than four, because the officer must not be able
 * to get two different accounts of the same result depending on where they
 * clicked; the server already guarantees that half of it (both this and the
 * typed "why is this connected?" call rag_agent.provenance.explain).
 *
 * The order is fixed and is the order the question is asked in:
 *
 *   CLAIM        what is being asserted
 *   BASIS        record / derived / model / prediction
 *   RECORDS      the specific records underneath it
 *   DERIVATION   how they were combined, in officer language
 *   QUALIFIES    why it made the cut, and what it does not mean
 *   NEXT         what can be asked about this exact thing
 *
 * There is deliberately no algorithm name, no component name, and no score in
 * the primary reading. Those are still available — the inspector's own "How this
 * was retrieved" field carries the query, and the Reasoning Trace panel carries
 * the pipeline — but reading them is a separate, deliberate act.
 * ========================================================================== */

/** The console's evidence rail has three provenance kinds; a chain has four. A
 *  forecast is a `model` for colouring purposes and a `prediction` for reading
 *  purposes, and both facts are true at once. */
const RAIL: Record<DerivationBasis, string> = {
  record: "prov-record", derived: "prov-derived",
  model: "prov-model", prediction: "prov-model",
};
const BASIS_WORD: Record<DerivationBasis, string> = {
  record: "Record", derived: "Derived", model: "Model", prediction: "Prediction",
};

export function WhyBody({ d, onAsk }: { d: Derivation; onAsk?: (q: string) => void }) {
  return (
    <div className="why">
      <p className="why-claim">{d.claim}</p>

      <div className="why-basis">
        <span className={`prov ${RAIL[d.basis]}`}>{BASIS_WORD[d.basis]}</span>
        <span className="meta">{d.basis_meaning}</span>
      </div>

      {d.records.length > 0 && (
        <div className="why-sec">
          <span className="label">Rests on</span>
          <ul className="why-records">
            {d.records.map((r, i) => (
              <li key={`${r.evidence_id ?? r.label}-${i}`}>
                <span className="why-rec-label mono">{r.label}</span>
                {r.detail && <span className="why-rec-detail">{r.detail}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {d.steps.length > 0 && (
        <div className="why-sec">
          <span className="label">How it was arrived at</span>
          <ol className="why-steps">
            {d.steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
        </div>
      )}

      {d.qualifies && (
        <div className="why-sec">
          <span className="label">Why it qualifies</span>
          <p className="why-text">{d.qualifies}</p>
        </div>
      )}

      {/* The caveat is ruled, not coloured red: "a co-accusation is not a finding
          of guilt" is the system working correctly, not an error. */}
      {d.caveat && (
        <div className="why-caveat">
          <span className="label">What it does not mean</span>
          <p className="why-text">{d.caveat}</p>
        </div>
      )}

      {d.incomplete && (
        <p className="why-incomplete">
          Some of this chain could not be reconstructed. What is shown is what the
          records themselves support — nothing has been filled in.
        </p>
      )}

      {onAsk && d.next_questions.length > 0 && (
        <div className="why-sec">
          <span className="label">Ask next</span>
          <div className="why-asks">
            {d.next_questions.map((q) => (
              <button key={q} className="btn btn-sm" onClick={() => onAsk(q)}>{q}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Self-fetching wrapper. Fetches once per evidence_id, on mount — a chain is
 *  only ever rendered because the officer deliberately asked for one, so there is
 *  nothing to defer behind a second click. */
export default function WhyChain({
  evidenceId, sessionId, onAsk,
}: { evidenceId: string; sessionId?: string; onAsk?: (q: string) => void }) {
  const [d, setD] = useState<Derivation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setD(null);
    setError(null);
    explainEvidence(evidenceId, sessionId)
      .then((r) => { if (live) setD(r); })
      .catch((e) => { if (live) setError(e?.message ?? "Could not load this"); });
    return () => { live = false; };
  }, [evidenceId, sessionId]);

  if (error) return <p className="why-incomplete">{error}</p>;
  if (!d) return <p className="meta">Tracing where this came from…</p>;
  return <WhyBody d={d} onAsk={onAsk} />;
}
