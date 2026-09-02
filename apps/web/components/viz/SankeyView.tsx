"use client";
import ReactECharts from "echarts-for-react";
import { useT } from "@/lib/i18n";
import { PRIMARY, TEXT_DIM, TEXT_FAINT, chartBase, ramp, rgba, sevGradient } from "./palette";

/** The money trail.
 *
 *  Deliberately distinct from the network graph: a transfer has direction and
 *  magnitude, which a force layout cannot show. Left is where money came from,
 *  right is where it went, and that is never reversed — reversing it would
 *  invent a payment that never happened.
 *
 *  Flow colour is the SEVERITY ramp here, and that is the correct scale: a large
 *  transfer in a laundering trail genuinely is the thing to look at first. */

// Above this many nodes on one side, every label at a fixed row height stops
// fitting the chart's height without overlapping (measured live: a 60-account
// trail became unreadable). Rather than shrink text past legibility, only the
// highest-value nodes keep a label — every node stays hoverable, so nothing is
// lost, just decluttered.
const LABEL_ALL_BELOW = 25;
const MAX_LABELS_WHEN_CROWDED = 20;

export default function SankeyView({ data }: { data: { nodes: { name: string }[]; links: any[] } }) {
  const t = useT();
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

  const base = chartBase();
  const faint = TEXT_FAINT();

  const option = {
    ...base,
    tooltip: {
      ...base.tooltip,
      formatter: (p: any) =>
        p.dataType === "edge"
          ? `<b>₹${Number(p.data.value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</b><br/>` +
            `<span style="color:${faint}">${short(p.data.source)} → ${short(p.data.target)}</span>`
          : `<b>${short(p.name)}</b><br/><span style="color:${faint}">₹${Math.round(flowOf.get(p.name) ?? 0).toLocaleString("en-IN")} through this account</span>`,
    },
    series: [{
      type: "sankey",
      left: 16, right: 16, top: 16, bottom: 16,
      nodeWidth: 10,
      nodeGap: 10,
      emphasis: { focus: "adjacency" },
      label: {
        color: TEXT_DIM(), fontSize: 10,
        fontFamily: "var(--font-mono), ui-monospace, monospace",
        formatter: (p: any) => (labeled && !labeled.has(p.name) ? "" : short(p.name)),
      },
      lineStyle: { curveness: 0.5 },
      itemStyle: { borderWidth: 0 },
      data: nodes.map((n) => ({ name: n.name, itemStyle: { color: rgba(PRIMARY(), 0.75) } })),
      links: links.map((l) => ({
        ...l,
        lineStyle: { color: ramp((l.value ?? 0) / max), opacity: 0.38 },
      })),
    }],
  };

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <ReactECharts option={option} style={{ height: "100%", width: "100%" }} notMerge />
      <div className="viz-legend">
        <span className="label">{t("Transfer size")}</span>
        <div className="viz-legend-row">
          <span className="viz-legend-scale"
            style={{ background: sevGradient() }} />
          <span>{t("smaller → larger")}</span>
        </div>
        <span className="meta">{t("Left to right is the direction of payment.")}</span>
      </div>
    </div>
  );
}

/** Account ids are UUIDs — 36 characters per node makes the diagram unreadable. */
function short(id: string): string {
  return typeof id === "string" && id.length > 12 ? `${id.slice(0, 8)}…` : id;
}
