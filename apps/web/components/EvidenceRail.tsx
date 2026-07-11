"use client";
import type { EvidenceItem } from "@/lib/types";
import { severityOf } from "@/lib/api";

/** Every citation chip in the answer opens its evidence here. The rail shows the
 *  FULL content, not just the label — a citation you cannot inspect is a citation
 *  you cannot check, which defeats the point of having one. */
export default function EvidenceRail({
  evidence, active, onSelect,
}: {
  evidence: EvidenceItem[];
  active: string | null;
  onSelect: (id: string | null) => void;
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
        const sev = severityOf(e.confidence);
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
              <span style={{ marginLeft: "auto" }} className={`chip chip-${sev}`}>
                {(e.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div className="ev-body">{e.content}</div>
            {active === e.evidence_id && e.source_query && (
              <div className="ev-src">{e.source_query}</div>
            )}
          </div>
        );
      })}
    </>
  );
}
