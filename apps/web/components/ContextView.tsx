"use client";
import dynamic from "next/dynamic";
import type { Visualization } from "@/lib/types";

// Charts and MapLibre touch window/canvas — keep them out of the server bundle.
const NetworkView = dynamic(() => import("./viz/NetworkView"), { ssr: false });
const SankeyView = dynamic(() => import("./viz/SankeyView"), { ssr: false });
const TrendView = dynamic(() => import("./viz/TrendView"), { ssr: false });
const MapView = dynamic(() => import("./viz/MapView"), { ssr: false });

const TITLES: Record<string, string> = {
  map: "Geospatial — hotspot density",
  network: "Criminal network",
  sankey: "Financial flow",
  trend: "Forecast",
  none: "Context",
};

/** The centre pane swaps by query type. The cross-fade is deliberate: a hard cut
 *  between a map and a graph is disorienting when both describe the same subject. */
export default function ContextView({ viz }: { viz: Visualization }) {
  const kind = viz?.kind ?? "none";

  return (
    <div className="pane glass" style={{ minWidth: 0 }}>
      <div className="pane-head">
        <span className="pane-title">{TITLES[kind] ?? "Context"}</span>
        {kind !== "none" && (
          <span className="chip chip-low">
            <span className="dot-live" /> live
          </span>
        )}
      </div>
      <div className="pane-body" style={{ padding: kind === "none" ? 16 : 10 }}>
        <div className="viz">
          {kind === "none" ? (
            <div className="viz-empty">
              <div style={{ fontSize: 26, opacity: 0.35 }}>◍</div>
              <div style={{ maxWidth: 300, lineHeight: 1.6 }}>
                Ask about a network, a money trail, hotspots or a forecast and the
                matching view opens here.
              </div>
            </div>
          ) : (
            <div className="viz-fade" key={kind + JSON.stringify(viz.data).length}>
              {kind === "network" && <NetworkView data={viz.data} />}
              {kind === "sankey" && <SankeyView data={viz.data} />}
              {kind === "trend" && <TrendView data={viz.data} />}
              {kind === "map" && <MapView data={viz.data} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
