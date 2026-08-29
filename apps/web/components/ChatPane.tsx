"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import ReasoningTrace from "./ReasoningTrace";
import Progress from "./Progress";
import { summarise } from "@/lib/evidence";
import { blobToBase64 } from "@/lib/api";
import type { SessionFocusView, Turn } from "@/lib/types";

/** Push-to-talk capture with a live waveform, drawn from an AnalyserNode — no
 *  charting dependency needed for two dozen bars on a canvas. */
function useVoiceRecorder(onDone: (base64: string) => void) {
  const [recording, setRecording] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const rafRef = useRef<number>(0);
  const stopTracksRef = useRef<() => void>(() => {});

  const draw = (analyser: AnalyserNode) => {
    const data = new Uint8Array(analyser.frequencyBinCount);
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    const loop = () => {
      if (!canvas || !ctx) return;
      analyser.getByteTimeDomainData(data);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const bars = 28;
      const step = Math.floor(data.length / bars);
      for (let i = 0; i < bars; i++) {
        const v = Math.abs(data[i * step] - 128) / 128;
        const h = Math.max(2, v * canvas.height * 0.8);
        ctx.fillStyle = "#4084d8";
        ctx.globalAlpha = 0.45 + v * 0.55;
        ctx.fillRect(i * (canvas.width / bars), (canvas.height - h) / 2, canvas.width / bars - 2, h);
      }
      rafRef.current = requestAnimationFrame(loop);
    };
    loop();
  };

  const start = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stopTracksRef.current = () => stream.getTracks().forEach((t) => t.stop());

    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
    const ctx = new AudioCtx();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    ctx.createMediaStreamSource(stream).connect(analyser);
    draw(analyser);

    chunksRef.current = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => chunksRef.current.push(e.data);
    rec.onstop = async () => {
      cancelAnimationFrame(rafRef.current);
      stopTracksRef.current();
      ctx.close();
      const blob = new Blob(chunksRef.current, { type: rec.mimeType });
      if (blob.size > 0) onDone(await blobToBase64(blob));
    };
    rec.start();
    recRef.current = rec;
    setRecording(true);
  };

  const stop = () => { recRef.current?.stop(); setRecording(false); };
  return { recording, canvasRef, toggle: () => (recording ? stop() : start()) };
}

/** Renders the answer with its [n] markers as real, clickable controls.
 *
 *  The engine writes "[1]" as plain text; left as text, the citation is
 *  decorative. Splitting on the marker and binding each chip to its evidence is
 *  what turns "cited" into "checkable". */
function withCitations(
  text: string,
  onCite: (evidenceId: string) => void,
  citations: Turn["citations"],
  active: string | null,
) {
  return text.split(/(\[\d+\])/g).map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    if (!m) return <span key={i}>{p}</span>;
    const idx = Number(m[1]);
    const cite = citations.find((c) => c.index === idx);
    if (!cite) return <span key={i}>{p}</span>;
    return (
      <button
        key={i}
        // The evidence thread reads this to find the claim end of its line.
        data-cite={cite.evidence_id}
        className={`cite ${active === cite.evidence_id ? "lit" : ""}`}
        title={`Source ${idx}: ${cite.label}`}
        onClick={() => onCite(cite.evidence_id)}
      >
        {idx}
      </button>
    );
  });
}

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
  turns, busy, focus, onSend, onSendAudio, onCite, activeEvidence, onInspect, onEntity,
}: {
  turns: Turn[];
  busy: boolean;
  focus?: SessionFocusView;
  onSend: (q: string) => void;
  onSendAudio: (base64: string) => void;
  onCite: (evidenceId: string) => void;
  activeEvidence: string | null;
  onInspect: () => void;
  onEntity: (label: string) => void;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const { recording, canvasRef, toggle: toggleMic } = useVoiceRecorder(onSendAudio);

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
          const nodes: any[] = t.visualization?.kind === "network" ? (t.visualization.data?.nodes ?? []) : [];
          const top = [...nodes]
            .filter((n) => n.label && n.label !== "subject")
            .sort((a, b) => (b.pagerank ?? 0) - (a.pagerank ?? 0))
            .slice(0, 5);

          return (
            <article className="turn" key={t.id}>
              <div className="ask"><span>{t.query}</span></div>

              {t.streaming ? (
                <Progress trace={t.trace} />
              ) : (
                <ReasoningTrace trace={t.trace} />
              )}

              {t.answer && (t.refused ? (
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
                  <div className="finding-body">
                    {withCitations(t.answer, onCite, t.citations, activeEvidence)}
                  </div>

                  {top.length > 0 && (
                    <div className="module">
                      <div className="module-head">
                        <span className="label">Strongest connections</span>
                        <span className="prov prov-derived" title="Inferred from shared cases">Derived</span>
                      </div>
                      <div className="entity-list">
                        {top.map((n, i) => (
                          <button key={n.id} className="entity-row"
                            onClick={() => onEntity(n.label)}
                            title={`Examine ${n.label}`}>
                            <span className="entity-rank">{i + 1}</span>
                            <span>{n.label}</span>
                            <span className="mono">{(n.pagerank ?? 0).toFixed(3)}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

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
          {recording ? (
            <canvas ref={canvasRef} width={300} height={34} className="mic-wave" />
          ) : (
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
          )}
          <div className="composer-acts">
            <button
              className={`btn btn-sm ${recording ? "btn-rec" : ""}`}
              onClick={toggleMic}
              disabled={busy && !recording}
              title={recording ? "Stop and send" : "Speak a question in English or Kannada"}
            >
              {recording ? "Stop" : "Speak"}
            </button>
            {!recording && (
              <button className="btn btn-sm btn-primary" onClick={() => send()} disabled={busy || !text.trim()}>
                {busy ? <span className="spinner" style={{ width: 11, height: 11 }} /> : "Ask"}
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
