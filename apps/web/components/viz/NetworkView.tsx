"use client";
import ReactECharts from "echarts-for-react";
import { CHART_BASE, ACCENT, TEXT_DIM, ramp, rgba } from "./palette";

type Node = { id: string; label: string; pagerank: number };
type Edge = { source: string; target: string; type: string; strength: number };

/** Force-directed criminal network. Node size and colour both encode influence,
 *  so the organiser is visible at a glance rather than requiring a legend hunt. */
export default function NetworkView({ data }: { data: { nodes: Node[]; edges: Edge[] } }) {
  const nodes = data.nodes ?? [];
  const edges = data.edges ?? [];
  const max = Math.max(1e-6, ...nodes.map((n) => n.pagerank ?? 0));

  // Two distinct people can share a display name (a real, unremarkable fact about
  // Indian names, not a data bug) — the evidence rail already disambiguates that
  // case in prose ("Suma Nadkarni (person 7334)"). The graph didn't: two nodes
  // both labelled bare "Suma Nadkarni" read as one duplicated node, not two
  // different associates. `n.id` already carries the real id (`person:8395`), so
  // any label collision gets the same short suffix the evidence text uses.
  const nameCounts = new Map<string, number>();
  for (const n of nodes) nameCounts.set(n.label, (nameCounts.get(n.label) ?? 0) + 1);
  const displayName = (n: Node) =>
    (nameCounts.get(n.label) ?? 0) > 1 ? `${n.label} (#${n.id.split(":").pop()})` : n.label;

  const option = {
    ...CHART_BASE,
    tooltip: { ...CHART_BASE.tooltip, formatter: (p: any) =>
      p.dataType === "node"
        ? `<b>${p.data.name}</b><br/>influence ${(p.data.value ?? 0).toFixed(3)}`
        : `${p.data.rel ?? "linked"}` },
    series: [{
      type: "graph",
      layout: "force",
      roam: true,
      draggable: true,
      // Wider repulsion/edgeLength than the previous 190/[45,130]: a single-hub
      // network with a dozen+ similarly-ranked leaf nodes packed them close enough
      // that their right-positioned labels overlapped into an unreadable smear.
      force: { repulsion: 280, edgeLength: [70, 190], gravity: 0.06 },
      // Labelling every node keeps a large expanded network legible (a 40%-of-max
      // cutoff already thins ~30 nodes down to the real hubs). But on a SMALL,
      // high-variance graph — e.g. a bare "who is involved" case-accused view with
      // 4 nodes and one clear organiser — that same cutoff zeroed out everyone but
      // the top node: 3 of 4 accused rendered as an unlabelled dot, unreadable to
      // an investigator. Below a small node count there is no clutter to justify
      // hiding a name, so every node keeps its label.
      label: {
        show: true, position: "right", color: TEXT_DIM, fontSize: 11,
        // A translucent backing box keeps a label legible where the wider force
        // layout still can't fully separate two nodes' text — readable in front
        // of another label or an edge line instead of dissolving into either.
        backgroundColor: rgba("#0a0e14", 0.72), padding: [1, 4], borderRadius: 3,
        formatter: (p: any) =>
          nodes.length <= 15 || p.data.value > max * 0.4 ? p.data.name : "",
      },
      emphasis: { focus: "adjacency", label: { show: true } },
      lineStyle: { color: "source", opacity: 0.35, curveness: 0.12 },
      data: nodes.map((n) => {
        const t = (n.pagerank ?? 0) / max;
        return {
          id: n.id,
          name: displayName(n),
          value: n.pagerank ?? 0,
          symbolSize: 12 + t * 30,
          itemStyle: {
            color: ramp(t),
            borderColor: rgba("#ffffff", 0.25),
            borderWidth: 1,
            shadowBlur: 14,
            shadowColor: rgba(ramp(t).startsWith("rgb") ? ACCENT : ACCENT, 0.5),
          },
        };
      }),
      links: edges.map((e) => ({
        source: e.source, target: e.target, rel: e.type,
        lineStyle: { width: 1 + (e.strength ?? 0) * 2.5 },
      })),
    }],
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} notMerge />;
}
