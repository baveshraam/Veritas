"use client";
import { useEffect, useState } from "react";
import { getCopilotBrief } from "@/lib/api";
import type { CopilotBrief } from "@/lib/types";

/** Investigation Copilot — the "Monday morning" brief for one FIR: timeline,
 * MO-similar past cases, ranked leads, and a paste-ready case-diary draft.
 * Floats over the console as a glass overlay rather than a route, so an officer
 * never loses the conversation underneath. */
export default function Copilot({ firId, onClose }: { firId: string; onClose: () => void }) {
  const [brief, setBrief] = useState<CopilotBrief | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setBrief(null);
    setError(null);
    getCopilotBrief(firId).then(setBrief).catch((e) => setError(e.message));
  }, [firId]);

  const copy = () => {
    if (!brief) return;
    navigator.clipboard.writeText(brief.draft_summary).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="copilot-overlay" onClick={onClose}>
      <div className="pane glass copilot-panel" onClick={(e) => e.stopPropagation()}>
        <div className="pane-head">
          <span className="pane-title">Investigation Copilot — {firId.slice(0, 8)}</span>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        <div className="pane-body">
          {error && <div className="msg-a refusal">{error}</div>}
          {!brief && !error && <div className="spinner" style={{ margin: "20px auto" }} />}
          {brief && (
            <>
              <section className="copilot-section">
                <h3>Timeline</h3>
                {brief.timeline.length === 0 && <p className="dim">No dated events on record.</p>}
                {brief.timeline.map((ev, i) => (
                  <div key={i} className="copilot-row">
                    <span className="copilot-date">{ev.date}</span>
                    <span>{ev.event}</span>
                  </div>
                ))}
              </section>

              <section className="copilot-section">
                <h3>MO-similar cases</h3>
                {brief.similar_cases.length === 0 && <p className="dim">No similar cases found.</p>}
                {brief.similar_cases.map((c, i) => (
                  <div key={i} className="copilot-row">
                    <span className="copilot-date">{c.fir_number}</span>
                    <span>
                      {c.crime_type} · {c.district} — <span className="chip chip-low">{c.outcome}</span>
                    </span>
                    {/* WHY these two cases are similar, not a bare embedding score —
                        "same crime type" alone is a weak reason, and a raw percentage
                        cannot tell an officer whether it's method, section, or
                        district that actually lined up. */}
                    <div className="dim" style={{ fontSize: 12, marginTop: 2 }}>
                      {c.explanation}
                      {typeof c.similarity === "number" && (
                        <span> · {Math.round(c.similarity * 100)}% text similarity</span>
                      )}
                    </div>
                  </div>
                ))}
              </section>

              <section className="copilot-section">
                <h3>Leads</h3>
                {brief.leads.length === 0 && <p className="dim">No leads generated.</p>}
                <ul>{brief.leads.map((l, i) => <li key={i}>{l}</li>)}</ul>
              </section>

              <section className="copilot-section">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <h3>Draft case-diary summary</h3>
                  <button className="btn" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
                </div>
                <p className="copilot-draft">{brief.draft_summary}</p>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
