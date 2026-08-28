"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import CaseExplorer from "./CaseExplorer";
import type { Visualization } from "@/lib/types";

// Charts and MapLibre touch window/canvas — keep them out of the server bundle.
const NetworkView = dynamic(() => import("./viz/NetworkView"), { ssr: false });
const SankeyView = dynamic(() => import("./viz/SankeyView"), { ssr: false });
const TrendView = dynamic(() => import("./viz/TrendView"), { ssr: false });
const MapView = dynamic(() => import("./viz/MapView"), { ssr: false });
const TimelineView = dynamic(() => import("./viz/TimelineView"), { ssr: false });

const TITLES: Record<string, string> = {
  map: "Geospatial — hotspot density",
  network: "Criminal network",
  sankey: "Financial flow",
  trend: "Forecast",
  timeline: "Investigation timeline",
  none: "Case index",
};

/** The centre pane swaps by query type. The cross-fade is deliberate: a hard cut
 *  between a map and a graph is disorienting when both describe the same subject.
 *
 *  With no answer on screen yet it shows the case index rather than a placeholder —
 *  see CaseExplorer for why an empty console is an unusable one. */
export default function ContextView({
  viz, onAsk, onCopilot, onBoard, activeEvidence, onSelectEvidence, onPinEvidence,
}: {
  viz: Visualization;
  onAsk: (q: string) => void;
  onCopilot: (firId: string) => void;
  onBoard: (firId: string) => void;
  activeEvidence?: string | null;
  onSelectEvidence?: (id: string) => void;
  onPinEvidence?: (id: string) => void;
}) {
  const vizKind = viz?.kind ?? "none";

  // A new answer pulls the pane back to its visualization; the officer can always
  // return to the index, but a fresh result should never be hidden behind it.
  const [showIndex, setShowIndex] = useState(true);
  useEffect(() => setShowIndex(vizKind === "none"), [vizKind, viz?.data]);

  const kind = showIndex ? "none" : vizKind;

  return (
    <div className="pane glass" style={{ minWidth: 0 }}>
      <div className="pane-head">
        <span className="pane-title">{TITLES[kind] ?? "Context"}</span>
        <div className="tabs">
          {vizKind !== "none" && (
            <>
              <button
                className={`tab ${showIndex ? "on" : ""}`}
                onClick={() => setShowIndex(true)}
              >
                Case index
              </button>
              <button
                className={`tab ${!showIndex ? "on" : ""}`}
                onClick={() => setShowIndex(false)}
              >
                {TITLES[vizKind]}
              </button>
            </>
          )}
        </div>
      </div>
      <div className="pane-body" style={{ padding: kind === "none" ? 16 : 10 }}>
        <div className="viz">
          {kind === "none" ? (
            <CaseExplorer onAsk={onAsk} onCopilot={onCopilot} onBoard={onBoard} />
          ) : (
            <div className="viz-fade" key={kind + JSON.stringify(viz.data).length}>
              {kind === "network" && <NetworkView data={viz.data} />}
              {kind === "sankey" && <SankeyView data={viz.data} />}
              {kind === "trend" && <TrendView data={viz.data} />}
              {kind === "map" && (
                <MapView data={viz.data} activeEvidenceId={activeEvidence} onSelect={onSelectEvidence} />
              )}
              {kind === "timeline" && (
                <TimelineView data={viz.data} activeEvidenceId={activeEvidence}
                  onSelect={onSelectEvidence} onPin={onPinEvidence} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
