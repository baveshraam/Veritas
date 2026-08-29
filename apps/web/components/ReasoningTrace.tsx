"use client";
import { useState } from "react";
import type { TraceEntry } from "@/lib/types";

/** The explainability surface — off by default, one click away, never removed.
 *
 *  This is not a debug log. It is the record of how the answer was reached,
 *  including when the answer was a refusal, and it is the thing an officer
 *  points at when asked why the system said what it said. */
export default function ReasoningTrace({ trace }: { trace: TraceEntry[] }) {
  const [open, setOpen] = useState(false);
  if (!trace.length) return null;

  const total = trace.reduce((s, t) => s + (t.duration_ms ?? 0), 0);

  return (
    <div className="trace">
      <button className="trace-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span aria-hidden>{open ? "▾" : "▸"}</span>
        How this was answered · {trace.length} steps
        {total > 0 && <span className="mono" style={{ color: "var(--t-4)" }}>{(total / 1000).toFixed(1)}s</span>}
      </button>
      {open && (
        <div className="trace-steps">
          {trace.map((t, i) => (
            <div className="trace-step" key={i} style={{ animationDelay: `${i * 35}ms` }}>
              <span><b>{t.step}</b> — {t.detail}</span>
              {t.duration_ms != null && <span className="ms">{t.duration_ms}ms</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
