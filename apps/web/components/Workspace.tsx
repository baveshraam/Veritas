"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import CaseExplorer from "./CaseExplorer";
import Board from "./Board";
import { getCaseTimeline } from "@/lib/api";
import type { SessionFocusView, TimelineResult, Visualization } from "@/lib/types";
import type { WorkspaceView } from "./InvestigationHeader";

// Charts and MapLibre touch window/canvas — keep them out of the server bundle.
const NetworkView = dynamic(() => import("./viz/NetworkView"), { ssr: false });
const SankeyView = dynamic(() => import("./viz/SankeyView"), { ssr: false });
const TrendView = dynamic(() => import("./viz/TrendView"), { ssr: false });
const MapView = dynamic(() => import("./viz/MapView"), { ssr: false });
const TimelineView = dynamic(() => import("./viz/TimelineView"), { ssr: false });

const rupees = (n: number) =>
  n >= 1e7 ? `₹${(n / 1e7).toFixed(2)} Cr`
  : n >= 1e5 ? `₹${(n / 1e5).toFixed(2)} L`
  : `₹${Math.round(n).toLocaleString("en-IN")}`;

/** A view that has nothing loaded yet. Never a dead end: it says what the view
 *  is for and hands over the exact question that fills it, so a judge or an
 *  officer reaches the analysis in one click instead of guessing a phrasing. */
function Prompt({
  mark, title, body, ask, question, disabled,
}: {
  mark: string; title: string; body: string;
  ask: (q: string) => void; question: string | null; disabled?: boolean;
}) {
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden>{mark}</span>
      <h3>{title}</h3>
      <p>{body}</p>
      {question && !disabled && (
        <button className="btn" onClick={() => ask(question)}>{question}</button>
      )}
    </div>
  );
}

/** The primary workspace: one surface at a time, with a header that says what
 *  is being shown and what the numbers in it are.
 *
 *  The old centre pane swapped silently between a map and a graph with nothing
 *  above it but a title, so "499 incidents at relative density 1.00" was a fact
 *  the visualization contained and never stated. The analysis header states it. */
export default function Workspace({
  view, viz, focus, onAsk, onCopilot, onBoard, activeEvidence, onSelectEvidence,
  onPinEvidence, boardVersion,
}: {
  view: WorkspaceView;
  viz: Visualization;
  focus?: SessionFocusView;
  onAsk: (q: string) => void;
  onCopilot: (firId: string) => void;
  onBoard: (firId: string) => void;
  activeEvidence: string | null;
  onSelectEvidence: (id: string) => void;
  onPinEvidence: (id: string) => void;
  boardVersion: number;
}) {
  const kind = viz?.kind ?? "none";
  const d = viz?.data ?? {};
  const firId = focus?.case?.fir_id ?? null;
  const person = focus?.person?.name;

  // The Timeline view prefers the FULL case timeline over whatever a chat turn
  // happened to filter — the tab is a view of the case, not of the last answer.
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
  let figs: { n: string; l: string }[] = [];
  let body: React.ReactNode = null;
  let flush = false;

  if (view === "overview") {
    if (kind === "trend") {
      const s: any[] = d.series ?? [];
      const mean = s.length ? s.reduce((a, p) => a + p[1], 0) / s.length : 0;
      title = "Forecast";
      sub = "Prophet with MinT reconciliation — a district's forecast equals the sum of its stations.";
      figs = [
        { n: String(s.length), l: "days ahead" },
        { n: mean.toFixed(1), l: "mean FIRs/day" },
      ];
      body = <TrendView data={d} />;
    } else {
      title = "Case register";
      sub = "Every case your rank is cleared to see. Open one to start an investigation.";
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
      const main = [...districts][0];
      title = "Crime concentration";
      sub = districts.size === 1 && main
        ? `${main} — individual cases and modelled hotspot density`
        : `${districts.size} districts — individual cases and modelled hotspot density`;
      figs = [
        { n: String(pts.length), l: "cases located" },
        { n: String(polys.length), l: "hotspots" },
        ...(polys.length ? [{ n: peak.toFixed(2), l: "peak density" }] : []),
      ];
      body = <MapView data={d} activeEvidenceId={activeEvidence} onSelect={onSelectEvidence} />;
      flush = true;
    } else {
      title = "Geography";
      body = <Prompt mark="◈" title="No geography loaded"
        body="Locations for a case, or hotspot density for a district, appear here. Cases are records; hotspot regions are model output."
        ask={onAsk} question="Show me crime hotspots" />;
    }
  }

  if (view === "network") {
    if (kind === "network") {
      const nodes: any[] = d.nodes ?? [];
      const edges: any[] = d.edges ?? [];
      const communities = new Set(nodes.map((n) => n.community).filter((c) => c != null));
      title = "Criminal network";
      sub = "People reconstructed from accused records by probabilistic linkage, connected by shared cases.";
      figs = [
        { n: String(Math.max(0, nodes.length - 1)), l: "associates" },
        { n: String(edges.length), l: "links" },
        ...(communities.size ? [{ n: String(communities.size), l: "communities" }] : []),
      ];
      body = <NetworkView data={d} onAsk={onAsk} subjectLabel={person} />;
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
      title = "Financial trail";
      sub = "Transfers between accounts owned by people in this investigation. Direction is preserved — money moves one way.";
      figs = [
        { n: rupees(traced), l: "traced" },
        { n: String(links.length), l: "transfers" },
        { n: String(nodes.length), l: "accounts" },
      ];
      body = <SankeyView data={d} />;
      flush = true;
    } else {
      title = "Financial";
      body = <Prompt mark="◆" title="No money trail loaded"
        body="Financial analysis follows a person's accounts. Name the subject and Veritas traces the transfers between the accounts they own."
        ask={onAsk}
        question={person ? `Where did ${person}'s money go?` : null} />;
    }
  }

  if (view === "timeline") {
    const data = kind === "timeline" ? d : caseTl;
    const events: any[] = data?.events ?? [];
    title = "Investigation timeline";
    sub = "One chronology across the case, the people accused in it, and money through their accounts.";
    if (events.length) {
      const derived = events.filter((e) => e.kind === "derived").length;
      figs = [
        { n: String(events.length), l: "events" },
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

  return (
    <section className="col col-workspace" aria-label="Workspace">
      <div className="workspace">
        <div className="analysis">
          <div style={{ minWidth: 0 }}>
            <div className="analysis-title">{title}</div>
            {sub && <div className="analysis-sub">{sub}</div>}
          </div>
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
