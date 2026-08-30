"use client";
import type { TraceEntry } from "@/lib/types";

/** Named stages while an investigation runs, instead of a spinner.
 *
 *  "Loading…" tells an officer nothing about whether a 20-second wait is normal.
 *  These four stages are derived from the trace the engine already emits, so
 *  they report what is genuinely happening.
 *
 *  WHAT THIS DELIBERATELY DOES NOT SHOW is the trace's raw `detail` string. It
 *  is written for an engineer and it says things like "Semantic model (QuickML)
 *  — no familiar phrasing matched, asking the model to interpret this question".
 *  Every word of that is true, and putting it in front of an officer mid-answer
 *  reads as "the system did not understand you" while the system is in fact
 *  understanding them. The detail is not suppressed — it is one click away in
 *  the reasoning trace, where opening it is a deliberate act. What belongs here
 *  is which part of the investigation is working, in the officer's language.
 *
 *  Nothing here is private: no prompt, no model deliberation, only the stage. */
const STAGES: { label: string; note: string; match: RegExp }[] = [
  { label: "Understanding the request", note: "Reading the question and the case in play",
    match: /^(Orchestrator|Translation|Voice Agent \(ASR\)|Semantic|Planner|Interpreter)/i },
  { label: "Retrieving records", note: "Searching the records you are cleared to see",
    match: /^(SQL Agent|Cypher Agent|HippoRAG|Think-on-Graph|Vector Search|Timeline|Case Board|Copilot|Prediction Agent|AML Detectors|Graph)/i },
  { label: "Verifying evidence", note: "Checking what the records actually support",
    match: /^Evidence Evaluator/i },
  { label: "Preparing the result", note: "Writing the finding and its citations",
    match: /^(Evidence Synthesis|Synthesis|Voice Agent \(TTS\))/i },
];

function stageOf(step: string): number {
  const i = STAGES.findIndex((s) => s.match.test(step));
  return i < 0 ? 0 : i;
}

export default function Progress({ trace }: { trace: TraceEntry[] }) {
  const reached = trace.length ? Math.max(...trace.map((t) => stageOf(t.step))) : 0;

  return (
    <div className="progress" role="status" aria-live="polite">
      <div className="label" style={{ marginBottom: 4 }}>Investigating</div>
      {STAGES.map((s, i) => {
        const state = i < reached ? "done" : i === reached ? "now" : "";
        return (
          <div className={`progress-row ${state}`} key={s.label}>
            <span className="progress-mark" aria-hidden>
              {i < reached ? "✓" : i === reached ? "" : "○"}
            </span>
            <span>{s.label}</span>
            {i === reached && <span className="progress-detail">{s.note}</span>}
          </div>
        );
      })}
    </div>
  );
}
