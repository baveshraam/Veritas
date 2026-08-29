"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import ChatPane from "@/components/ChatPane";
import CommandPalette from "@/components/CommandPalette";
import Copilot from "@/components/Copilot";
import EvidenceInspector from "@/components/EvidenceInspector";
import EvidencePanel from "@/components/EvidencePanel";
import EvidenceThread from "@/components/EvidenceThread";
import InvestigationHeader, { VIEW_FOR_VIZ, type WorkspaceView } from "@/components/InvestigationHeader";
import LoginGate from "@/components/LoginGate";
import TopBar from "@/components/TopBar";
import Workspace from "@/components/Workspace";
import { exportPdf, playBase64Audio, setToken, streamChat } from "@/lib/api";
import type { Officer, Turn, Visualization } from "@/lib/types";

/** Records visible at each rank, in one word. The console's most reviewable
 *  property is that the same question answers differently per rank, so the
 *  scope is stated in the investigation header rather than left to be
 *  discovered by hitting a 403. */
const SCOPE: Record<string, string> = {
  IO: "Station scope",
  SHO: "Station scope",
  DSP: "District scope",
  SP: "District scope",
  IG: "State scope",
  SCRB_Analyst: "State scope",
};

export default function Console() {
  const [officer, setOfficer] = useState<Officer | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [language, setLanguage] = useState<"en" | "kn">("en");
  const [voiceOut, setVoiceOut] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [copilotFir, setCopilotFir] = useState<string | null>(null);
  const [copilotTab, setCopilotTab] = useState<"brief" | "board" | "timeline">("brief");
  const [exportNote, setExportNote] = useState<string | null>(null);
  const [view, setView] = useState<WorkspaceView>("overview");
  const [palette, setPalette] = useState(false);

  // One session for the whole conversation — this is what makes "does he have
  // priors" resolve against the previous turn on the server.
  const sessionId = useMemo(() => crypto.randomUUID(), []);

  const latest = turns[turns.length - 1];
  const viz: Visualization = latest?.visualization ?? { kind: "none", data: {} };
  const evidence = latest?.evidence ?? [];
  // The most recent turn that actually resolved a subject. Not `latest?.focus`:
  // a refusal or a capability answer resolves nothing, and blanking the header
  // on those turns would tell the officer the case they are working had closed.
  const focus = [...turns].reverse().find((t) => t.focus && (t.focus.case || t.focus.person))?.focus;
  // A turn is appended to `turns` the instant it is SENT, so anything that must
  // re-read server state after a mutation has to count turns that have actually
  // finished — counting on turns.length reloads the board before the mutation
  // it triggered has landed, and reads stale state.
  const settled = turns.filter((t) => !t.streaming).length;

  const send = useCallback(
    async (input: { query?: string; audio?: string; activeEvidenceId?: string }) => {
      const id = crypto.randomUUID();
      setBusy(true);
      setInspecting(false);
      // A board action ("pin this") targets whatever evidence is already
      // selected — don't clear it out from under the request about to use it.
      if (!input.activeEvidenceId) setActiveEvidence(null);
      setTurns((t) => [
        ...t,
        { id, query: input.query ?? "Voice question", answer: "", streaming: true, refused: false,
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
          (f) => {
            patch((t) => ({
              ...t,
              streaming: false,
              answer: f.final_answer,
              refused: f.refused,
              citations: f.citations,
              evidence: f.evidence_items,
              visualization: f.visualization,
              focus: f.focus,
            }));
            // A new answer pulls the workspace to the view it produced. The
            // officer can always navigate back, but a fresh result must never
            // land behind a tab nobody is looking at.
            const next = VIEW_FOR_VIZ[f.visualization?.kind ?? "none"];
            if (next) setView(next);
          },
          (audio) => playBase64Audio(audio),
        );
      } catch (e: any) {
        // Covers both a transport failure and an `error` frame from the engine.
        // Either way the turn must stop streaming and say so — never leave the
        // pane spinning — and it is a FAILURE, not a refusal.
        patch((t) => ({
          ...t,
          streaming: false,
          failed: true,
          answer: e?.message ?? "The connection to the investigation engine was lost.",
        }));
      } finally {
        setBusy(false);
      }
    },
    [sessionId, language, voiceOut, activeEvidence],
  );

  /** Select a citation: highlight its source and draw the thread to it. The
   *  full record is one more click away, in the inspector — selecting must stay
   *  cheap enough to do while reading a sentence. */
  const revealEvidence = useCallback((evidenceId: string) => {
    setActiveEvidence(evidenceId);
    document.getElementById(`ev-${evidenceId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  const openInspector = useCallback((evidenceId: string) => {
    setActiveEvidence(evidenceId);
    setInspecting(true);
  }, []);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((v) => !v);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  const doExport = useCallback(() => {
    exportPdf(sessionId)
      .then((isPdf) => {
        if (!isPdf) {
          setExportNote("No PDF renderer on this deployment — a printable HTML copy was downloaded.");
          setTimeout(() => setExportNote(null), 8000);
        }
      })
      .catch(() => {
        setExportNote("Export failed.");
        setTimeout(() => setExportNote(null), 8000);
      });
  }, [sessionId]);

  if (!officer) return <LoginGate onIn={setOfficer} />;

  const activeIndex = evidence.findIndex((e) => e.evidence_id === activeEvidence);
  const inspected = inspecting && activeIndex >= 0 ? evidence[activeIndex] : null;
  const networkSize = viz.kind === "network" ? Math.max(0, (viz.data?.nodes?.length ?? 1) - 1) : null;

  return (
    <div className="app">
      <TopBar
        officer={officer}
        language={language}
        onLanguage={setLanguage}
        voiceOut={voiceOut}
        onVoiceOut={setVoiceOut}
        onSearch={() => setPalette(true)}
        onExport={doExport}
        canExport={turns.length > 0}
        exportNote={exportNote}
        onSignOut={() => { setToken(null); setOfficer(null); setTurns([]); setView("overview"); }}
      />

      <InvestigationHeader
        focus={focus}
        view={view}
        onView={setView}
        vizKind={viz.kind}
        citedCount={evidence.length}
        networkSize={networkSize}
        boardVersion={settled}
        scopeLabel={SCOPE[officer.role] ?? "Scoped access"}
      />

      <div className="workbench">
        <ChatPane
          turns={turns}
          busy={busy}
          focus={focus}
          onSend={(query) => send({ query })}
          onSendAudio={(audio) => send({ audio })}
          onCite={revealEvidence}
          activeEvidence={activeEvidence}
          onInspect={() => openInspector(activeEvidence ?? evidence[0]?.evidence_id ?? "")}
          onEntity={(name) => send({ query: `Does ${name} have priors?` })}
        />

        <Workspace
          view={view}
          viz={viz}
          focus={focus}
          onAsk={(query) => send({ query })}
          onCopilot={(fir) => { setCopilotTab("brief"); setCopilotFir(fir); }}
          onBoard={(fir) => { setCopilotTab("board"); setCopilotFir(fir); }}
          activeEvidence={activeEvidence}
          onSelectEvidence={revealEvidence}
          onPinEvidence={(id) => send({ query: "Add this event to the investigation board.", activeEvidenceId: id })}
          boardVersion={settled}
        />

        <EvidencePanel
          evidence={evidence}
          active={activeEvidence}
          onOpen={openInspector}
        />
      </div>

      <EvidenceThread evidenceId={inspecting ? null : activeEvidence} />

      {inspected && (
        <EvidenceInspector
          item={inspected}
          index={activeIndex}
          total={evidence.length}
          onClose={() => setInspecting(false)}
          onStep={(d) => {
            const next = evidence[(activeIndex + d + evidence.length) % evidence.length];
            if (next) setActiveEvidence(next.evidence_id);
          }}
          onPin={(id) => send({ query: "Pin this to the case board", activeEvidenceId: id })}
          onCopilot={(fir) => { setInspecting(false); setCopilotTab("brief"); setCopilotFir(fir); }}
          onBoard={(fir) => { setInspecting(false); setCopilotTab("board"); setCopilotFir(fir); }}
        />
      )}

      <CommandPalette
        open={palette}
        onClose={() => setPalette(false)}
        onAsk={(q) => send({ query: q })}
        onCopilot={(fir) => { setCopilotTab("brief"); setCopilotFir(fir); }}
        onBoard={(fir) => { setCopilotTab("board"); setCopilotFir(fir); }}
        onExport={doExport}
        canExport={turns.length > 0}
        onLanguage={setLanguage}
        language={language}
        focus={focus}
      />

      {copilotFir && (
        <Copilot
          firId={copilotFir}
          onClose={() => setCopilotFir(null)}
          onAsk={(query) => send({ query })}
          onPin={(id) => send({ query: "Add this event to the investigation board.", activeEvidenceId: id })}
          turnsVersion={settled}
          initialTab={copilotTab}
        />
      )}
    </div>
  );
}
