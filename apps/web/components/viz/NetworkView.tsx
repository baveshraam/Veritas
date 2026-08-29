"use client";
import { useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { CHART_BASE, ACCENT, TEXT_DIM, influence, rgba } from "./palette";

type Node = { id: string; label: string; pagerank: number };
type Edge = { source: string; target: string; type: string; strength: number };

const MAX_STATIC_LABELS = 12;

/** The co-offending network.
 *
 *  Two things this view is careful not to say. It does not colour influence on
 *  the severity ramp — PageRank measures how connected somebody is inside this
 *  graph, and painting that in crimson would assert a threat score the platform
 *  does not compute (see palette.ts). And it never calls a Louvain community a
 *  gang: the records document no gang, so the grouping is labelled as what it
 *  is — a network community derived from shared cases.
 *
 *  Selection is progressive disclosure: clicking a person dims the rest of the
 *  graph to their immediate neighbourhood and opens a small inspector, so a
 *  twenty-node network can be read one person at a time instead of all at once.
 */
export default function NetworkView({
  data, onAsk, subjectLabel,
}: {
  data: { nodes: Node[]; edges: Edge[] };
  onAsk?: (q: string) => void;
  /** The person the network was drawn around. The engine labels that node
   *  "subject", which is a placeholder, not a name — and the one node an
   *  officer most needs to identify should not be the only unlabelled one. */
  subjectLabel?: string | null;
}) {
  const nodes = useMemo(() => data.nodes ?? [], [data]);
  const edges = useMemo(() => data.edges ?? [], [data]);
  const [selected, setSelected] = useState<string | null>(null);

  // The engine gives the ROOT node a pagerank of exactly 1.0 as a display-sizing
  // sentinel (synthesis_agent.py says so) — it is not a measured centrality. Left
  // in the normalisation it sets the scale single-handedly, so every genuinely
  // measured value (0.003-0.01 in a real co-offending network) collapses to the
  // bottom of the ramp and twenty distinguishable associates render as twenty
  // identical grey dots. Scale on the real values; size the subject explicitly.
  const isRoot = (n: Node) => n.label === "subject" || (n.pagerank ?? 0) >= 1;
  const measured = nodes.filter((n) => !isRoot(n)).map((n) => n.pagerank ?? 0);
  const max = Math.max(1e-6, ...(measured.length ? measured : [1]));

  // Two distinct people can share a display name — a real, unremarkable fact
  // about Indian names, not a data bug. Two nodes both labelled bare "Suma
  // Nadkarni" read as one duplicated node rather than two different associates,
  // so a collision gets the same short id suffix the evidence text uses.
  const nameCounts = new Map<string, number>();
  for (const n of nodes) nameCounts.set(n.label, (nameCounts.get(n.label) ?? 0) + 1);
  const displayName = (n: Node) =>
    isRoot(n) ? (subjectLabel || n.label)
    : (nameCounts.get(n.label) ?? 0) > 1 ? `${n.label} (#${n.id.split(":").pop()})` : n.label;

  // A single-hub network with a dozen similarly-ranked associates has no real
  // separation at a percentage cutoff — they are all close to each other, just
  // not to the hub — so the always-labelled set is capped at a fixed, small
  // number instead. Every other node still labels on hover: the information is
  // not hidden, it is simply not all fighting for the same pixels at once.
  const alwaysLabeled = new Set([
    ...nodes.filter(isRoot).map((n) => n.id),
    ...(nodes.length <= 15 ? nodes.map((n) => n.id)
      : [...nodes].filter((n) => !isRoot(n))
          .sort((a, b) => (b.pagerank ?? 0) - (a.pagerank ?? 0))
          .slice(0, MAX_STATIC_LABELS).map((n) => n.id)),
  ]);

  const neighbours = useMemo(() => {
    if (!selected) return null;
    const set = new Set<string>([selected]);
    for (const e of edges) {
      if (e.source === selected) set.add(e.target);
      if (e.target === selected) set.add(e.source);
    }
    return set;
  }, [selected, edges]);

  const sel = selected ? nodes.find((n) => n.id === selected) ?? null : null;
  const selDegree = selected
    ? edges.filter((e) => e.source === selected || e.target === selected).length
    : 0;
  const selHops = selected
    ? (() => {
        const e = edges.find((x) => x.source === selected || x.target === selected);
        const s = e?.strength ?? 0;
        return s > 0 ? Math.max(1, Math.round(1 / s)) : null;
      })()
    : null;

  const option = {
    ...CHART_BASE,
    tooltip: {
      ...CHART_BASE.tooltip,
      formatter: (p: any) =>
        p.dataType === "node"
          ? `<b>${p.data.name}</b><br/><span style="color:#64768a">network influence ${(p.data.value ?? 0).toFixed(3)}</span>`
          : `${p.data.rel ?? "linked"}`,
    },
    series: [{
      type: "graph",
      layout: "force",
      roam: true,
      draggable: true,
      force: { repulsion: 300, edgeLength: [70, 190], gravity: 0.06 },
      label: {
        show: true, position: "right", color: TEXT_DIM, fontSize: 11,
        // A backing box keeps a label legible where the force layout cannot
        // fully separate two nodes' text.
        backgroundColor: "rgba(10,13,18,0.75)", padding: [1, 4], borderRadius: 3,
        formatter: (p: any) => (alwaysLabeled.has(p.data.id) ? p.data.name : ""),
      },
      emphasis: { focus: "adjacency", label: { show: true } },
      lineStyle: { color: "#4a5c70", opacity: 0.45, curveness: 0.1, width: 1 },
      data: nodes.map((n) => {
        const root = isRoot(n);
        const t = root ? 1 : Math.min(1, (n.pagerank ?? 0) / max);
        const isSel = n.id === selected;
        const dim = !!neighbours && !neighbours.has(n.id);
        return {
          id: n.id,
          name: displayName(n),
          value: n.pagerank ?? 0,
          symbolSize: root ? 30 : 11 + t * 17,
          itemStyle: {
            color: isSel ? ACCENT : root ? "#e8eef5" : influence(t),
            opacity: dim ? 0.16 : 1,
            borderColor: isSel ? ACCENT : root ? "rgba(64,132,216,0.55)" : "rgba(232,238,245,0.28)",
            borderWidth: isSel ? 2.5 : root ? 4 : 1,
          },
          label: { opacity: dim ? 0.18 : 1 },
        };
      }),
      links: edges.map((e) => {
        const dim = !!neighbours && !(neighbours.has(e.source) && neighbours.has(e.target));
        return {
          source: e.source, target: e.target, rel: e.type,
          lineStyle: {
            width: 0.8 + (e.strength ?? 0) * 2,
            opacity: dim ? 0.06 : 0.4,
            color: neighbours && !dim ? ACCENT : "#4a5c70",
          },
        };
      }),
    }],
  };

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <ReactECharts
        option={option}
        style={{ height: "100%", width: "100%" }}
        notMerge
        onEvents={{
          click: (p: any) => {
            if (p.dataType === "node") setSelected((s) => (s === p.data.id ? null : p.data.id));
            else setSelected(null);
          },
        }}
      />

      {sel && (
        <div className="node-card">
          <div className="node-card-name">{displayName(sel)}</div>
          <div className="meta mono" style={{ marginTop: 2 }}>{sel.id}</div>
          <div className="node-card-rows">
            <div className="node-card-row"><span>Links in view</span><b>{selDegree}</b></div>
            {selHops != null && (
              <div className="node-card-row"><span>Distance</span><b>{selHops} hop{selHops === 1 ? "" : "s"}</b></div>
            )}
            <div className="node-card-row"><span>Network influence</span><b>{(sel.pagerank ?? 0).toFixed(3)}</b></div>
          </div>
          <div style={{ display: "flex", gap: 5 }}>
            {onAsk && !isRoot(sel) && (
              <button className="btn btn-sm" onClick={() => onAsk(`Does ${sel.label} have priors?`)}>
                Examine person
              </button>
            )}
            <button className="btn btn-sm btn-quiet" onClick={() => setSelected(null)}>Clear</button>
          </div>
        </div>
      )}

      <div className="viz-legend">
        <span className="label">Network influence</span>
        <div className="viz-legend-row">
          <span className="viz-legend-scale"
            style={{ background: "linear-gradient(90deg, #5b7288, #4084d8)" }} />
          <span>peripheral → central</span>
        </div>
        <div className="viz-legend-row">
          <span className="viz-legend-scale" style={{ width: 10, height: 10, borderRadius: "50%", background: "#e8eef5" }} />
          <span>subject of the search</span>
        </div>
        <div className="viz-legend-row">
          <span className="viz-legend-scale" style={{ width: 10, height: 10, borderRadius: "50%", background: ACCENT }} />
          <span>selected</span>
        </div>
        <span className="meta" style={{ color: "var(--t-4)", maxWidth: 200 }}>
          Connectedness within this graph — not a risk score.
        </span>
      </div>
    </div>
  );
}
