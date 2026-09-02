"use client";
import { useCallback, useEffect, useState } from "react";
import ChatPane from "@/components/ChatPane";
import CommandPalette from "@/components/CommandPalette";
import Copilot from "@/components/Copilot";
import EvidenceInspector from "@/components/EvidenceInspector";
import EvidencePanel from "@/components/EvidencePanel";
import EvidenceThread from "@/components/EvidenceThread";
import InvestigationHeader, { VIEW_FOR_EVIDENCE, VIEW_FOR_VIZ, type WorkspaceView } from "@/components/InvestigationHeader";
import LoginGate from "@/components/LoginGate";
import TopBar from "@/components/TopBar";
import Workspace from "@/components/Workspace";
import { exportPdf, loadToken, playBase64Audio, setToken, streamChat } from "@/lib/api";
import { LangProvider, translate } from "@/lib/i18n";
import { readNetwork } from "@/lib/network";
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
  const t = useCallback(
    (s: string, vars?: Record<string, string | number>) => translate(s, language, vars),
    [language],
  );
  const [voiceOut, setVoiceOut] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [copilotFir, setCopilotFir] = useState<string | null>(null);
  const [copilotTab, setCopilotTab] = useState<"brief" | "board" | "timeline">("brief");
  const [exportNote, setExportNote] = useState<string | null>(null);
  const [view, setView] = useState<WorkspaceView>("overview");
  const [palette, setPalette] = useState(false);

  // One session for the whole conversation — this is what makes "does he have
  // priors" resolve against the previous turn on the server. Switchable: loading
  // a past session from history (pooled by rank+station, see SessionHistory)
  // replaces both the id and the turns it resolves against.
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());

  const loadHistorySession = useCallback((loaded: Turn[], sid: string) => {
    setSessionId(sid);
    setTurns(loaded);
    setActiveEvidence(null);
    setInspecting(false);
    setView("overview");
  }, []);

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
    async (input: { query?: string; audio?: string; activeEvidenceId?: string; silent?: boolean }) => {
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

      // Demonstration/unverified rank carries no token by design (LoginGate)
      // — every record-scoped question would otherwise fire and come back
      // "Chat failed (401)", read as the engine breaking rather than as the
      // designed consequence of not being signed in.
      if (!loadToken()) {
        patch((tn) => ({
          ...tn, streaming: false, unauthenticated: true,
          answer: t("This rank was entered without a verified badge, so no record-scoped question can be answered. Switch and sign in with a real badge to continue."),
        }));
        setBusy(false);
        return;
      }

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
            let next = VIEW_FOR_VIZ[f.visualization?.kind ?? "none"]
              // No visualization does not mean no subject: "no outbound trail
              // was found" is the financial answer, and it belongs in Financial.
              ?? VIEW_FOR_EVIDENCE.find(([re]) =>
                   f.evidence_items.some((e) => re.test(e.evidence_id)))?.[1];
            // Offenders and Repeat Offenders share one evidence prefix (both are
            // OFFENDER_RANKING) — the query text is what actually says which the
            // officer asked for, and it is the same regex the engine itself used
            // to turn on habitual_only server-side.
            if (next === "offenders" && /\b(repeat|habitual|chronic)\s+(offenders|criminals)\b/i.test(input.query ?? "")) {
              next = "repeat_offenders";
            }
            // A silent (tab-preload) query must never pull the workspace away
            // from wherever the officer has since clicked — that fight, not
            // any single answer, is what "stuck" meant.
            if (next && !input.silent) setView(next);
          },
          (audio) => playBase64Audio(audio),
        );
      } catch (e: any) {
        // Covers both a transport failure and an `error` frame from the engine.
        // Either way the turn must stop streaming and say so — never leave the
        // pane spinning — and it is a FAILURE, not a refusal.
        patch((tn) => ({
          ...tn,
          streaming: false,
          failed: true,
          answer: e?.message ?? t("The connection to the investigation engine was lost."),
        }));
      } finally {
        setBusy(false);
      }
    },
    [sessionId, language, voiceOut, activeEvidence, t],
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
    setExportNote(t("Exporting…"));
    exportPdf(sessionId)
      .then((isPdf) => {
        setExportNote(isPdf
          ? t("PDF downloaded.")
          : t("No PDF renderer on this deployment — a printable HTML copy was downloaded."));
        setTimeout(() => setExportNote(null), 8000);
      })
      .catch(() => {
        setExportNote(t("Export failed."));
        setTimeout(() => setExportNote(null), 8000);
      });
  }, [sessionId, t]);

  if (!officer) return <LoginGate onIn={setOfficer} />;

  const activeIndex = evidence.findIndex((e) => e.evidence_id === activeEvidence);
  const inspected = inspecting && activeIndex >= 0 ? evidence[activeIndex] : null;
  // People in the current network — from the same reading the workspace and the
  // copilot use, so the header can never disagree with the graph beside it. A
  // case's accused list has no root node, so "nodes - 1" undercounted it by one.
  const net = readNetwork(viz, evidence, focus?.person?.name);
  const networkSize = net ? net.total : null;

  return (
    <LangProvider value={language}>
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
        scopeLabel={t(SCOPE[officer.role] ?? "Scoped access")}
      />

      <div className={`workbench ${evidence.length ? "" : "lean"}`}>
        <ChatPane
          turns={turns}
          busy={busy}
          focus={focus}
          onSend={(query) => send({ query })}
          onSendAudio={(audio) => send({ audio })}
          onCite={revealEvidence}
          activeEvidence={activeEvidence}
          onInspect={() => openInspector(activeEvidence ?? evidence[0]?.evidence_id ?? "")}
          onLoadSession={loadHistorySession}
        />

        <Workspace
          view={view}
          viz={viz}
          focus={focus}
          evidence={evidence}
          onAsk={(query) => send({ query })}
          onPreload={(query) => send({ query, silent: true })}
          onCopilot={(fir) => { setCopilotTab("brief"); setCopilotFir(fir); }}
          onBoard={(fir) => { setCopilotTab("board"); setCopilotFir(fir); }}
          activeEvidence={activeEvidence}
          onSelectEvidence={revealEvidence}
          onPinEvidence={(id) => send({ query: "Add this event to the investigation board.", activeEvidenceId: id })}
          boardVersion={settled}
          sessionId={sessionId}
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
          sessionId={sessionId}
          onAsk={(q) => { setInspecting(false); send({ query: q }); }}
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
    </LangProvider>
  );
}
