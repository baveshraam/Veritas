"use client";
import { useEffect, useRef, useState } from "react";
import { blobToBase64 } from "@/lib/api";
import { useT } from "@/lib/i18n";

/* ============================================================================
 * PUSH-TO-TALK
 *
 * Kannada voice input is one of this platform's two documented reasons for
 * running its own models, and it was fronted by a text button reading "Speak"
 * that turned into a text button reading "Stop". Five things were wrong with
 * that, and each of them is something an officer hits on their first attempt:
 *
 *   1. Recording REPLACED the question field, so anything already typed
 *      vanished behind a canvas and came back only if you guessed that "Stop"
 *      would restore it.
 *   2. There was no way to ABANDON a recording. "Stop" sent it. Someone who
 *      starts talking, is interrupted, and wants to start again had no move
 *      except to let a bad recording go to the engine.
 *   3. Nothing said how long it had been listening, so a recording that had
 *      silently failed looked identical to one that was working.
 *   4. A denied microphone permission threw into a promise nobody awaited: the
 *      button flipped to "Stop" and recorded nothing, forever.
 *   5. Nothing announced the state change, so a screen reader user got no
 *      indication that the microphone was live.
 *
 * The shape here is the one every voice-note interface converged on because it
 * answers those: a mic button that becomes a recording BAR carrying a live
 * level meter, an elapsed timer, a discard and a send. The question field stays
 * where it is.
 * ========================================================================== */

/** Hard cap. A push-to-talk question is a sentence; a recording still running
 *  after a minute is a forgotten button, and sending 30MB of room noise to an
 *  ASR model is worse than stopping. */
const MAX_SECONDS = 60;
const WARN_AT = 50;

type Phase = "idle" | "asking" | "recording" | "denied" | "unsupported";

function Mic({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden focusable="false">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}

function mmss(total: number): string {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export default function VoiceRecorder({
  onCapture, disabled,
}: {
  /** Called with base64 audio only when the officer chooses to SEND. A discarded
   *  recording never reaches this — that is the whole point of having one. */
  onCapture: (base64: string) => void;
  disabled?: boolean;
}) {
  const t = useT();
  const [phase, setPhase] = useState<Phase>("idle");
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const rafRef = useRef(0);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cleanupRef = useRef<() => void>(() => {});
  // Whether the recording that is stopping should be SENT. Read inside
  // MediaRecorder.onstop, which fires asynchronously well after the click — a
  // ref, not state, because the handler closes over the value at stop time.
  const keepRef = useRef(true);

  useEffect(() => () => { cleanupRef.current(); }, []);

  const teardown = () => {
    cancelAnimationFrame(rafRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
    tickRef.current = null;
    cleanupRef.current();
    cleanupRef.current = () => {};
    setPhase("idle");
    setSeconds(0);
    setLevel(0);
  };

  const start = async () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia
        || typeof MediaRecorder === "undefined") {
      setPhase("unsupported");
      return;
    }
    setPhase("asking");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      // Denied, dismissed, or no device. All three are the same thing to the
      // officer — the microphone is not available — and all three used to leave
      // the button showing "Stop" over a recording that did not exist.
      setPhase("denied");
      return;
    }

    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
    const audio = new AudioCtx();
    const analyser = audio.createAnalyser();
    analyser.fftSize = 256;
    audio.createMediaStreamSource(stream).connect(analyser);

    cleanupRef.current = () => {
      stream.getTracks().forEach((t) => t.stop());
      audio.close().catch(() => {});
    };

    // The bar colour is read ONCE, not per bar per frame: the old loop called
    // getComputedStyle 28 times every animation frame, which is 1,680 forced
    // style reads a second to draw a colour that cannot change mid-recording.
    const css = getComputedStyle(document.documentElement);
    const barColor = css.getPropertyValue("--pri").trim() || "#1f6ed0";
    const data = new Uint8Array(analyser.frequencyBinCount);

    const loop = () => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (canvas && ctx) {
        analyser.getByteTimeDomainData(data);
        const bars = 32;
        const step = Math.floor(data.length / bars);
        const w = canvas.width / bars;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        let peak = 0;
        for (let i = 0; i < bars; i++) {
          const v = Math.abs(data[i * step] - 128) / 128;
          peak = Math.max(peak, v);
          const h = Math.max(2, v * canvas.height * 0.85);
          ctx.fillStyle = barColor;
          ctx.globalAlpha = 0.35 + v * 0.65;
          ctx.fillRect(i * w, (canvas.height - h) / 2, Math.max(1, w - 2), h);
        }
        setLevel(peak);
      }
      rafRef.current = requestAnimationFrame(loop);
    };
    loop();

    chunksRef.current = [];
    keepRef.current = true;
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => chunksRef.current.push(e.data);
    rec.onstop = async () => {
      const blob = new Blob(chunksRef.current, { type: rec.mimeType });
      const keep = keepRef.current;
      teardown();
      // A blob of a few hundred bytes is a click, not a question. Sending it
      // costs a full ASR round trip to be told nothing was said.
      if (keep && blob.size > 1024) onCapture(await blobToBase64(blob));
    };
    rec.start();
    recRef.current = rec;
    setPhase("recording");

    tickRef.current = setInterval(() => {
      setSeconds((s) => {
        if (s + 1 >= MAX_SECONDS) {
          keepRef.current = true;
          recRef.current?.stop();      // send what we have rather than truncate silently
        }
        return s + 1;
      });
    }, 1000);
  };

  const finish = (keep: boolean) => {
    keepRef.current = keep;
    if (recRef.current && recRef.current.state !== "inactive") recRef.current.stop();
    else teardown();
  };

  if (phase === "recording" || phase === "asking") {
    const near = seconds >= WARN_AT;
    return (
      <div className="rec" role="group" aria-label={t("Recording a question")}>
        <span className={`rec-dot${level > 0.06 ? " is-live" : ""}`} aria-hidden />
        <canvas ref={canvasRef} width={180} height={26} className="rec-wave" />
        <span className={`rec-time mono${near ? " is-near" : ""}`}>
          {mmss(seconds)}
        </span>
        {/* Politely announced once per state, not on every tick. */}
        <span className="sr-only" role="status" aria-live="polite">
          {t(phase === "asking" ? "Waiting for microphone permission" : "Recording. Choose send or discard.")}
        </span>
        <button className="btn btn-sm btn-quiet" onClick={() => finish(false)}
          title={t("Discard this recording")}>
          {t("Discard")}
        </button>
        <button className="btn btn-sm btn-primary" onClick={() => finish(true)}
          title={t("Stop recording and ask")}>
          {t("Send")}
        </button>
      </div>
    );
  }

  if (phase === "denied" || phase === "unsupported") {
    return (
      <div className="rec rec-off" role="status">
        <span className="meta">
          {t(phase === "denied"
            ? "Microphone blocked. Allow it in your browser's site settings, then try again."
            : "This browser cannot record audio. Type the question instead.")}
        </span>
        <button className="btn btn-sm btn-quiet" onClick={() => setPhase("idle")}>
          {t("Dismiss")}
        </button>
      </div>
    );
  }

  return (
    <button className="btn btn-sm btn-mic" onClick={start} disabled={disabled}
      title={t("Ask by voice, in English or Kannada")} aria-label={t("Ask by voice")}>
      <Mic />
      <span>{t("Speak")}</span>
    </button>
  );
}
