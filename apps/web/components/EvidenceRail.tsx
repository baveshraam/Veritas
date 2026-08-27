"use client";
import type { EvidenceItem } from "@/lib/types";
import { confidenceBand, confidenceLabel } from "@/lib/api";

/** Every citation chip in the answer opens its evidence here. The rail shows the
 *  FULL content, not just the label — a citation you cannot inspect is a citation
 *  you cannot check, which defeats the point of having one. */
export default function EvidenceRail({
  evidence, active, onSelect, onOpenCopilot, onOpenBoard, onPin,
}: {
  evidence: EvidenceItem[];
  active: string | null;
  onSelect: (id: string | null) => void;
  onOpenCopilot: (firId: string) => void;
  onOpenBoard: (firId: string) => void;
  onPin: (evidenceId: string) => void;
}) {
  if (!evidence.length) {
    return (
      <div className="viz-empty">
        <div style={{ fontSize: 22, opacity: 0.4 }}>◎</div>
        <div>Evidence for the current answer appears here.</div>
      </div>
    );
  }

  return (
    <>
      {evidence.map((e, i) => {
        const band = confidenceBand(e.confidence);
        const label = confidenceLabel(e.confidence_kind);
        // "model_estimate" items already carry their real number in the body text
        // (e.g. "risk score of 0.62, calibrated") — a second percentage here, under
        // a different meaning, would just be a second unlabeled number next to the
        // first. Only "support" and "similarity" render a percentage, and both are
        // labeled with what they actually measure, never a bare "confidence".
        return (
          <div
            key={e.evidence_id}
            id={`ev-${e.evidence_id}`}
            className={`ev ${active === e.evidence_id ? "active" : ""}`}
            onClick={() => onSelect(active === e.evidence_id ? null : e.evidence_id)}
          >
            <div className="ev-head">
              <span className="ev-idx">{i + 1}</span>
              <span className="ev-type">{e.source_type.replace(/_/g, " ")}</span>
              {e.confidence_kind === "model_estimate" ? (
                <span style={{ marginLeft: "auto" }} className="chip chip-fair" title={label}>
                  model output
                </span>
              ) : (
                <span style={{ marginLeft: "auto" }} className={`chip chip-${band}`} title={label}>
                  {(e.confidence * 100).toFixed(0)}% {label}
                </span>
              )}
            </div>
            <div className="ev-body">{e.content}</div>
            {active === e.evidence_id && e.source_query && (
              <div className="ev-src">{e.source_query}</div>
            )}
            {active === e.evidence_id && (
              <div className="ev-actions">
                {/* Pinning writes to the currently open case's board (resolved
                    server-side from session focus) — this evidence card need not be
                    a FIR record itself to be pinned, e.g. an associate relationship
                    or a risk finding are just as pinnable. */}
                <button
                  className="btn btn-sm"
                  onClick={(ev) => { ev.stopPropagation(); onPin(e.evidence_id); }}
                  title="Save this to the case's investigation board"
                >
                  Pin to board
                </button>
                {e.source_type === "FIR_RECORD" && /^\d+$/.test(e.source_id) && (
                  <>
                    <button
                      className="btn btn-sm"
                      onClick={(ev) => { ev.stopPropagation(); onOpenCopilot(e.source_id); }}
                    >
                      Open Investigation Copilot
                    </button>
                    <button
                      className="btn btn-sm"
                      onClick={(ev) => { ev.stopPropagation(); onOpenBoard(e.source_id); }}
                    >
                      Open Case Board
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
