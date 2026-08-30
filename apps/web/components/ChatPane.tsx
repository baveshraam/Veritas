"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import Finding from "./Finding";
import NetworkFinding from "./NetworkFinding";
import ReasoningTrace from "./ReasoningTrace";
import Progress from "./Progress";
import { summarise } from "@/lib/evidence";
import { readNetwork } from "@/lib/network";
import type { SessionFocusView, Turn } from "@/lib/types";
import VoiceRecorder from "./VoiceRecorder";

const OPENERS: { label: string; q: string }[] = [
  { label: "Person history", q: "Does Usha Naika have priors?" },
  { label: "Criminal network", q: "Who are the associates of Usha Naika?" },
  { label: "Geography", q: "Show me crime hotspots" },
  { label: "Forecast", q: "What are the crime trends?" },
];

/** Follow-ups that are real questions this engine answers, phrased the way its
 *  own intent classifier expects. Never a generic "tell me more". */
function followUps(focus: SessionFocusView | undefined, t: Turn): string[] {
  const out: string[] = [];
  const person = focus?.person?.name;
  if (focus?.case) {
    out.push("What happened in this case?", "Who is involved in this case?",
             "What should I investigate next?");
  }
  if (person) {
    out.push(`Does ${person} have priors?`, `Who are the associates of ${person}?`);
  }
  if (t.visualization.kind === "network" && focus?.case) out.push("Pin this to the case board");
  return out.filter((q) => q.toLowerCase() !== t.query.toLowerCase()).slice(0, 3);
}

export default function ChatPane({
  turns, busy, focus, onSend, onSendAudio, onCite, activeEvidence, onInspect,
}: {
  turns: Turn[];
  busy: boolean;
  focus?: SessionFocusView;
  onSend: (q: string) => void;
  onSendAudio: (base64: string) => void;
  onCite: (evidenceId: string) => void;
  activeEvidence: string | null;
  onInspect: () => void;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns, busy]);

  const send = (q?: string) => {
    const value = (q ?? text).trim();
    if (!value || busy) return;
    if (!q) setText("");
    onSend(value);
  };

  const last = turns[turns.length - 1];

  return (
    <section className="col col-copilot" aria-label="Investigation copilot">
      <div className="col-head">
        <span className="label">Copilot</span>
        <div className="col-head-right">
          {turns.length > 0 && (
            <span className="meta">{turns.length} {turns.length === 1 ? "question" : "questions"}</span>
          )}
        </div>
      </div>

      <div className="col-body copilot-scroll">
        {!turns.length && (
          <div className="opening">
            <h2>Ask an investigative question.</h2>
            <p>
              Answers are drawn from the case records you are cleared to see, and every
              claim carries the record it came from. Where the records don&apos;t support a
              claim, Veritas says so rather than guessing.
            </p>
            <div className="label" style={{ marginBottom: 7 }}>Start here</div>
            {OPENERS.map((o) => (
              <button key={o.q} className="opening-q" onClick={() => send(o.q)}>
                <b>{o.label}</b>
                {o.q}
              </button>
            ))}
          </div>
        )}

        {turns.map((t) => {
          const support = summarise(t.evidence);
          const ups = t.streaming ? [] : followUps(focus, t);
          const net = readNetwork(t.visualization, t.evidence, focus?.person?.name);

          return (
            <article className="turn" key={t.id}>
              <div className="ask"><span>{t.query}</span></div>

              {t.streaming ? (
                <Progress trace={t.trace} />
              ) : (
                <ReasoningTrace trace={t.trace} />
              )}

              {t.answer && (t.unauthenticated ? (
                <div className="refusal">
                  <div className="refusal-head">
                    <span aria-hidden>◇</span> Demonstration rank — not signed in
                  </div>
                  <div className="refusal-body">{t.answer}</div>
                </div>
              ) : t.refused ? (
                <div className="refusal">
                  <div className="refusal-head">
                    <span aria-hidden>◇</span> No supporting records
                  </div>
                  <div className="refusal-body">{t.answer}</div>
                  <div className="refusal-note">
                    This does not mean the event did not occur — only that nothing in the
                    records you can see establishes it. Narrow the question, name the
                    subject, or ask at a rank with wider scope.
                  </div>
                </div>
              ) : t.failed ? (
                <div className="failure">
                  <b>The investigation could not be completed.</b>
                  <div style={{ marginTop: 4 }}>{t.answer}</div>
                </div>
              ) : (
                <>
                  <div className="finding-head">
                    <span className="label">Finding</span>
                  </div>
                  <Finding text={t.answer} citations={t.citations}
                    active={activeEvidence} onCite={onCite} />

                  {net && <NetworkFinding reading={net} onAsk={(q) => send(q)} />}

                  {support.total > 0 && (
                    <div className="support">
                      <div className="support-head">
                        <span className="label">Evidence support</span>
                        <span className={`support-verdict is-${support.band}`}>{support.verdict}</span>
                      </div>
                      <div className={`support-bar support-verdict is-${support.band}`}>
                        {[0, 1, 2, 3].map((i) => (
                          <i key={i} className={i < support.steps ? "on" : ""} />
                        ))}
                      </div>
                      <div className="support-counts">
                        {support.authoritative > 0 && (
                          <span><span className="prov prov-record">Record</span> {support.authoritative} authoritative</span>
                        )}
                        {support.corroborating > 0 && (
                          <span><span className="prov prov-derived">Derived</span> {support.corroborating} corroborating</span>
                        )}
                        {support.modelled > 0 && (
                          <span><span className="prov prov-model">Model</span> {support.modelled} computed</span>
                        )}
                      </div>
                      <button className="btn btn-sm" style={{ marginTop: 9 }} onClick={onInspect}>
                        Inspect evidence
                      </button>
                    </div>
                  )}
                </>
              ))}

              {ups.length > 0 && t === last && (
                <div className="suggests">
                  {ups.map((q) => (
                    <button key={q} className="suggest" onClick={() => send(q)} disabled={busy}>
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </article>
          );
        })}
        <div ref={endRef} />
      </div>

      <div className="composer">
        <div className="composer-box">
          {/* The question field STAYS while recording. Replacing it with a canvas
              made anything already typed vanish, which is a thing an officer does
              by accident and cannot undo. */}
          <textarea
            ref={taRef}
            value={text}
            rows={1}
            placeholder="Ask about a case, a person, a district…"
            aria-label="Ask an investigative question"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
          />
          {/* A direct child of the box, not of the action cluster: while recording
              this becomes a FULL-WIDTH row above the field (see .rec in
              globals.css). Nested inside the cluster it overflowed a 390px column
              and pushed the Ask button off the edge of the panel. */}
          <VoiceRecorder onCapture={onSendAudio} disabled={busy} />
          <button className="btn btn-sm btn-primary composer-ask" onClick={() => send()}
            disabled={busy || !text.trim()}>
            {busy ? <span className="spinner" style={{ width: 11, height: 11 }} /> : "Ask"}
          </button>
        </div>
      </div>
    </section>
  );
}
