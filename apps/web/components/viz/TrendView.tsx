"use client";
import ReactECharts from "echarts-for-react";
import { CHART_BASE, GRID, TEXT_FAINT, VIOLET, rgba } from "./palette";

type Point = [string, number, number, number]; // date, point, lower, upper

/** The forecast, with its interval.
 *
 *  The band is not decoration: a point estimate shown without its uncertainty is
 *  exactly the false precision this platform exists to avoid. The line is drawn
 *  in the console's MODEL colour, the same violet the evidence column uses for a
 *  model output, so a forecast never reads as something that was recorded. */
export default function TrendView({ data }: { data: { series: Point[] } }) {
  const s = data.series ?? [];
  const dates = s.map((p) => p[0]);
  const point = s.map((p) => p[1]);
  const lower = s.map((p) => p[2]);
  const upper = s.map((p) => p[3]);
  const spread = s.map((p) => Math.max(0, p[3] - p[2]));

  const option = {
    ...CHART_BASE,
    grid: { left: 48, right: 22, top: 30, bottom: 32 },
    tooltip: {
      ...CHART_BASE.tooltip,
      trigger: "axis",
      axisPointer: { lineStyle: { color: "#2a3746" } },
      formatter: (ps: any[]) => {
        const i = ps[0].dataIndex;
        return `<b>${dates[i]}</b><br/>${point[i].toFixed(1)} FIRs/day` +
               `<br/><span style="color:#64768a">interval ${s[i][2].toFixed(1)} – ${s[i][3].toFixed(1)}</span>`;
      },
    },
    xAxis: {
      type: "category", data: dates, boundaryGap: false,
      axisLine: { lineStyle: { color: GRID } },
      axisTick: { show: false },
      axisLabel: { color: TEXT_FAINT, fontSize: 10, formatter: (v: string) => v.slice(5) },
    },
    yAxis: {
      type: "value",
      name: "FIRs / day",
      nameTextStyle: { color: TEXT_FAINT, fontSize: 10, align: "left" },
      splitLine: { lineStyle: { color: GRID } },
      axisLabel: { color: TEXT_FAINT, fontSize: 10 },
    },
    series: [
      // A stacked transparent base plus a visible spread is how ECharts draws a
      // band. Fill alone was not enough: on a low-count forecast the interval is
      // genuinely wide, and a wide flat fill reads as a solid block rather than
      // as an uncertainty range. The two hairline edges are what make it read as
      // an interval — they are the numbers an officer would actually quote.
      { type: "line", stack: "band", data: lower, lineStyle: { opacity: 0 },
        symbol: "none", silent: true, smooth: true, areaStyle: { opacity: 0 } },
      { type: "line", stack: "band", data: spread, lineStyle: { opacity: 0 },
        symbol: "none", silent: true, smooth: true,
        areaStyle: { color: rgba(VIOLET, 0.11) } },
      { type: "line", data: lower, smooth: true, symbol: "none", silent: true,
        lineStyle: { color: rgba(VIOLET, 0.45), width: 1, type: "dashed" } },
      { type: "line", data: upper, smooth: true, symbol: "none", silent: true,
        lineStyle: { color: rgba(VIOLET, 0.45), width: 1, type: "dashed" } },
      { type: "line", data: point, smooth: true, symbol: "none",
        lineStyle: { color: VIOLET, width: 2.4 } },
    ],
  };

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <ReactECharts option={option} style={{ height: "100%", width: "100%" }} notMerge />
      <div className="viz-legend" style={{ left: "auto", right: 12, bottom: "auto", top: 12 }}>
        <span className="prov prov-model">Model</span>
        <div className="viz-legend-row">
          <span className="viz-legend-scale" style={{ height: 2, background: VIOLET }} />
          <span>forecast</span>
        </div>
        <div className="viz-legend-row">
          <span className="viz-legend-scale"
            style={{ height: 12, background: rgba(VIOLET, 0.11),
                     borderTop: `1px dashed ${rgba(VIOLET, 0.5)}`,
                     borderBottom: `1px dashed ${rgba(VIOLET, 0.5)}` }} />
          <span>confidence interval</span>
        </div>
      </div>
    </div>
  );
}
