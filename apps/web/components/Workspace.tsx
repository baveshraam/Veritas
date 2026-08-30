"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import CaseExplorer from "./CaseExplorer";
import CaseOverview from "./CaseOverview";
import PersonOverview from "./PersonOverview";
import Board from "./Board";
import { getCaseTimeline } from "@/lib/api";
import { densityReading, forecastReading, plural, rupees, type Reading } from "@/lib/metrics";
import { readNetwork } from "@/lib/network";
import type { EvidenceItem, SessionFocusView, TimelineResult, Visualization } from "@/lib/types";
import type { WorkspaceView } from "./InvestigationHeader";

// Charts and MapLibre touch window/canvas — keep them out of the server bundle.
const NetworkView = dynamic(() => import("./viz/NetworkView"), { ssr: false });
const SankeyView = dynamic(() => import("./viz/SankeyView"), { ssr: false });
const TrendView = dynamic(() => import("./viz/TrendView"), { ssr: false });
const MapView = dynamic(() => import("./viz/MapView"), { ssr: false });
const TimelineView = dynamic(() => import("./viz/TimelineView"), { ssr: false });

/** A view that has nothing loaded yet. Never a dead end: it says what the view
 *  is for and hands over the exact question that fills it, so a judge or an
 *  officer reaches the analysis in one click instead of guessing a phrasing. */
function Prompt({
  mark, title, body, ask, question,
}: {
  mark: string; title: string; body: string;
  ask: (q: string) => void; question: string | null;
}) {
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden>{mark}</span>
      <h3>{title}</h3>
      <p>{body}</p>
      {question && (
        <button className="btn" onClick={() => ask(question)}>{question}</button>
      )}
    </div>
  );
}

/** The primary workspace: one surface at a time, under a header that answers
 *  the questions a visualization cannot answer about itself — what this is,
 *  what it found, what KIND of claim that is, and what to do next.
 *
 *  The rule the header enforces (see lib/metrics.ts): the FINDING is the
 *  headline and the measurement sits under it. "Severe concentration" over
 *  "1.00"; "≈74 cases projected" over "2.5 mean FIRs/day". Nothing is hidden —
 *  a band is a reading of a number that is still printed beside it. */
export default function Workspace({
  view, viz, focus, evidence, onAsk, onCopilot, onBoard, activeEvidence, onSelectEvidence,
  onPinEvidence, boardVersion, sessionId,
}: {
  view: WorkspaceView;
  viz: Visualization;
  focus?: SessionFocusView;
  evidence: EvidenceItem[];
  onAsk: (q: string) => void;
  onCopilot: (firId: string) => void;
  onBoard: (firId: string) => void;
  activeEvidence: string | null;
  onSelectEvidence: (id: string) => void;
  onPinEvidence: (id: string) => void;
  boardVersion: number;
  /** Passed down so a selected node / case / event can ask GET /explain why it is
   *  on screen, with the session's own operation and focus as context. */
  sessionId?: string;
}) {
  const kind = viz?.kind ?? "none";
  const d = viz?.data ?? {};
  const firId = focus?.case?.fir_id ?? null;
  const person = focus?.person?.name;

  // The Timeline view prefers the FULL case timeline over whatever a chat turn
  // happened to filter — the tab is a view of the case, not of the last answer.
  // Opening a case turns Overview into the case's own overview. The register
  // must not become unreachable for that (it is also in ⌘K) — this is the one
  // click back to it, and it resets whenever the case changes.
  const [showRegister, setShowRegister] = useState(false);
  useEffect(() => { setShowRegister(false); }, [firId, focus?.person?.person_id]);

  const [caseTl, setCaseTl] = useState<TimelineResult | null>(null);
  const [tlError, setTlError] = useState<string | null>(null);
  useEffect(() => {
    if (view !== "timeline" || !firId || kind === "timeline") return;
    setCaseTl(null); setTlError(null);
    let live = true;
    getCaseTimeline(firId)
      .then((t) => live && setCaseTl(t))
      .catch((e) => live && setTlError(e.message));
    return () => { live = false; };
  }, [view, firId, kind]);

  let title = "Case register";
  let sub = "";
  let lead: Reading | null = null;
  let prov: "record" | "derived" | "model" | null = null;
  let figs: { n: string; l: string }[] = [];
  let next: { label: string; q: string } | null = null;
  let body: React.ReactNode = null;
  let flush = false;

  if (view === "overview") {
    if (kind === "trend") {
      const s: [string, number, number, number][] = d.series ?? [];
      const f = forecastReading(s);
      title = `${f.days}-day outlook`;
      sub = "Projected case volume, with the daily range the model considers likely.";
      lead = f;
      prov = "model";
      figs = [{ n: String(f.days), l: "days ahead" }];
      next = { label: "Where are these concentrated?", q: "Show me crime hotspots" };
      body = <TrendView data={d} />;
    } else if (firId && !showRegister) {
      // A case is open. The register is the right answer when nothing is; it is
      // the wrong one the moment something is, and it was what Overview showed.
      title = "Case overview";
      sub = "What this case is, who is in it, what is still open, and what changed most recently.";
      body = <CaseOverview firId={firId} onAsk={onAsk} onCopilot={onCopilot}
        refreshToken={boardVersion} />;
      next = { label: "Case register", q: "" };
      flush = true;
    } else if (focus?.person?.person_id && !showRegister) {
      // A person is the subject and no case is open — the identity-resolution
      // centrepiece (CLAUDE.md §0) otherwise had no home screen: priors, network,
      // financial and timeline all worked one question at a time, but Overview
      // fell back to the unfiltered case register regardless of who was asked
      // about.
      title = "Person overview";
      sub = "Who this is, the cases naming them, and what to ask next.";
      body = <PersonOverview personId={focus.person.person_id} name={person} onAsk={onAsk} />;
      next = { label: "Case register", q: "" };
      flush = true;
    } else {
      title = "Case register";
      sub = firId
        ? "Every case your rank is cleared to see. The case you are working stays open."
        : "Every case your rank is cleared to see. Open one to start an investigation.";
      if (firId) next = { label: "Back to this case", q: "" };
      body = <CaseExplorer onAsk={onAsk} onCopilot={onCopilot} onBoard={onBoard}
        activeFir={firId} />;
      flush = true;
    }
  }

  if (view === "geography") {
    if (kind === "map") {
      const pts: any[] = d.fir_points ?? [];
      const polys: any[] = d.polygons ?? [];
      const districts = new Set(pts.map((p) => p.district).filter(Boolean));
      const peak = polys.length ? Math.max(...polys.map((h) => h.intensity ?? 0)) : 0;
      const biggest = polys.length ? Math.max(...polys.map((h) => h.crime_count ?? 0)) : 0;
      const main = [...districts][0];
      title = "Crime concentration";
      sub = districts.size === 1 && main
        ? `${main} — cases as recorded, with modelled hotspot density drawn over them.`
        : `${districts.size} districts — cases as recorded, with modelled hotspot density drawn over them.`;
      if (polys.length) {
        lead = densityReading(peak);
        prov = "model";
      }
      figs = [
        { n: String(pts.length), l: "cases located" },
        ...(polys.length ? [
          { n: String(polys.length), l: "hotspots" },
          { n: String(biggest), l: "in the strongest" },
        ] : []),
      ];
      if (main) next = { label: `Cases in ${main}`, q: `Show me theft cases in ${main}` };
      body = <MapView data={d} activeEvidenceId={activeEvidence} onSelect={onSelectEvidence}
               onAsk={onAsk} sessionId={sessionId} />;
      flush = true;
    } else {
      title = "Geography";
      body = <Prompt mark="◈" title="No geography loaded"
        body="Locations for a case, or hotspot density for a district, appear here. Cases are records; hotspot regions are model output."
        ask={onAsk} question="Show me crime hotspots" />;
    }
  }

  const net = readNetwork(viz, evidence, person);

  if (view === "network") {
    if (kind === "network" && net) {
      title = "People and connections";
      // The layering, stated where the graph is. The copilot says the same
      // thing beside the answer — an officer arriving by tab never read that.
      const front = net.basis === "record" ? "named in these records" : "who offended alongside them";
      const wider = net.extended.length
        ? `, and ${net.extended.length} more reached through a chain of shared cases`
        : "";
      sub = net.direct.length
        ? `${plural(net.direct.length, "person", "people")} ${front}${wider}.`
        : "People reconstructed from accused records by probabilistic linkage, connected by the cases they share.";
      lead = {
        headline: net.direct.length
          ? `${net.direct.length} ${net.basis === "record" ? "directly involved" : "direct co-offenders"}`
          : `${net.total} in this network`,
        measure: `${plural(net.edges, "connection")} · ${net.total} people in view`,
      };
      prov = net.basis === "record" ? "record" : "derived";
      figs = [
        { n: String(net.direct.length), l: net.basis === "record" ? "named in record" : "direct" },
        { n: String(net.extended.length), l: "wider network" },
        ...(net.communities ? [{ n: String(net.communities), l: "communities" }] : []),
      ];
      if (net.extended[0]) {
        next = { label: `Examine ${net.extended[0].name}`, q: `Does ${net.extended[0].name} have priors?` };
      }
      body = <NetworkView data={d} onAsk={onAsk} subjectLabel={person} reading={net}
               sessionId={sessionId} />;
      flush = true;
    } else {
      title = "Network";
      body = <Prompt mark="◇" title="No network loaded"
        body="Name a person and Veritas traces who they offend with. Without a named subject there is nothing to traverse from, and picking one would be a guess."
        ask={onAsk}
        question={person ? `Who are the associates of ${person}?` : "Who are the associates of Usha Naika?"} />;
    }
  }

  if (view === "financial") {
    if (kind === "sankey") {
      const links: any[] = d.links ?? [];
      const nodes: any[] = d.nodes ?? [];
      const traced = links.reduce((a, l) => a + (l.value ?? 0), 0);
      const sources = new Set(links.map((l) => l.source)).size;
      const dests = new Set(links.map((l) => l.target)).size;
      title = "Financial trail";
      sub = "Transfers between accounts owned by people in this investigation. Direction is preserved — money moves one way.";
      lead = {
        headline: `${rupees(traced)} traced`,
        measure: `${plural(sources, "source account")} · ${plural(dests, "destination account")}`,
      };
      prov = "record";
      figs = [
        { n: String(links.length), l: "transfers" },
        { n: String(nodes.length), l: "accounts" },
      ];
      body = <SankeyView data={d} />;
      flush = true;
    } else {
      // A trail that was LOOKED FOR and not found is a finding, and must not
      // render as "nothing has been asked yet". The engine says which happened.
      const searched = evidence.find((e) => e.evidence_id.startsWith("flow:none:"));
      title = "Financial";
      if (searched) {
        lead = { headline: "No outbound trail", measure: "Within your access scope" };
        prov = "record";
        sub = "The accounts were traced. Nothing moved out of them in the records you can see.";
        body = <Prompt mark="◆" title="No outbound transfer trail"
          body={searched.content}
          ask={onAsk}
          question={person ? `Show me the timeline for ${person}` : null} />;
      } else {
        body = <Prompt mark="◆" title="No money trail loaded"
          body="Financial analysis follows a person's accounts. Name the subject and Veritas traces the transfers between the accounts they own."
          ask={onAsk}
          question={person ? `Where did ${person}'s money go?` : null} />;
      }
    }
  }

  if (view === "timeline") {
    const data = kind === "timeline" ? d : caseTl;
    const events: any[] = data?.events ?? [];
    title = "Investigation timeline";
    sub = "One chronology across the case, the people accused in it, and money through their accounts.";
    if (events.length) {
      const derived = events.filter((e) => e.kind === "derived").length;
      lead = {
        headline: plural(events.length, "dated event"),
        measure: `${events.length - derived} stated in the records · ${derived} linked by identity resolution`,
      };
      prov = derived ? "derived" : "record";
      figs = [
        { n: String(events.length - derived), l: "from records" },
        ...(derived ? [{ n: String(derived), l: "derived" }] : []),
      ];
      body = <TimelineView data={data} activeEvidenceId={activeEvidence}
        onSelect={onSelectEvidence} onPin={onPinEvidence} />;
    } else if (tlError) {
      body = <Prompt mark="◷" title="Timeline unavailable" body={tlError} ask={onAsk} question={null} />;
    } else if (firId && !caseTl) {
      body = <div className="empty"><span className="spinner" /><p>Building the case chronology…</p></div>;
    } else {
      body = <Prompt mark="◷" title="No timeline loaded"
        body="Open a case and its chronology appears here — its own dates, its accused persons' other cases, and any money that moved."
        ask={onAsk} question={firId ? null : "What happened in this case?"} />;
    }
  }

  if (view === "board") {
    title = "Investigation board";
    sub = "What this investigation has established, what is still open, and what you noted. It persists across sessions and officers.";
    body = firId
      ? <Board firId={firId} onAsk={onAsk} refreshToken={boardVersion} />
      : <Prompt mark="▣" title="No case open"
          body="The board belongs to a case. Open one from the register, or ask about a FIR, and its board becomes available here."
          ask={onAsk} question={null} />;
    flush = true;
  }

  const PROV_WORD = { record: "Record", derived: "Derived", model: "Model" } as const;

  return (
    <section className="col col-workspace" aria-label="Workspace">
      <div className="workspace">
        <div className="analysis">
          <div className="analysis-id">
            <div className="analysis-title">{title}</div>
            {sub && <div className="analysis-sub">{sub}</div>}
          </div>

          {lead && (
            <div className="analysis-lead">
              {prov && <span className={`prov prov-${prov}`}>{PROV_WORD[prov]}</span>}
              <div className="analysis-lead-n">{lead.headline}</div>
              <div className="analysis-lead-m">{lead.measure}</div>
            </div>
          )}

          {figs.length > 0 && (
            <div className="analysis-figs">
              {figs.map((f) => (
                <div className="analysis-fig" key={f.l}>
                  <div className="analysis-fig-n">{f.n}</div>
                  <div className="analysis-fig-l">{f.l}</div>
                </div>
              ))}
            </div>
          )}

          {next && (
            <div className="analysis-acts">
              <button className="btn btn-sm"
                onClick={() => (next!.q ? onAsk(next!.q) : setShowRegister((v) => !v))}>
                {next.label}
              </button>
            </div>
          )}
        </div>
        <div className={`stage ${flush ? "flush" : ""}`}>
          <div className="stage-inner">
            <div className="viz-enter" key={`${view}:${kind}`} style={{ height: "100%" }}>
              {body}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
