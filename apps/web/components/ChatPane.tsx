"use client";
import { useEffect, useRef, useState } from "react";
import type { Turn } from "@/lib/types";
import { blobToBase64 } from "@/lib/api";
import ReasoningTrace from "./ReasoningTrace";

/** Push-to-talk mic capture with a live waveform, drawn from an AnalyserNode —
 * no charting dependency needed for a dozen bars on a canvas. */
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
      const bars = 24;
      const step = Math.floor(data.length / bars);
      for (let i = 0; i < bars; i++) {
        const v = Math.abs(data[i * step] - 128) / 128;
        const h = Math.max(2, v * canvas.height);
        ctx.fillStyle = "#d8a657";
        ctx.globalAlpha = 0.55 + v * 0.45;
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

  const stop = () => {
    recRef.current?.stop();
    setRecording(false);
  };

  return { recording, canvasRef, toggle: () => (recording ? stop() : start()) };
}

/** Renders the answer with its [n] chips as real, clickable controls.
 *
 * The engine writes "[1]" as plain text; left as text, the citation is decorative.
 * Splitting on the marker and binding each chip to its evidence is what turns
 * "cited" into "checkable". */
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
        // The thread reads this to find the claim end of the line it draws.
        data-cite={cite.evidence_id}
        className={`cite ${active === cite.evidence_id ? "lit" : ""}`}
        title={cite.label}
        onClick={() => onCite(cite.evidence_id)}
      >
        {idx}
      </button>
    );
  });
}

export default function ChatPane({
  turns, busy, onSend, onSendAudio, onCite, activeEvidence,
}: {
  turns: Turn[];
  busy: boolean;
  onSend: (q: string) => void;
  onSendAudio: (base64: string) => void;
  onCite: (evidenceId: string) => void;
  activeEvidence: string | null;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const { recording, canvasRef, toggle: toggleMic } = useVoiceRecorder(onSendAudio);

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
        <span className="pane-title">Investigation</span>
        {turns.length > 0 && (
          <span className="chip chip-low">{turns.length} {turns.length === 1 ? "query" : "queries"}</span>
        )}
      </div>

      <div className="pane-body">
        {!turns.length && (
          <div className="intro">
            <p>
              <strong>The case index is open beside you.</strong> Search it and press{" "}
              <em>Ask about this case</em> on any card, or type a question here.
            </p>
            <p className="dim">Questions this console answers from the records:</p>
            <ul>
              <li>Who is accused in a case, and do they have priors?</li>
              <li>Who does this person offend with — and who runs that network?</li>
              <li>Where is theft concentrated in this district right now?</li>
              <li>Where did the money in this case go?</li>
              <li>How many cases should this station expect next month?</li>
            </ul>
            <p>
              Answers cite the FIR they came from. Select any{" "}
              <span className="cite" style={{ cursor: "default" }}>1</span> to trace it
              back to the record it rests on.
            </p>
          </div>
        )}

        {turns.map((t) => (
          <div className="msg" key={t.id}>
            <div className="msg-q">{t.query}</div>
            <ReasoningTrace trace={t.trace} streaming={t.streaming} />
            {t.answer && (
              <div className={`msg-a ${t.citations.length === 0 ? "refusal" : ""}`}>
                {withCitations(t.answer, onCite, t.citations, activeEvidence)}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="composer">
        {recording ? (
          <canvas ref={canvasRef} width={280} height={42} className="mic-wave" />
        ) : (
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
        )}
        <button
          className={`btn ${recording ? "btn-rec" : ""}`}
          onClick={toggleMic}
          disabled={busy && !recording}
          title={recording ? "Stop and send" : "Hold a question in English or Kannada"}
        >
          {recording ? "Stop" : "Speak"}
        </button>
        {!recording && (
          <button className="btn btn-accent" onClick={send} disabled={busy || !text.trim()}>
            {busy ? <span className="spinner" /> : "Ask"}
          </button>
        )}
      </div>
    </div>
  );
}
