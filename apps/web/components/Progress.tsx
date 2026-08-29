"use client";
import type { TraceEntry } from "@/lib/types";

/** Named stages while an investigation runs, instead of a spinner.
 *
 *  "Loading…" tells an officer nothing about whether a 20-second wait is normal.
 *  These four stages are derived from the trace the engine already emits, so
 *  they report what is genuinely happening — and they are the same user-facing
 *  step names and details the reasoning trace shows afterwards. Nothing private
 *  is exposed here: no prompt, no model deliberation, only which part of the
 *  pipeline is working. */
const STAGES: { label: string; match: RegExp }[] = [
  { label: "Understanding the request", match: /^(Orchestrator|Translation|Voice Agent \(ASR\))/ },
  { label: "Retrieving records", match: /^(SQL Agent|Cypher Agent|HippoRAG|Think-on-Graph|Vector Search|Timeline|Case Board|Copilot|Prediction Agent|AML Detectors)/ },
  { label: "Verifying evidence", match: /^Evidence Evaluator/ },
  { label: "Preparing the result", match: /^(Evidence Synthesis|Synthesis|Voice Agent \(TTS\))/ },
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
        const latest = [...trace].reverse().find((t) => stageOf(t.step) === i);
        return (
          <div className={`progress-row ${state}`} key={s.label}>
            <span className="progress-mark" aria-hidden>
              {i < reached ? "✓" : i === reached ? "" : "○"}
            </span>
            <span>{s.label}</span>
            {state && latest && (
              <span className="progress-detail" title={latest.detail}>
                {latest.detail.length > 34 ? `${latest.detail.slice(0, 33)}…` : latest.detail}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
