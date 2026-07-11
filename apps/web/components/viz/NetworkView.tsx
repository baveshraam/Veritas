"use client";
import ReactECharts from "echarts-for-react";
import { CHART_BASE, ACCENT, ramp, rgba } from "./palette";

type Node = { id: string; label: string; risk_score: number };
type Edge = { source: string; target: string; type: string; strength: number };

/** Force-directed criminal network. Node size and colour both encode influence,
 *  so the organiser is visible at a glance rather than requiring a legend hunt. */
export default function NetworkView({ data }: { data: { nodes: Node[]; edges: Edge[] } }) {
  const nodes = data.nodes ?? [];
  const edges = data.edges ?? [];
  const max = Math.max(1e-6, ...nodes.map((n) => n.risk_score ?? 0));

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
      force: { repulsion: 190, edgeLength: [45, 130], gravity: 0.08 },
      label: {
        show: true, position: "right", color: "#e8edfb", fontSize: 11,
        formatter: (p: any) => (p.data.value > max * 0.4 ? p.data.name : ""),
      },
      emphasis: { focus: "adjacency", label: { show: true } },
      lineStyle: { color: "source", opacity: 0.35, curveness: 0.12 },
      data: nodes.map((n) => {
        const t = (n.risk_score ?? 0) / max;
        return {
          id: n.id,
          name: n.label,
          value: n.risk_score ?? 0,
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
