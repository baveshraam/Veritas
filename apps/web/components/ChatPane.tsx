"use client";
import { useEffect, useRef, useState } from "react";
import type { Turn } from "@/lib/types";
import ReasoningTrace from "./ReasoningTrace";

/** Renders the answer with its [n] chips as real, clickable controls.
 *
 * The engine writes "[1]" as plain text; left as text, the citation is decorative.
 * Splitting on the marker and binding each chip to its evidence is what turns
 * "cited" into "checkable". */
function withCitations(
  text: string,
  onCite: (evidenceId: string) => void,
  citations: Turn["citations"],
) {
  return text.split(/(\[\d+\])/g).map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (!m) return <span key={i}>{p}</span>;
    const idx = Number(m[1]);
    const cite = citations.find((c) => c.index === idx);
    if (!cite) return <span key={i}>{p}</span>;
    return (
      <button key={i} className="cite" title={cite.label} onClick={() => onCite(cite.evidence_id)}>
        {idx}
      </button>
    );
  });
}

export default function ChatPane({
  turns, busy, language, onLanguage, onSend, onCite, onExport, officer,
}: {
  turns: Turn[];
  busy: boolean;
  language: "en" | "kn";
  onLanguage: (l: "en" | "kn") => void;
  onSend: (q: string) => void;
  onCite: (evidenceId: string) => void;
  onExport: () => void;
  officer: { name: string; role: string; ps_code: string } | null;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  const send = () => {
    const q = text.trim();
    if (!q || busy) return;
    setText("");
    onSend(q);
  };

  return (
    <div className="pane glass">
      <div className="pane-head">
        <div>
          <div className="pane-title">Veritas</div>
          {officer && (
            <div style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 2 }}>
              {officer.name} · {officer.role} · {officer.ps_code}
            </div>
          )}
        </div>
        <div className="tabs">
          {(["en", "kn"] as const).map((l) => (
            <button
              key={l}
              className={`tab ${language === l ? "on" : ""}`}
              onClick={() => onLanguage(l)}
            >
              {l === "en" ? "EN" : "ಕನ್ನಡ"}
            </button>
          ))}
          <button className="tab" onClick={onExport} disabled={!turns.length} title="Export as PDF">
            PDF
          </button>
        </div>
      </div>

      <div className="pane-body">
        {!turns.length && (
          <div className="viz-empty" style={{ height: "auto", paddingTop: 40 }}>
            <div style={{ fontSize: 26, opacity: 0.35 }}>⌕</div>
            <div style={{ maxWidth: 285, lineHeight: 1.65 }}>
              Ask about a person, a network, a money trail, hotspots or a forecast.
              Every answer traces to a record — and where the records don&apos;t
              support one, it will say so rather than guess.
            </div>
          </div>
        )}

        {turns.map((t) => (
          <div className="msg" key={t.id}>
            <div className="msg-q">{t.query}</div>
            <ReasoningTrace trace={t.trace} streaming={t.streaming} />
            {t.answer && (
              <div className={`msg-a ${t.citations.length === 0 ? "refusal" : ""}`}>
                {withCitations(t.answer, onCite, t.citations)}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="composer">
        <textarea
          value={text}
          placeholder="Ask an investigative question…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="btn btn-accent" onClick={send} disabled={busy || !text.trim()}>
          {busy ? <span className="spinner" /> : "Ask"}
        </button>
      </div>
    </div>
  );
}
