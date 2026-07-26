"use client";
import { useState } from "react";
import type { TraceEntry } from "@/lib/types";

/** The explainability surface, not a debug log — off by default, one click away.
 *  Renders the LangGraph trace in plain language so an officer can see WHY the
 *  system answered as it did, including when it refused. */
export default function ReasoningTrace({ trace, streaming }: { trace: TraceEntry[]; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  if (!trace.length && !streaming) return null;

  return (
    <div className="trace">
      <button className="trace-toggle" onClick={() => setOpen(!open)}>
        {streaming ? <span className="spinner" /> : <span>{open ? "▾" : "▸"}</span>}
        <span>
          {streaming ? "reasoning…" : `reasoning trace · ${trace.length} steps`}
        </span>
      </button>
      {(open || streaming) && (
        <div className="trace-steps">
          {trace.map((t, i) => (
            <div className="trace-step" key={i} style={{ animationDelay: `${i * 45}ms` }}>
              <span className="dot" />
              <span>
                <b style={{ color: "var(--text)", fontWeight: 600 }}>{t.step}</b>
                {" — "}{t.detail}
              </span>
              {t.duration_ms != null && <span className="ms">{t.duration_ms}ms</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
