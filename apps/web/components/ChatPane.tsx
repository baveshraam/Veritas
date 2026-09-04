"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import Finding from "./Finding";
import NetworkFinding from "./NetworkFinding";
import ReasoningTrace from "./ReasoningTrace";
import Progress from "./Progress";
import SessionHistory from "./SessionHistory";
import { attachFile } from "@/lib/api";
import { summarise } from "@/lib/evidence";
import { translate, useLang, useT } from "@/lib/i18n";
import { readNetwork } from "@/lib/network";
import type { SessionFocusView, Turn } from "@/lib/types";
import VoiceRecorder from "./VoiceRecorder";

const OPENERS: { label: string; q: string }[] = [
  { label: "Interrogation prep", q: "What should I ask Usha Naika?" },
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
    out.push("What happened in this case?", "Catch me up on this case",
             "Would this case hold up?", "Who else should know about this?",
             "Check my other cases for a match", "Who is involved in this case?",
             "What should I investigate next?");
  }
  if (person) {
    out.push(`What should I ask ${person}?`, `Does ${person} have priors?`,
             `Who are the associates of ${person}?`);
  }
  if (t.visualization.kind === "network" && focus?.case) out.push("Pin this to the case board");
  const picked = out.filter((q) => q.toLowerCase() !== t.query.toLowerCase()).slice(0, 3);
  // The self-challenge is a meta-turn about THIS answer, so it earns a slot of its
  // own rather than competing with the case/person questions for one.
  if (t.evidence.length && t.query.toLowerCase() !== "convince me this is wrong") {
    picked.push("Convince me this is wrong");
  }
  return picked;
}

export default function ChatPane({
  turns, busy, focus, onSend, onSendAudio, onCite, activeEvidence, onInspect, onLoadSession,
}: {
  turns: Turn[];
  busy: boolean;
  focus?: SessionFocusView;
  onSend: (q: string) => void;
  onSendAudio: (base64: string) => void;
  onCite: (evidenceId: string) => void;
  activeEvidence: string | null;
  onInspect: () => void;
  onLoadSession: (turns: Turn[], sessionId: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  // Read-only PDF/Word text staged for the NEXT question only — never persisted,
  // never embedded, never cited: an attachment is context, not a record.
  const [attachment, setAttachment] = useState<{ filename: string; text: string } | null>(null);
  const [attaching, setAttaching] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns, busy]);

  const send = (q?: string) => {
    const value = (q ?? text).trim();
    if (!value || busy) return;
    if (!q) setText("");
    const withAttachment = attachment
      ? `Attached document "${attachment.filename}":\n"""\n${attachment.text}\n"""\n\n${value}`
      : value;
    setAttachment(null);
    onSend(withAttachment);
  };

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    setAttachError(null);
    setAttaching(true);
    try {
      const r = await attachFile(file);
      setAttachment({ filename: r.filename, text: r.text });
    } catch (e: any) {
      setAttachError(e?.message ?? t("Could not read this file"));
    } finally {
      setAttaching(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const last = turns[turns.length - 1];

  return (
    <section className="col col-copilot" aria-label="Investigation copilot">
      <div className="col-head">
        <span className="label">{t("Copilot")}</span>
        <div className="col-head-right">
          {turns.length > 0 && (
            <span className="meta">{turns.length} {t(turns.length === 1 ? "question" : "questions")}</span>
          )}
          <SessionHistory onLoad={onLoadSession} />
        </div>
      </div>

      <div className="col-body copilot-scroll">
        {!turns.length && (
          <div className="opening">
            <h2>{t("Ask an investigative question.")}</h2>
            <p>
              {t("Answers are drawn from the case records you are cleared to see, and every claim carries the record it came from. Where the records don't support a claim, Veritas says so rather than guessing.")}
            </p>
            <div className="label" style={{ marginBottom: 7 }}>{t("Start here")}</div>
            {OPENERS.map((o) => (
              <button key={o.q} className="opening-q" onClick={() => send(o.q)}>
                <b>{t(o.label)}</b>
                {t(o.q)}
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
                    <span aria-hidden>◇</span> {translate("Demonstration rank — not signed in", lang)}
                  </div>
                  <div className="refusal-body">{t.answer}</div>
                </div>
              ) : t.refused ? (
                <div className="refusal">
                  <div className="refusal-head">
                    <span aria-hidden>◇</span> {translate("No supporting records", lang)}
                  </div>
                  <div className="refusal-body">{t.answer}</div>
                  <div className="refusal-note">
                    {translate("This does not mean the event did not occur — only that nothing in the records you can see establishes it. Narrow the question, name the subject, or ask at a rank with wider scope.", lang)}
                  </div>
                </div>
              ) : t.failed ? (
                <div className="failure">
                  <b>{translate("The investigation could not be completed.", lang)}</b>
                  <div style={{ marginTop: 4 }}>{t.answer}</div>
                </div>
              ) : (
                <>
                  <div className="finding-head">
                    <span className="label">{translate("Finding", lang)}</span>
                  </div>
                  <Finding text={t.answer} citations={t.citations}
                    active={activeEvidence} onCite={onCite} />

                  {net && <NetworkFinding reading={net} onAsk={(q) => send(q)} />}

                  {support.total > 0 && (
                    <div className="support">
                      <div className="support-head">
                        <span className="label">{translate("Evidence support", lang)}</span>
                        <span className={`support-verdict is-${support.band}`}>{translate(support.verdict, lang)}</span>
                      </div>
                      <div className={`support-bar support-verdict is-${support.band}`}>
                        {[0, 1, 2, 3].map((i) => (
                          <i key={i} className={i < support.steps ? "on" : ""} />
                        ))}
                      </div>
                      <div className="support-counts">
                        {support.authoritative > 0 && (
                          <span><span className="prov prov-record">{translate("Record", lang)}</span> {support.authoritative} {translate("authoritative", lang)}</span>
                        )}
                        {support.corroborating > 0 && (
                          <span><span className="prov prov-derived">{translate("Derived", lang)}</span> {support.corroborating} {translate("corroborating", lang)}</span>
                        )}
                        {support.modelled > 0 && (
                          <span><span className="prov prov-model">{translate("Model", lang)}</span> {support.modelled} {translate("computed", lang)}</span>
                        )}
                      </div>
                      <button className="btn btn-sm" style={{ marginTop: 9 }} onClick={onInspect}>
                        {translate("Inspect evidence", lang)}
                      </button>
                    </div>
                  )}
                </>
              ))}

              {ups.length > 0 && t === last && (
                <div className="suggests">
                  {ups.map((q) => (
                    <button key={q} className="suggest" onClick={() => send(q)} disabled={busy}>
                      {translate(q, lang)}
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
        {(attachment || attaching || attachError) && (
          <div className="meta" style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
            {attaching && <span>{t("Reading file…")}</span>}
            {attachment && (
              <>
                <span>📎 {attachment.filename}</span>
                <button className="btn btn-quiet btn-sm" style={{ padding: "0 6px" }}
                  onClick={() => setAttachment(null)}>{t("Remove")}</button>
              </>
            )}
            {attachError && <span style={{ color: "var(--red)" }}>{attachError}</span>}
          </div>
        )}
        <div className="composer-box">
          {/* The question field STAYS while recording. Replacing it with a canvas
              made anything already typed vanish, which is a thing an officer does
              by accident and cannot undo. */}
          <textarea
            ref={taRef}
            value={text}
            rows={1}
            placeholder={t("Ask about a case, a person, a district…")}
            aria-label={t("Ask an investigative question")}
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
          <input ref={fileRef} type="file" accept=".pdf,.docx" style={{ display: "none" }}
            onChange={(e) => pickFile(e.target.files?.[0])} />
          <button className="btn btn-quiet btn-sm" type="button" disabled={busy || attaching}
            title={t("Attach a PDF or Word document as context")}
            onClick={() => fileRef.current?.click()}>
            📎
          </button>
          <button className="btn btn-sm btn-primary composer-ask" onClick={() => send()}
            disabled={busy || !text.trim()}>
            {busy ? <span className="spinner" style={{ width: 11, height: 11 }} /> : t("Ask")}
          </button>
        </div>
      </div>
    </section>
  );
}
