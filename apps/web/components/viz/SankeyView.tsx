"use client";
import ReactECharts from "echarts-for-react";
import { CHART_BASE, ramp, rgba } from "./palette";

/** Money-flow Sankey. Deliberately distinct from the criminal-network view: a
 *  transfer has direction and magnitude, which a force graph cannot show. */
export default function SankeyView({ data }: { data: { nodes: { name: string }[]; links: any[] } }) {
  const links = data.links ?? [];
  const max = Math.max(1e-6, ...links.map((l) => l.value ?? 0));

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
      label: { color: "#c8d3ef", fontSize: 10, formatter: (p: any) => short(p.name) },
      lineStyle: { curveness: 0.5 },
      itemStyle: { borderWidth: 0 },
      data: (data.nodes ?? []).map((n) => ({
        name: n.name,
        itemStyle: { color: rgba("#2f6fed", 0.6) },
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
