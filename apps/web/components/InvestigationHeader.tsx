"use client";
import { useEffect, useState } from "react";
import { getBoard } from "@/lib/api";
import type { CaseBoard, SessionFocusView, VizKind } from "@/lib/types";

export type WorkspaceView =
  | "overview" | "timeline" | "network" | "geography" | "financial" | "board";

/** Which workspace view a given answer's visualization belongs in. Trend has no
 *  tab of its own: a district forecast is not a facet of one case, so it lands
 *  in Overview alongside the case index. */
export const VIEW_FOR_VIZ: Partial<Record<VizKind, WorkspaceView>> = {
  network: "network",
  map: "geography",
  sankey: "financial",
  timeline: "timeline",
  trend: "overview",
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
];

const TABS: { key: WorkspaceView; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "timeline", label: "Timeline" },
  { key: "network", label: "Network" },
  { key: "geography", label: "Geography" },
  { key: "financial", label: "Financial" },
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

  const kicker = kase ? "Case under investigation" : person ? "Person of interest" : "Open investigation";
  const title = kase
    ? (board?.fir_number ?? kase.fir_number ?? `FIR ${kase.fir_id}`)
    : person
      ? (person.name ?? `Person ${person.person_id}`)
      : "Karnataka State Police — case register";

  return (
    <div className="investigation">
      <div className="inv-main">
        <div className="inv-id">
          <div className="inv-kicker">
            <span>{kicker}</span>
            <span className="pill pill-neutral" title="Records visible at your rank">{scopeLabel}</span>
          </div>
          <h2 className={`inv-title ${kase ? "mono" : ""}`} title={title}>{title}</h2>
          <div className="inv-sub">
            {kase ? (
              <>
                {crime && <b>{crime}</b>}
                {crime && district ? " · " : ""}
                {district}
                {person && <> · also examining <b>{person.name ?? `person ${person.person_id}`}</b></>}
              </>
            ) : person ? (
              <>Identity reconstructed from the case records by probabilistic record linkage.</>
            ) : (
              <>Ask a question, or open a case from the register to begin.</>
            )}
          </div>
        </div>

        <div className="inv-metrics">
          {status && (
            <div className="inv-metric">
              <div className="inv-metric-n" style={{ fontSize: 13, paddingTop: 3 }}>
                <span className={`pill ${status === OPEN_STATUS ? "pill-open" : "pill-neutral"}`}>{status}</span>
              </div>
              <div className="inv-metric-l">Status</div>
            </div>
          )}
          {networkSize != null && (
            <div className="inv-metric">
              <div className="inv-metric-n">{networkSize}</div>
              <div className="inv-metric-l">In network</div>
            </div>
          )}
          {citedCount > 0 && (
            <div className="inv-metric">
              <div className="inv-metric-n">{citedCount}</div>
              <div className="inv-metric-l">Cited now</div>
            </div>
          )}
          {board && (
            <div className="inv-metric">
              <div className="inv-metric-n">{board.total}</div>
              <div className="inv-metric-l">On board</div>
            </div>
          )}
        </div>
      </div>

      <nav className="inv-tabs" aria-label="Investigation views">
        {TABS.map((t) => {
          const n = t.key === "board" ? board?.total ?? null : null;
          return (
            <button
              key={t.key}
              className={`inv-tab ${view === t.key ? "on" : ""}`}
              onClick={() => onView(t.key)}
              aria-current={view === t.key ? "page" : undefined}
            >
              {t.label}
              {n ? <span className="inv-tab-n">{n}</span> : null}
              {/* A dot marks the view the current answer actually produced —
                  colour is never the only signal, so it is a shape, not a tint. */}
              {liveView === t.key && view !== t.key && (
                <span className="inv-tab-live" title="This view holds the current answer" />
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
