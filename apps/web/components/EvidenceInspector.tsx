"use client";
import { useEffect, useState } from "react";
import {
  band, CONF_MEANING, CONF_NAME, PROV_LABEL, PROV_MEANING, provenanceOf,
  showsPercent, sourceLabel,
} from "@/lib/evidence";
import type { EvidenceItem } from "@/lib/types";
import WhyChain from "./WhyChain";

function stamp(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso
    : d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric",
                                 hour: "2-digit", minute: "2-digit" });
}

/** The evidence inspector.
 *
 *  Opens over the workbench without navigating away from it — an officer
 *  checking a source has not stopped investigating, and losing the conversation
 *  to read a citation would be the wrong trade.
 *
 *  It answers five questions in a fixed order, because they are the ones an
 *  investigator actually asks of a source: what does the record say, WHY is it
 *  here, where did it come from, how sure is that, and what exactly was asked to
 *  get it.
 *
 *  "Why is it here" is the one this console could not answer until the
 *  provenance chain existed. The other four are properties of the item; that one
 *  is a property of the reasoning that produced it, so it is fetched (GET
 *  /explain) rather than read off the payload — and it is fetched only when the
 *  officer opens the section, because most inspections are a glance at the
 *  record, not an interrogation of it. */
export default function EvidenceInspector({
  item, index, total, sessionId, onClose, onPin, onCopilot, onBoard, onStep, onAsk,
}: {
  item: EvidenceItem;
  index: number;
  total: number;
  sessionId?: string;
  onClose: () => void;
  onPin: (id: string) => void;
  onCopilot: (firId: string) => void;
  onBoard: (firId: string) => void;
  onStep: (delta: number) => void;
  onAsk?: (query: string) => void;
}) {
  const [why, setWhy] = useState(false);
  // Collapse on navigating to a different source: the chain on screen must always
  // be the chain for the item on screen, and a stale one is worse than none.
  useEffect(() => setWhy(false), [item.evidence_id]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowDown" || e.key === "j") onStep(1);
      if (e.key === "ArrowUp" || e.key === "k") onStep(-1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose, onStep]);

  const p = provenanceOf(item);
  const b = band(item.confidence);
  const isFir = item.source_type === "FIR_RECORD" && /^\d+$/.test(item.source_id);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="inspector" role="dialog" aria-label="Evidence detail">
        <div className="inspector-head">
          <div style={{ minWidth: 0 }}>
            <div className="inspector-title mono">{item.source_id}</div>
            <div className="inspector-sub">
              Source {index + 1} of {total} · {sourceLabel(item)}
            </div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 5 }}>
            <button className="btn btn-sm" onClick={() => onStep(-1)} disabled={total < 2}
              title="Previous source (↑)">↑</button>
            <button className="btn btn-sm" onClick={() => onStep(1)} disabled={total < 2}
              title="Next source (↓)">↓</button>
            <button className="btn btn-sm" onClick={onClose} title="Close (Esc)">Close</button>
          </div>
        </div>

        <div className="inspector-body">
          <div className="field-block">
            <span className="label">
              {p === "record" ? "Record fact" : p === "derived" ? "Derived finding" : "Model output"}
            </span>
            <div className={`record-quote ${p === "derived" ? "is-derived" : p === "model" ? "is-model" : ""}`}>
              {item.content}
            </div>
          </div>

          <div className="field-block">
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <span className="label" style={{ margin: 0 }}>Why this is here</span>
              <button className="btn btn-sm btn-quiet" style={{ marginLeft: "auto" }}
                onClick={() => setWhy((v) => !v)}
                aria-expanded={why}>
                {why ? "Hide" : "Trace it"}
              </button>
            </div>
            {why ? (
              <WhyChain evidenceId={item.evidence_id} sessionId={sessionId} onAsk={onAsk} />
            ) : (
              <div className="meta">
                The records this rests on, how they were combined, and what it does not
                establish.
              </div>
            )}
          </div>

          <div className="field-block">
            <span className="label">Provenance</span>
            <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 5 }}>
              <span className={`prov prov-${p}`}>{PROV_LABEL[p]}</span>
              <span className="field-value quiet" style={{ fontSize: 13 }}>{sourceLabel(item)}</span>
            </div>
            <div className="meta">{PROV_MEANING[p]}</div>
          </div>

          <div className="field-block">
            <span className="label">{CONF_NAME[item.confidence_kind]}</span>
            {showsPercent(item.confidence_kind) ? (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 5 }}>
                  <div className={`support-bar support-verdict is-${b}`} style={{ flex: "0 0 90px", height: 4 }}>
                    {[0, 1, 2, 3].map((i) => (
                      <i key={i} className={i < Math.ceil(item.confidence * 4) ? "on" : ""} />
                    ))}
                  </div>
                  <span className={`support-verdict is-${b}`} style={{ fontFamily: "var(--font-rec)" }}>
                    {(item.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="meta">{CONF_MEANING[item.confidence_kind]}</div>
              </>
            ) : (
              <div className="meta">
                {CONF_MEANING[item.confidence_kind]} Read it in the text above rather than as a
                second percentage here.
              </div>
            )}
          </div>

          {item.source_query && (
            <div className="field-block">
              <span className="label">How this was retrieved</span>
              <div className="source-query">{item.source_query}</div>
            </div>
          )}

          <div className="field-block">
            <span className="label">Retrieved</span>
            <div className="field-value quiet mono" style={{ fontSize: 12.5 }}>{stamp(item.timestamp)}</div>
          </div>

          <div className="inspector-acts">
            <button className="btn" onClick={() => onPin(item.evidence_id)}
              title="Save this to the open case's investigation board">
              Pin to board
            </button>
            {isFir && (
              <>
                <button className="btn" onClick={() => onCopilot(item.source_id)}>Open case briefing</button>
                <button className="btn" onClick={() => onBoard(item.source_id)}>Open case board</button>
              </>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
