"use client";
import ReactECharts from "echarts-for-react";
import { CHART_BASE, ACCENT, GRID, rgba } from "./palette";

type Point = [string, number, number, number]; // date, point, lower, upper

/** Forecast with its confidence band. The band is not decoration: a point estimate
 *  shown without its uncertainty is exactly the kind of false precision this
 *  platform is supposed to avoid (Layer 10). */
export default function TrendView({ data }: { data: { series: Point[] } }) {
  const s = data.series ?? [];
  const dates = s.map((p) => p[0]);
  const point = s.map((p) => p[1]);
  const lower = s.map((p) => p[2]);
  const spread = s.map((p) => Math.max(0, p[3] - p[2]));

  const option = {
    ...CHART_BASE,
    grid: { left: 46, right: 20, top: 26, bottom: 34 },
    tooltip: {
      ...CHART_BASE.tooltip,
      trigger: "axis",
      formatter: (ps: any[]) => {
        const i = ps[0].dataIndex;
        return `<b>${dates[i]}</b><br/>forecast ${point[i].toFixed(1)}` +
               `<br/><span style="color:#93a0c2">range ${s[i][2].toFixed(1)} – ${s[i][3].toFixed(1)}</span>`;
      },
    },
    xAxis: {
      type: "category", data: dates, boundaryGap: false,
      axisLine: { lineStyle: { color: GRID } },
      axisLabel: { color: "#64708f", fontSize: 10, formatter: (v: string) => v.slice(5) },
    },
    yAxis: {
      type: "value", name: "FIRs/day", nameTextStyle: { color: "#64708f", fontSize: 10 },
      splitLine: { lineStyle: { color: GRID } },
      axisLabel: { color: "#64708f", fontSize: 10 },
    },
    series: [
      // stacked transparent base + visible spread = the confidence band
      { type: "line", stack: "band", data: lower, lineStyle: { opacity: 0 },
        symbol: "none", silent: true, areaStyle: { opacity: 0 } },
      { type: "line", stack: "band", data: spread, lineStyle: { opacity: 0 },
        symbol: "none", silent: true,
        areaStyle: { color: rgba(ACCENT, 0.14) } },
      { type: "line", data: point, smooth: true, symbol: "none",
        lineStyle: { color: ACCENT, width: 2.2, shadowBlur: 12, shadowColor: rgba(ACCENT, 0.5) } },
    ],
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} notMerge />;
}
