"use client";
import { useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import WhyChain from "../WhyChain";
import { useT } from "@/lib/i18n";
import { influenceReading } from "@/lib/metrics";
import { isRoot, type NetworkReading } from "@/lib/network";
import {
  ACCENT, LABEL_PLATE, LINE, PRIMARY, TEXT, TEXT_DIM, TEXT_FAINT,
  chartBase, influence, influenceGradient, rgba,
} from "./palette";

/** As the engine sends it: ids are numbers for a case's accused list and
 *  strings elsewhere. Normalised to strings at the top of the component. */
type RawNode = { id: string | number; label: string; pagerank: number };
type RawEdge = { source: string | number; target: string | number; type: string; strength: number };
type Node = { id: string; label: string; pagerank: number };

const MAX_STATIC_LABELS = 12;

/** The co-offending network.
 *
 *  Three things this view is careful not to say. It does not colour influence on
 *  the severity ramp — PageRank measures how connected somebody is inside this
 *  graph, and painting that in crimson would assert a threat score the platform
 *  does not compute (see palette.ts). It never calls a Louvain community a gang:
 *  the records document no gang, so a grouping is labelled as what it is. And it
 *  never lets a person reached through a chain of shared cases render
 *  identically to a person the case file actually names — the graph draws two
 *  populations and says which is which, in the legend and on the node.
 *
 *  Selection is progressive disclosure: clicking a person dims the rest of the
 *  graph to their immediate neighbourhood and opens a small inspector, so a
 *  twenty-node network can be read one person at a time instead of all at once.
 */
export default function NetworkView({
  data, onAsk, subjectLabel, reading, sessionId,
}: {
  data: { nodes: RawNode[]; edges: RawEdge[] };
  onAsk?: (q: string) => void;
  /** Lets a selected node ask the server why it is connected — the same
   *  GET /explain the evidence inspector uses, so a click and a typed "why is
   *  this person connected?" cannot give two different accounts. */
  sessionId?: string;
  /** The person the network was drawn around. The engine labels that node
   *  "subject", which is a placeholder, not a name — and the one node an
   *  officer most needs to identify should not be the only unlabelled one. */
  subjectLabel?: string | null;
  /** Who is named in the record and who was reached through shared cases. */
  reading?: NetworkReading | null;
}) {
  const t = useT();
  // The engine sends node ids as numbers and edge endpoints as numbers, while
  // every id this component joins against (evidence ids, the selection, the
  // label set) is a string. Normalise once, here, rather than at each comparison
  // — a missed String() reads as "that person simply is not in the graph".
  const nodes = useMemo(
    () => (data.nodes ?? []).map((n) => ({ ...n, id: String(n.id) })),
    [data],
  );
  const edges = useMemo(
    () => (data.edges ?? []).map((e) => ({ ...e, source: String(e.source), target: String(e.target) })),
    [data],
  );
  const [selected, setSelected] = useState<string | null>(null);
  // The derivation panel is collapsed by default and resets on every new
  // selection: a chain left open from the previous person would be read as
  // this one's, which is exactly the misattribution the panel exists to stop.
  const [why, setWhy] = useState(false);

  const directIds = useMemo(
    () => new Set((reading?.direct ?? []).map((c) => c.id)),
    [reading],
  );
  // A square is the console's RECORD glyph. It is earned only when the case file
  // actually names these people; a direct co-offender is a derived finding and
  // gets the derived treatment however close to the subject they are.
  const named = reading?.basis === "record";

  // The engine gives the ROOT node a pagerank of exactly 1.0 as a display-sizing
  // sentinel (synthesis_agent.py says so) — it is not a measured centrality. Left
  // in the normalisation it sets the scale single-handedly, so every genuinely
  // measured value (0.003-0.01 in a real co-offending network) collapses to the
  // bottom of the ramp and twenty distinguishable associates render as twenty
  // identical grey dots. Scale on the real values; size the subject explicitly.
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
    // Force-labelling every direct connection is what made a 40-node graph
    // unreadable — the cap has to hold whatever the reason for the label is.
    ...(named ? [...directIds].slice(0, MAX_STATIC_LABELS) : []),
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
  const selReading = sel && !isRoot(sel)
    ? influenceReading(Math.min(1, (sel.pagerank ?? 0) / max), sel.pagerank ?? 0)
    : null;

  const base = chartBase();
  const accent = ACCENT();
  const primary = PRIMARY();
  const faint = TEXT_FAINT();
  const line = LINE();

  const option = {
    ...base,
    tooltip: {
      ...base.tooltip,
      formatter: (p: any) =>
        p.dataType === "node"
          ? `<b>${p.data.name}</b><br/><span style="color:${faint}">${p.data.role}</span>`
          : `${p.data.rel ?? "linked"}`,
    },
    series: [{
      type: "graph",
      layout: "force",
      roam: true,
      draggable: true,
      force: { repulsion: 300, edgeLength: [70, 190], gravity: 0.06 },
      label: {
        show: true, position: "right", color: TEXT_DIM(), fontSize: 11,
        // A backing plate keeps a label legible where the force layout cannot
        // fully separate two nodes' text.
        backgroundColor: LABEL_PLATE(), padding: [1, 4], borderRadius: 3,
        formatter: (p: any) => (alwaysLabeled.has(p.data.id) ? p.data.name : ""),
      },
      emphasis: { focus: "adjacency", label: { show: true } },
      lineStyle: { color: line, opacity: 0.55, curveness: 0.1, width: 1 },
      data: nodes.map((n) => {
        const root = isRoot(n);
        const direct = directIds.has(n.id);
        const frac = root ? 1 : Math.min(1, (n.pagerank ?? 0) / max);
        const isSel = n.id === selected;
        const dim = !!neighbours && !neighbours.has(n.id);
        return {
          id: n.id,
          name: displayName(n),
          value: n.pagerank ?? 0,
          role: root ? t("subject of this search")
              : direct && named ? t("named in the case records")
              : direct ? t("offended alongside the subject")
              : t("{headline} — reached through shared cases", { headline: t(influenceReading(frac, n.pagerank ?? 0).headline) }),
          // A person the record names is a SQUARE, the same shape the console's
          // "Record" provenance glyph uses; everyone else is a circle. The
          // distinction survives colour-blindness and a greyscale printout,
          // which a hue alone would not.
          symbol: root || (direct && named) ? "rect" : "circle",
          symbolSize: root ? 28 : direct && named ? 14 + frac * 12 : 10 + frac * 15,
          itemStyle: {
            color: isSel ? accent : root ? primary : direct && named ? rgba(primary, 0.85) : influence(frac),
            opacity: dim ? 0.16 : 1,
            borderColor: isSel ? accent : root ? primary : rgba(TEXT(), 0.25),
            borderWidth: isSel ? 2.5 : root ? 3 : 1,
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
            opacity: dim ? 0.06 : 0.45,
            color: neighbours && !dim ? accent : line,
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
            setWhy(false);
            if (p.dataType === "node") setSelected((s) => (s === p.data.id ? null : p.data.id));
            else setSelected(null);
          },
        }}
      />

      {sel && (
        <div className={`node-card${why ? " node-card-wide" : ""}`}>
          <div className="node-card-name">{displayName(sel)}</div>
          <div className="meta" style={{ marginTop: 2 }}>
            {t(isRoot(sel) ? "Subject of this search"
              : directIds.has(sel.id) && named ? "Named in the case records"
              : directIds.has(sel.id) ? "Offended alongside the subject on a shared case"
              : "Reached through a chain of shared cases — not accused in this case")}
          </div>
          <div className="node-card-rows">
            <div className="node-card-row"><span>{t("Connections in view")}</span><b>{selDegree}</b></div>
            {selHops != null && !isRoot(sel) && (
              <div className="node-card-row">
                <span>{t("Distance")}</span><b>{t("{n} step(s)", { n: selHops })}</b>
              </div>
            )}
            {selReading && (
              <div className="node-card-row node-card-read">
                <span>{t(selReading.headline)}</span>
                <b>{selReading.measure.replace("Network influence · ", "")}</b>
              </div>
            )}
          </div>
          {/* WHY is this person connected — the derivation, not the hop count the
              row above already prints. A node reached through a chain of shared
              cases is the single most consequential derived claim on this screen,
              and it was the one thing a click could not interrogate. */}
          {why && !isRoot(sel) && (
            <div className="probe-body" style={{ marginBottom: 10 }}>
              {/* Which claim this node makes depends on which population it is in.
                  A person the case FILE names is an `accused:` record — the answer is
                  the Accused row and the identity match behind the canonical name. A
                  person reached through shared cases is an `assoc:` derivation — the
                  answer is the chain of FIRs. Asking the wrong one would explain the
                  wrong claim, which is the exact confusion this graph already works
                  to prevent. */}
              <WhyChain
                evidenceId={`${named && directIds.has(sel.id) ? "accused" : "assoc"}:${sel.id}`}
                sessionId={sessionId}
                onAsk={onAsk}
              />
            </div>
          )}

          <div className="probe-acts">
            {!isRoot(sel) && (
              <button className="btn btn-sm" onClick={() => setWhy((v) => !v)} aria-expanded={why}>
                {t(why ? "Hide chain" : "Why connected?")}
              </button>
            )}
            {onAsk && !isRoot(sel) && (
              <>
                <button className="btn btn-sm" onClick={() => onAsk(`Does ${sel.label} have priors?`)}>
                  {t("Priors")}
                </button>
                <button className="btn btn-sm"
                  onClick={() => onAsk(`Show me the timeline for ${sel.label}.`)}>
                  {t("Timeline")}
                </button>
                <button className="btn btn-sm"
                  onClick={() => onAsk(`Where did ${sel.label}'s money go?`)}>
                  {t("Trace money")}
                </button>
              </>
            )}
            <button className="btn btn-sm btn-quiet" onClick={() => setSelected(null)}>{t("Clear")}</button>
          </div>
        </div>
      )}

      <div className="viz-legend">
        {named && (
          <div className="viz-legend-row">
            <span className="viz-legend-scale"
              style={{ width: 10, height: 10, background: primary }} />
            <span>{t("Named in the records")}</span>
            <span className="prov prov-record" style={{ marginLeft: "auto" }}>{t("Record")}</span>
          </div>
        )}
        {(!named || (reading?.extended.length ?? 0) > 0) && (
          <div className="viz-legend-row">
            <span className="viz-legend-scale"
              style={{ width: 10, height: 10, borderRadius: "50%", background: influence(0.7) }} />
            <span>{t(named ? "Reached through shared cases" : "Connected through shared cases")}</span>
            <span className="prov prov-derived" style={{ marginLeft: "auto" }}>{t("Derived")}</span>
          </div>
        )}
        <div className="viz-legend-row">
          <span className="viz-legend-scale" style={{ background: influenceGradient() }} />
          <span>{t("peripheral → central")}</span>
        </div>
        <span className="meta" style={{ maxWidth: 210 }}>
          {t("Connectedness within this graph — not a risk score, and not an accusation.")}
        </span>
      </div>
    </div>
  );
}
