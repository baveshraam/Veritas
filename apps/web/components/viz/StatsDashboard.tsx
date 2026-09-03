"use client";
import ReactECharts from "echarts-for-react";
import { useT } from "@/lib/i18n";
import type { Counted, Statistics } from "@/lib/api";
import { plural } from "@/lib/metrics";
import { GRID, LINE, PRIMARY, SURFACE, TEXT, TEXT_DIM, TEXT_FAINT, chartBase, rgba } from "./palette";

/** The Statistics tab as an actual analytics dashboard.
 *
 *  It used to be two sentences in an evidence list — the conviction rate and, on a
 *  good turn, one status breakdown — because the view was filled by asking the
 *  conversational engine a question, and a question returns one answer. A dashboard
 *  is not one answer; it is the shape of the whole case set at once, and it now comes
 *  from one scan of the records (`sql_agent.dashboard`, GET /analytics/statistics).
 *
 *  EVERY FIGURE HERE IS A COUNT OF RECORDS. Nothing on this surface is modelled,
 *  predicted or inferred, so nothing carries the MODEL or DERIVED provenance channel —
 *  the whole dashboard is one RECORD claim, stated once in the analysis header above
 *  it rather than repeated on nine tiles. The conviction rate is the one derived
 *  number, and it is printed with its own denominator beside it for exactly the reason
 *  CLAUDE.md §8 gives: a rate whose denominator is off screen is a number an officer
 *  cannot check.
 *
 *  Colour follows the console's own rule (viz/palette.ts): this is volume, not
 *  severity, so it uses the neutral analytical blue rather than the green->red ramp.
 *  A tall bar here means "more cases recorded", which is not the same claim as
 *  "more dangerous", and the severity ramp would assert the second one. */

const CHART_H = 208;
const RANK_MAX = 10;

/** "top 10" is false on a chart with three rows in it — and an IO's dashboard has
 *  exactly one district and one station, so the caption claimed a ranking that was
 *  not there. Says what is actually drawn. */
function topNote(total: number): string {
  return total > RANK_MAX ? `top ${RANK_MAX} of ${total}` : "all of them";
}

function Tile({ n, l, sub, tone }: { n: string; l: string; sub?: string; tone?: "pri" | "amber" | "ok" }) {
  return (
    <div className={`stat-tile ${tone ? `stat-tile-${tone}` : ""}`}>
      <div className="stat-tile-n">{n}</div>
      <div className="stat-tile-l">{l}</div>
      {sub && <div className="stat-tile-s">{sub}</div>}
    </div>
  );
}

function Panel({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="stat-panel">
      <div className="stat-panel-h">
        <span className="stat-panel-t">{title}</span>
        {note && <span className="stat-panel-n">{note}</span>}
      </div>
      {children}
    </div>
  );
}

/** A horizontal bar ranking. Horizontal because these categories are NAMES — a
 *  district, an offence, a station — and a rotated 45° axis label is a thing an
 *  officer has to tilt their head to read. */
function RankBars({ rows, max = 10, unit }: { rows: Counted[]; max?: number; unit: string }) {
  const t = useT();
  const top = rows.slice(0, max);
  const base = chartBase();
  const pri = PRIMARY();
  const faint = TEXT_FAINT();
  const option = {
    ...base,
    grid: { left: 4, right: 46, top: 6, bottom: 4, containLabel: true },
    tooltip: {
      ...base.tooltip, trigger: "item",
      formatter: (p: any) => `<b>${p.name}</b><br/>${p.value.toLocaleString()} ${unit}`,
    },
    xAxis: { type: "value", splitLine: { lineStyle: { color: GRID() } },
             axisLabel: { color: faint, fontSize: 10 } },
    // Reversed: ECharts draws a category axis bottom-up, so the largest value has
    // to be last in the array to render at the top where a ranking is read from.
    yAxis: {
      type: "category", data: top.map((r) => r.name).reverse(),
      axisLine: { lineStyle: { color: GRID() } }, axisTick: { show: false },
      axisLabel: { color: TEXT_DIM(), fontSize: 11, width: 118, overflow: "truncate" },
    },
    series: [{
      type: "bar", data: top.map((r) => r.cases).reverse(),
      barMaxWidth: 15,
      itemStyle: { color: pri, borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: "right", color: faint, fontSize: 10.5,
               formatter: (p: any) => p.value.toLocaleString() },
    }],
  };
  return <ReactECharts option={option} style={{ height: CHART_H }} notMerge
                       aria-label={t("Ranking chart")} />;
}

export default function StatsDashboard({ data, onAsk }: { data: Statistics; onAsk: (q: string) => void }) {
  const t = useT();
  const base = chartBase();
  const pri = PRIMARY();
  const faint = TEXT_FAINT();
  const grid = GRID();

  const conv = data.conviction;
  const pending = data.status.find((s) => /investigation/i.test(s.name))?.cases ?? 0;
  const chargesheeted = data.status.find((s) => /chargesheet/i.test(s.name))?.cases ?? 0;

  // Case volume over time. The x-axis is real recorded months, in order — the one
  // series on this page that must never be sorted by size.
  const months = data.monthly;
  const trend = {
    ...base,
    grid: { left: 8, right: 12, top: 12, bottom: 4, containLabel: true },
    tooltip: {
      ...base.tooltip, trigger: "axis",
      axisPointer: { lineStyle: { color: LINE() } },
      formatter: (ps: any[]) => `<b>${ps[0].name}</b><br/>${ps[0].value.toLocaleString()} ${t("cases registered")}`,
    },
    xAxis: {
      type: "category", data: months.map((m) => m.name), boundaryGap: false,
      axisLine: { lineStyle: { color: grid } }, axisTick: { show: false },
      axisLabel: { color: faint, fontSize: 10,
                   // Every third month, so a three-year window stays readable
                   // without rotating a single label.
                   interval: Math.max(0, Math.floor(months.length / 12)) },
    },
    yAxis: {
      type: "value", splitLine: { lineStyle: { color: grid } },
      axisLabel: { color: faint, fontSize: 10 },
    },
    series: [{
      type: "line", data: months.map((m) => m.cases), smooth: 0.25, symbol: "none",
      lineStyle: { color: pri, width: 2 },
      areaStyle: { color: rgba(pri, 0.12) },
    }],
  };

  // Status mix. A donut rather than a pie: the hole is where the total goes, and
  // a share is only meaningful next to the number it is a share of.
  const statusTones = ["#1f6ed0", "#1c7a4c", "#9c6410", "#b8362e", "#574bb0", "#6a7787"];
  const donut = {
    ...base,
    tooltip: {
      ...base.tooltip, trigger: "item",
      formatter: (p: any) => `<b>${p.name}</b><br/>${p.value.toLocaleString()} ${t("cases")} · ${p.percent}%`,
    },
    legend: {
      orient: "vertical", right: 0, top: "middle", itemWidth: 9, itemHeight: 9,
      icon: "roundRect", textStyle: { color: TEXT_DIM(), fontSize: 11 },
    },
    series: [{
      type: "pie", radius: ["52%", "76%"], center: ["32%", "50%"], avoidLabelOverlap: true,
      itemStyle: { borderColor: SURFACE(), borderWidth: 2 },
      label: { show: false }, labelLine: { show: false },
      data: data.status.map((s, i) => ({
        name: s.name, value: s.cases,
        itemStyle: { color: statusTones[i % statusTones.length] },
      })),
    }],
  };

  return (
    <div className="stat-dash">
      <div className="stat-tiles">
        <Tile n={data.total.toLocaleString()} l={t("cases on record")}
              sub={t("within your access scope")} />
        <Tile tone="ok"
              n={conv.rate === null ? "—" : `${Math.round(conv.rate * 100)}%`}
              l={t("conviction rate")}
              sub={conv.rate === null
                ? t("no case has reached a verdict")
                : t("{c} of {d} that reached a verdict", { c: conv.convicted.toLocaleString(), d: conv.decided.toLocaleString() })} />
        <Tile tone="amber" n={pending.toLocaleString()} l={t("under investigation")}
              sub={t("no outcome recorded yet")} />
        <Tile n={chargesheeted.toLocaleString()} l={t("chargesheeted")}
              sub={t("filed, awaiting trial")} />
        <Tile n={String(data.district.length)} l={t("districts")}
              sub={plural(data.station.length, "police station", undefined, t)} />
      </div>

      <div className="stat-grid">
        <Panel title={t("Case volume over time")}
               note={t("{n} months of recorded registrations", { n: months.length })}>
          <ReactECharts option={trend} style={{ height: CHART_H }} notMerge />
        </Panel>

        <Panel title={t("Where each case stands")} note={t("as recorded")}>
          <ReactECharts option={donut} style={{ height: CHART_H }} notMerge />
        </Panel>

        <Panel title={t("Offence types")} note={t("most frequent first")}>
          <RankBars rows={data.crime_type} unit={t("cases")} />
        </Panel>

        <Panel title={t("Districts by case volume")} note={topNote(data.district.length)}>
          <RankBars rows={data.district} unit={t("cases")} />
        </Panel>

        <Panel title={t("Busiest police stations")} note={topNote(data.station.length)}>
          <RankBars rows={data.station} unit={t("cases")} />
        </Panel>

        <Panel title={t("Ask about any of this")}
               note={t("the same records, questioned")}>
          <div className="stat-asks">
            {[
              "What is the conviction rate in Bengaluru Urban?",
              "Which station has the most pending cases?",
              "Which district has the most theft cases?",
              "Who are the top 20 most active offenders?",
              "Show me crime hotspots",
            ].map((q) => (
              <button key={q} className="btn btn-sm" onClick={() => onAsk(q)}>{t(q)}</button>
            ))}
          </div>
          <p className="stat-foot">
            {t("Every figure above is a count of records within your access scope — a different rank sees a different denominator. Nothing here is modelled or predicted.")}
          </p>
        </Panel>
      </div>
    </div>
  );
}
