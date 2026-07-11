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
        ctx.fillStyle = "#2f6fed";
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
  turns, busy, language, onLanguage, onSend, onSendAudio, voiceOut, onVoiceOut,
  onCite, onExport, officer,
}: {
  turns: Turn[];
  busy: boolean;
  language: "en" | "kn";
  onLanguage: (l: "en" | "kn") => void;
  onSend: (q: string) => void;
  onSendAudio: (base64: string) => void;
  voiceOut: boolean;
  onVoiceOut: (v: boolean) => void;
  onCite: (evidenceId: string) => void;
  onExport: () => void;
  officer: { name: string; role: string; ps_code: string } | null;
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
          <button
            className={`tab ${voiceOut ? "on" : ""}`}
            onClick={() => onVoiceOut(!voiceOut)}
            title="Speak the answer aloud"
          >
            {voiceOut ? "🔊" : "🔈"}
          </button>
          <button className="tab" onClick={onExport} disabled={!turns.length} title="Export as PDF">
            PDF
          </button>
        </div>
      </div>

      <div className="pane-body">
        {!turns.length && (
          <div className="intro">
            <p>
              <strong>The case index is open beside you.</strong> Search it, then press{" "}
              <em>Ask about this case</em> on any card — or type a question here.
            </p>
            <p className="dim">What this console can answer:</p>
            <ul>
              <li>Who is accused in a case, and do they have priors?</li>
              <li>Who does this person offend with — and who runs that network?</li>
              <li>Where is theft concentrated in this district right now?</li>
              <li>Where did the money in this case go?</li>
              <li>How many cases should this station expect next month?</li>
            </ul>
            <p className="dim">
              Every answer cites the FIR it came from. Where the records don&apos;t
              support one, it says so instead of guessing.
            </p>
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
          title={recording ? "Stop and send" : "Push to talk"}
        >
          {recording ? "■" : "🎤"}
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
