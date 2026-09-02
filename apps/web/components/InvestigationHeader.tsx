"use client";
import { useEffect, useState } from "react";
import { getBoard } from "@/lib/api";
import { assetUrl } from "@/lib/asset";
import { useT } from "@/lib/i18n";
import type { CaseBoard, SessionFocusView, VizKind } from "@/lib/types";

export type WorkspaceView =
  | "overview" | "register" | "timeline" | "network" | "geography" | "financial"
  | "offenders" | "repeat_offenders" | "statistics" | "forecast" | "board"
  | "area" | "community" | "watchlist" | "workload";

/** Which workspace view a given answer's visualization belongs in. */
export const VIEW_FOR_VIZ: Partial<Record<VizKind, WorkspaceView>> = {
  network: "network",
  map: "geography",
  sankey: "financial",
  timeline: "timeline",
  trend: "forecast",
};

/** Where an answer belongs when it produced NO visualization.
 *
 *  A negative finding is still a finding about a domain: "no outbound transfer
 *  trail was found" is the financial answer, and leaving the workspace on the
 *  case register while the copilot says so is a discontinuity an officer reads
 *  as "the system ignored my question". Keyed on the evidence ids the engine
 *  already emits, so nothing new has to be sent to know this. */
export const VIEW_FOR_EVIDENCE: [RegExp, WorkspaceView][] = [
  [/^flow:/, "financial"],
  [/^aml:/, "financial"],
  [/^hotspot:/, "geography"],
  [/^(assoc|same_as):/, "network"],
  [/^timeline:/, "timeline"],
  [/^(board|lead):/, "board"],
  [/^(offender|ranking):/, "offenders"],
  [/^stats:/, "statistics"],
  [/^area:/, "area"],
  [/^community:/, "community"],
  [/^watchlist:/, "watchlist"],
  [/^(workload|stalled):/, "workload"],
];

const TABS: { key: WorkspaceView; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "register", label: "Case Register" },
  { key: "timeline", label: "Timeline" },
  { key: "network", label: "Network" },
  { key: "geography", label: "Hotspot Map" },
  { key: "financial", label: "Financial" },
  { key: "offenders", label: "Offenders" },
  { key: "repeat_offenders", label: "Repeat Offenders" },
  { key: "statistics", label: "Statistics" },
  { key: "forecast", label: "Forecast" },
  { key: "area", label: "Area Profile" },
  { key: "community", label: "Community" },
  { key: "watchlist", label: "Watchlist" },
  { key: "workload", label: "Workload" },
  { key: "board", label: "Board" },
];

const OPEN_STATUS = "Under Investigation";

/** The standing answer to "what am I investigating?".
 *
 *  A multi-turn investigation is unreadable without this. "Does she have
 *  priors?" answers about somebody, and before this existed the only thing on
 *  screen that said who was a line inside a reasoning trace that is collapsed by
 *  default. It is persistent, it is the first thing under the global bar, and it
 *  carries the workspace navigation — because every view below it is a view OF
 *  this investigation, not a separate destination.
 *
 *  The case facts and the board count come from one `GET /board/{fir}` call,
 *  which already returns fir_number, crime type, district, status and the item
 *  list. No new endpoint, and no count that isn't a real one: the metric strip
 *  shows what has actually been loaded, never an estimate. */
export default function InvestigationHeader({
  focus, view, onView, vizKind, citedCount, networkSize, boardVersion, scopeLabel,
}: {
  focus?: SessionFocusView;
  view: WorkspaceView;
  onView: (v: WorkspaceView) => void;
  vizKind: VizKind;
  citedCount: number;
  networkSize: number | null;
  boardVersion: number;
  scopeLabel: string;
}) {
  const t = useT();
  const firId = focus?.case?.fir_id ?? null;
  const [board, setBoard] = useState<CaseBoard | null>(null);

  useEffect(() => {
    if (!firId) { setBoard(null); return; }
    let live = true;
    getBoard(firId).then((b) => live && setBoard(b)).catch(() => live && setBoard(null));
    return () => { live = false; };
  }, [firId, boardVersion]);

  const person = focus?.person;
  const kase = focus?.case;
  const liveView = VIEW_FOR_VIZ[vizKind];

  // Prefer the board's own copy of the case facts — it reads them from the
  // record, where session focus only carries what the last turn resolved.
  const crime = board?.crime_type ?? kase?.crime_type;
  const district = board?.district ?? kase?.district;
  const status = board?.case_status;

  const kicker = kase ? t("Case under investigation") : person ? t("Person of interest") : t("Open investigation");
  const title = kase
    ? (board?.fir_number ?? kase.fir_number ?? `FIR ${kase.fir_id}`)
    : person
      ? (person.name ?? t("Person {id}", { id: person.person_id }))
      : t("Karnataka State Police — case register");

  return (
    <div className="investigation">
      <div className="inv-main">
        <img src={assetUrl("/ksp-logo.svg")} alt="" aria-hidden className="inv-crest" />
        <div className="inv-id">
          <div className="inv-kicker">
            <span>{kicker}</span>
            <span className="pill pill-neutral" title={t("Records visible at your rank")}>{scopeLabel}</span>
          </div>
          <h2 className={`inv-title ${kase ? "mono" : ""}`} title={title}>{title}</h2>
          <div className="inv-sub">
            {kase ? (
              <>
                {crime && <b>{crime}</b>}
                {crime && district ? " · " : ""}
                {district}
                {person && <>{t(" · also examining ")}<b>{person.name ?? t("person {id}", { id: person.person_id })}</b></>}
              </>
            ) : person ? (
              <>{t("Identity reconstructed from the case records by probabilistic record linkage.")}</>
            ) : (
              <>{t("Ask a question, or open a case from the register to begin.")}</>
            )}
          </div>
        </div>

        <div className="inv-metrics">
          {status && (
            <div className="inv-metric">
              <div className="inv-metric-n" style={{ fontSize: 13, paddingTop: 3 }}>
                <span className={`pill ${status === OPEN_STATUS ? "pill-open" : "pill-neutral"}`}>{t(status)}</span>
              </div>
              <div className="inv-metric-l">{t("Status")}</div>
            </div>
          )}
          {networkSize != null && (
            <div className="inv-metric">
              <div className="inv-metric-n">{networkSize}</div>
              <div className="inv-metric-l">{t("In network")}</div>
            </div>
          )}
          {citedCount > 0 && (
            <div className="inv-metric">
              <div className="inv-metric-n">{citedCount}</div>
              <div className="inv-metric-l">{t("Cited now")}</div>
            </div>
          )}
          {board && (
            <div className="inv-metric">
              <div className="inv-metric-n">{board.total}</div>
              <div className="inv-metric-l">{t("On board")}</div>
            </div>
          )}
        </div>
      </div>

      <nav className="inv-tabs" aria-label={t("Investigation views")}>
        {TABS.map((tab) => {
          const n = tab.key === "board" ? board?.total ?? null : null;
          return (
            <button
              key={tab.key}
              className={`inv-tab ${view === tab.key ? "on" : ""}`}
              onClick={() => onView(tab.key)}
              aria-current={view === tab.key ? "page" : undefined}
            >
              {t(tab.label)}
              {n ? <span className="inv-tab-n">{n}</span> : null}
              {/* A dot marks the view the current answer actually produced —
                  colour is never the only signal, so it is a shape, not a tint. */}
              {liveView === tab.key && view !== tab.key && (
                <span className="inv-tab-live" title={t("This view holds the current answer")} />
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
