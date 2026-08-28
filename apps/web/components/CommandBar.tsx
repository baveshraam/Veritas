"use client";
import { useEffect, useState } from "react";
import { getHealth, type Health } from "@/lib/api";
import type { Officer, SessionFocusView } from "@/lib/types";

/** Console-wide controls and identity.
 *
 *  Rank sits here rather than in the chat pane because it governs the whole console —
 *  the case index, the traversal depth and the masking all read it, not just the
 *  conversation. It gets the brass because it is the fact that changes what you see.
 *
 *  The status readout states what is actually loaded (records, graph, index). On a
 *  platform whose claim is "every answer traces to a record", the size of the record
 *  set is not decoration — it is the scope of what any answer can be drawn from. */
export default function CommandBar({
  officer, language, onLanguage, voiceOut, onVoiceOut, onExport, canExport, exportNote, onSignOut,
  focus,
}: {
  officer: Officer;
  focus?: SessionFocusView;
  language: "en" | "kn";
  onLanguage: (l: "en" | "kn") => void;
  voiceOut: boolean;
  onVoiceOut: (v: boolean) => void;
  onExport: () => void;
  canExport: boolean;
  exportNote?: string | null;
  onSignOut: () => void;
}) {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setDown(true));
  }, []);

  const fmt = (n: number) => n.toLocaleString("en-IN");

  return (
    <header className="topbar glass">
      <div className="brand">
        <h1>VERITAS</h1>
        <span className="brand-sub">Crime Intelligence</span>
      </div>

      <div className="status">
        <span className={`dot-live ${down ? "off" : ""}`} />
        {health ? (
          <span className="status-txt">
            <b>{fmt(health.firs)}</b> FIRs · <b>{fmt(health.graph_nodes)}</b> nodes ·{" "}
            <b>{fmt(health.indexed_documents)}</b> indexed
          </span>
        ) : (
          <span className="status-txt">{down ? "API unreachable" : "Checking records…"}</span>
        )}
      </div>

      {/* What the conversation is currently ABOUT. A follow-up ("does she have
          priors?", "what happened in it?") is answered against this, so it has to be
          on screen standing rather than buried in a collapsed reasoning trace —
          otherwise the officer cannot tell which record the last three answers were
          about. Names arrive already masked for this rank. */}
      {(focus?.case || focus?.person) && (
        <div className="focus-chip" title="What this conversation is currently about">
          <span className="focus-label">Examining</span>
          {focus.case && (
            <span className="focus-item">
              <span className="focus-kind">FIR</span>
              <span className="focus-val mono">{focus.case.fir_number ?? focus.case.fir_id}</span>
              {focus.case.district && <span className="focus-sub">{focus.case.district}</span>}
            </span>
          )}
          {focus.person && (
            <span className="focus-item">
              <span className="focus-kind">Person</span>
              <span className="focus-val">{focus.person.name ?? `#${focus.person.person_id}`}</span>
            </span>
          )}
        </div>
      )}

      <div className="bar-spacer" />

      <div className="tabs">
        {(["en", "kn"] as const).map((l) => (
          <button
            key={l}
            className={`tab ${language === l ? "on" : ""}`}
            onClick={() => onLanguage(l)}
            title={l === "en" ? "Answer in English" : "Answer in Kannada"}
          >
            {l === "en" ? "EN" : "ಕನ್ನಡ"}
          </button>
        ))}
        <button
          className={`tab ${voiceOut ? "on" : ""}`}
          onClick={() => onVoiceOut(!voiceOut)}
          title="Speak the answer aloud"
        >
          {voiceOut ? "Voice on" : "Voice off"}
        </button>
        <button className="tab" onClick={onExport} disabled={!canExport} title="Export this session as PDF">
          Export PDF
        </button>
        {exportNote && <span className="export-note" role="status">{exportNote}</span>}
      </div>

      <div className="officer-chip">
        <span className="rank">{officer.role}</span>
        <span className="who">{officer.name}</span>
        <span className="ps">{officer.ps_code === "—" ? "unverified" : `PS ${officer.ps_code}`}</span>
      </div>

      <button className="tab" onClick={onSignOut} title="Sign in as another rank">
        Switch
      </button>
    </header>
  );
}
