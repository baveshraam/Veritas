"use client";
import ReactECharts from "echarts-for-react";
import { CHART_BASE, ACCENT, TEXT_DIM, ramp, rgba } from "./palette";

/** Money-flow Sankey. Deliberately distinct from the criminal-network view: a
 *  transfer has direction and magnitude, which a force graph cannot show. */
// Above this many nodes on one side, every label at a fixed 10px row height no
// longer fits the chart's height without overlapping (measured live: a 60-
// destination-account trail became unreadable, UI-26). Rather than shrink text
// past legibility or add a scrollable canvas ECharts' sankey series doesn't
// support, only the highest-value nodes keep a label — still every node stays
// hoverable via the tooltip, so no information is lost, just decluttered.
const LABEL_ALL_BELOW = 25;
const MAX_LABELS_WHEN_CROWDED = 20;

export default function SankeyView({ data }: { data: { nodes: { name: string }[]; links: any[] } }) {
  const links = data.links ?? [];
  const nodes = data.nodes ?? [];
  const max = Math.max(1e-6, ...links.map((l) => l.value ?? 0));

  const flowOf = new Map<string, number>();
  for (const l of links) {
    flowOf.set(l.source, (flowOf.get(l.source) ?? 0) + (l.value ?? 0));
    flowOf.set(l.target, (flowOf.get(l.target) ?? 0) + (l.value ?? 0));
  }
  const labeled = nodes.length > LABEL_ALL_BELOW
    ? new Set(
        [...nodes]
          .sort((a, b) => (flowOf.get(b.name) ?? 0) - (flowOf.get(a.name) ?? 0))
          .slice(0, MAX_LABELS_WHEN_CROWDED)
          .map((n) => n.name),
      )
    : null;

  const option = {
    ...CHART_BASE,
    tooltip: {
      ...CHART_BASE.tooltip,
      formatter: (p: any) =>
        p.dataType === "edge"
          ? `₹${Number(p.data.value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}<br/>` +
            `${short(p.data.source)} → ${short(p.data.target)}`
          : `<b>${short(p.name)}</b>`,
    },
    series: [{
      type: "sankey",
      left: 18, right: 18, top: 18, bottom: 18,
      nodeWidth: 12,
      nodeGap: 10,
      emphasis: { focus: "adjacency" },
      label: {
        color: TEXT_DIM, fontSize: 10,
        formatter: (p: any) => (labeled && !labeled.has(p.name) ? "" : short(p.name)),
      },
      lineStyle: { curveness: 0.5 },
      itemStyle: { borderWidth: 0 },
      data: nodes.map((n) => ({
        name: n.name,
        itemStyle: { color: rgba(ACCENT, 0.6) },
      })),
      links: links.map((l) => ({
        ...l,
        lineStyle: { color: ramp((l.value ?? 0) / max), opacity: 0.42 },
      })),
    }],
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} notMerge />;
}

/** Account ids are UUIDs — showing 36 chars per node makes the diagram unreadable. */
function short(id: string): string {
  return typeof id === "string" && id.length > 12 ? `${id.slice(0, 8)}…` : id;
}
