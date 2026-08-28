"use client";
import { useCallback, useMemo, useState } from "react";
import AlertToasts from "@/components/AlertToasts";
import ChatPane from "@/components/ChatPane";
import CommandBar from "@/components/CommandBar";
import ContextView from "@/components/ContextView";
import Copilot from "@/components/Copilot";
import EvidenceRail from "@/components/EvidenceRail";
import EvidenceThread from "@/components/EvidenceThread";
import LoginGate from "@/components/LoginGate";
import { exportPdf, playBase64Audio, setToken, streamChat } from "@/lib/api";
import type { Officer, Turn, Visualization } from "@/lib/types";

export default function Console() {
  const [officer, setOfficer] = useState<Officer | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [language, setLanguage] = useState<"en" | "kn">("en");
  const [voiceOut, setVoiceOut] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);
  const [copilotFir, setCopilotFir] = useState<string | null>(null);
  const [copilotTab, setCopilotTab] = useState<"brief" | "board" | "timeline">("brief");
  const [exportNote, setExportNote] = useState<string | null>(null);

  // One session for the whole conversation — this is what makes "does HE have
  // priors" resolve against the previous turn on the server.
  const sessionId = useMemo(() => crypto.randomUUID(), []);

  const latest = turns[turns.length - 1];
  const viz: Visualization = latest?.visualization ?? { kind: "none", data: {} };
  const evidence = latest?.evidence ?? [];
  // The most recent turn that actually resolved a subject. Not `latest?.focus`: a
  // refusal or a capability answer resolves nothing, and blanking the chip on those
  // turns would tell the officer the case they are working had been closed.
  const focus = [...turns].reverse().find((t) => t.focus && (t.focus.case || t.focus.person))?.focus;

  const send = useCallback(
    async (input: { query?: string; audio?: string; activeEvidenceId?: string }) => {
      const id = crypto.randomUUID();
      setBusy(true);
      // A board action ("pin this") targets whatever evidence card is already
      // selected — don't clear it out from under the request that is about to use it.
      if (!input.activeEvidenceId) setActiveEvidence(null);
      setTurns((t) => [
        ...t,
        { id, query: input.query ?? "🎤 Voice message", answer: "", streaming: true, refused: false,
          trace: [], citations: [], evidence: [], visualization: { kind: "none", data: {} } },
      ]);

      const patch = (fn: (t: Turn) => Turn) =>
        setTurns((all) => all.map((t) => (t.id === id ? fn(t) : t)));

      try {
        await streamChat(
          sessionId,
          { ...input, respondWithVoice: voiceOut,
            activeEvidenceId: input.activeEvidenceId ?? activeEvidence },
          language,
          (tr) => patch((t) => ({ ...t, trace: [...t.trace, tr] })),
          (f) =>
            patch((t) => ({
              ...t,
              streaming: false,
              answer: f.final_answer,
              refused: f.refused,
              citations: f.citations,
              evidence: f.evidence_items,
              visualization: f.visualization,
              focus: f.focus,
            })),
          (audio) => playBase64Audio(audio),
        );
      } catch (e: any) {
        // Covers both a transport failure and an `error` frame from the engine. Either
        // way the turn must stop streaming and say so — never leave the pane spinning.
        patch((t) => ({
          ...t,
          streaming: false,
          refused: true,
          answer: e?.message ?? "The investigation could not be completed.",
        }));
      } finally {
        setBusy(false);
      }
    },
    [sessionId, language, voiceOut, activeEvidence],
  );

  const revealEvidence = useCallback((evidenceId: string) => {
    setActiveEvidence(evidenceId);
    document
      .getElementById(`ev-${evidenceId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  if (!officer) return <LoginGate onIn={setOfficer} />;

  return (
    <div className="shell">
      <CommandBar
        officer={officer}
        language={language}
        onLanguage={setLanguage}
        voiceOut={voiceOut}
        onVoiceOut={setVoiceOut}
        onExport={() => {
          exportPdf(sessionId)
            .then((isPdf) => {
              if (!isPdf) {
                setExportNote("PDF renderer unavailable on this deployment — downloaded a printable HTML copy instead.");
                setTimeout(() => setExportNote(null), 7000);
              }
            })
            .catch(() => {
              setExportNote("Export failed.");
              setTimeout(() => setExportNote(null), 7000);
            });
        }}
        canExport={turns.length > 0}
        exportNote={exportNote}
        onSignOut={() => { setToken(null); setOfficer(null); setTurns([]); }}
        focus={focus}
      />

      <main className="console">
        <ChatPane
          turns={turns}
          busy={busy}
          onSend={(query) => send({ query })}
          onSendAudio={(audio) => send({ audio })}
          onCite={revealEvidence}
          activeEvidence={activeEvidence}
        />

        <ContextView
          viz={viz}
          onAsk={(query) => send({ query })}
          onCopilot={(fir) => { setCopilotTab("brief"); setCopilotFir(fir); }}
          onBoard={(fir) => { setCopilotTab("board"); setCopilotFir(fir); }}
          activeEvidence={activeEvidence}
          onSelectEvidence={revealEvidence}
          onPinEvidence={(evidenceId) => send({ query: "Add this event to the investigation board.", activeEvidenceId: evidenceId })}
        />

        <div className="pane glass rail">
          <div className="pane-head">
            <span className="pane-title">Evidence</span>
            {evidence.length > 0 && (
              <span className="chip chip-low">{evidence.length} cited</span>
            )}
          </div>
          <AlertToasts />
          <div className="pane-body">
            <EvidenceRail
              evidence={evidence}
              active={activeEvidence}
              onSelect={setActiveEvidence}
              onOpenCopilot={(fir) => { setCopilotTab("brief"); setCopilotFir(fir); }}
              onOpenBoard={(fir) => { setCopilotTab("board"); setCopilotFir(fir); }}
              onPin={(evidenceId) => send({ query: "Pin this to the case board", activeEvidenceId: evidenceId })}
            />
          </div>
        </div>
      </main>

      <EvidenceThread evidenceId={activeEvidence} />
      {copilotFir && (
        <Copilot
          firId={copilotFir}
          onClose={() => setCopilotFir(null)}
          onAsk={(query) => send({ query })}
          onPin={(evidenceId) => send({ query: "Add this event to the investigation board.", activeEvidenceId: evidenceId })}
          // The Board panel refetches when this changes — it must count turns that
          // have actually FINISHED, not turns.length: a turn is appended to `turns`
          // the instant it's sent (so the answer can stream in), well before a board
          // mutation it triggers has actually landed server-side. Counting on
          // turns.length reloaded the board immediately on submit and read stale
          // (pre-mutation) state, then never reloaded again once the real answer
          // arrived — a lead saved via the panel's own form silently failed to
          // appear until something else happened to remount the panel.
          turnsVersion={turns.filter((t) => !t.streaming).length}
          initialTab={copilotTab}
        />
      )}
    </div>
  );
}
