"use client";
import { useCallback, useMemo, useState } from "react";
import ChatPane from "@/components/ChatPane";
import ContextView from "@/components/ContextView";
import EvidenceRail from "@/components/EvidenceRail";
import LoginGate from "@/components/LoginGate";
import { exportPdf, streamChat } from "@/lib/api";
import type { Officer, Turn, Visualization } from "@/lib/types";

export default function Console() {
  const [officer, setOfficer] = useState<Officer | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [language, setLanguage] = useState<"en" | "kn">("en");
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);

  // One session for the whole conversation — this is what makes "does HE have
  // priors" resolve against the previous turn on the server.
  const sessionId = useMemo(() => crypto.randomUUID(), []);

  const latest = turns[turns.length - 1];
  const viz: Visualization = latest?.visualization ?? { kind: "none", data: {} };
  const evidence = latest?.evidence ?? [];

  const send = useCallback(
    async (query: string) => {
      const id = crypto.randomUUID();
      setBusy(true);
      setActiveEvidence(null);
      setTurns((t) => [
        ...t,
        { id, query, answer: "", streaming: true, trace: [],
          citations: [], evidence: [], visualization: { kind: "none", data: {} } },
      ]);

      const patch = (fn: (t: Turn) => Turn) =>
        setTurns((all) => all.map((t) => (t.id === id ? fn(t) : t)));

      try {
        await streamChat(
          sessionId, query, language,
          (tr) => patch((t) => ({ ...t, trace: [...t.trace, tr] })),
          (f) =>
            patch((t) => ({
              ...t,
              streaming: false,
              answer: f.final_answer,
              citations: f.citations,
              evidence: f.evidence_items,
              visualization: f.visualization,
            })),
        );
      } catch (e: any) {
        patch((t) => ({
          ...t,
          streaming: false,
          answer: `The console could not reach the investigation engine: ${e.message}`,
        }));
      } finally {
        setBusy(false);
      }
    },
    [sessionId, language],
  );

  const revealEvidence = useCallback((evidenceId: string) => {
    setActiveEvidence(evidenceId);
    document
      .getElementById(`ev-${evidenceId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  if (!officer) return <LoginGate onIn={setOfficer} />;

  return (
    <main className="console">
      <ChatPane
        turns={turns}
        busy={busy}
        language={language}
        onLanguage={setLanguage}
        onSend={send}
        onCite={revealEvidence}
        onExport={() => exportPdf(sessionId).catch(() => undefined)}
        officer={officer}
      />

      <ContextView viz={viz} />

      <div className="pane glass rail">
        <div className="pane-head">
          <span className="pane-title">Evidence</span>
          {evidence.length > 0 && (
            <span className="chip chip-low">{evidence.length} items</span>
          )}
        </div>
        <div className="pane-body">
          <EvidenceRail
            evidence={evidence}
            active={activeEvidence}
            onSelect={setActiveEvidence}
          />
        </div>
      </div>
    </main>
  );
}
