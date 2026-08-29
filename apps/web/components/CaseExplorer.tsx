"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { listCases } from "@/lib/api";
import type { CaseIndex, CaseRow } from "@/lib/types";

/** The case register — what the workspace shows before anything has been asked.
 *
 *  A conversational console that opens on an empty prompt asks the officer to
 *  guess what the system knows. This is the answer to "what is in here": every
 *  case they are cleared to see, searchable and faceted. A case is not a dead
 *  end — opening one hands the copilot a real, specific question about it, so
 *  browsing turns into asking without anyone inventing a phrasing.
 *
 *  Rows, not cards. Ten cases with three buttons each is thirty controls
 *  competing on one screen; the register is a list an officer scans, and the
 *  actions belong to the row under the cursor. */

/** Case status is NOT severity and must never borrow the severity ramp.
 *
 *  It used to: "Under Investigation" rendered in the same crimson as a
 *  high-risk hotspot, so the most ordinary state a case can be in read as an
 *  alarm. Status is neutral now, carrying one honest bit — whether it is open. */
const OPEN_STATUS = "Under Investigation";

function fmt(d: string): string {
  const t = new Date(d);
  return isNaN(t.getTime()) ? d.slice(0, 10)
    : t.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

/** Phrased to hit the FIR_LOOKUP intent: "fir" plus "status of", and no word
 *  that scores for CRIME_SEARCH (show / list / cases). */
export const askAbout = (c: CaseRow) => `What is the status of FIR ${c.fir_number}?`;

export default function CaseExplorer({
  onAsk, onCopilot, onBoard, activeFir,
}: {
  onAsk: (q: string) => void;
  onCopilot: (firId: string) => void;
  onBoard: (firId: string) => void;
  activeFir?: string | null;
}) {
  const [q, setQ] = useState("");
  const [crimeType, setCrimeType] = useState<string | null>(null);
  const [caseStatus, setCaseStatus] = useState<string | null>(null);
  const [idx, setIdx] = useState<CaseIndex | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Debounced so typing a district name doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      listCases({
        q: q.trim() || undefined,
        crime_type: crimeType ?? undefined,
        case_status: caseStatus ?? undefined,
      })
        .then((i) => { setIdx(i); setError(null); })
        .catch((e) => setError(e.message));
    }, 220);
    return () => clearTimeout(t);
  }, [q, crimeType, caseStatus]);

  const districts = useMemo(
    () => new Set((idx?.cases ?? []).map((c) => c.district)).size,
    [idx],
  );
  // Most result sets record no modus operandi at all. Reserving a column for it
  // regardless squeezed the location line into wrapping onto two rows next to
  // an empty third of the table.
  const anyMo = useMemo(() => (idx?.cases ?? []).some((c) => !!c.modus_operandi), [idx]);

  // The case the conversation is about should be visible in the register without
  // the officer hunting for the highlighted row.
  const rowsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!activeFir) return;
    rowsRef.current?.querySelector<HTMLElement>(".case-row.on")
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeFir, idx]);

  const toggle = (cur: string | null, v: string) => (cur === v ? null : v);

  return (
    <div className="index">
      <div className="index-controls">
        <div className="index-search">
          <input
            className="field"
            value={q}
            placeholder="Search by FIR number, crime, district or method…"
            aria-label="Search the case register"
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {idx && (
          <>
            <div className="facet-group">
              <span className="label">Crime</span>
              {idx.crime_types.slice(0, 7).map((f) => (
                <button key={f.name} className={`facet ${crimeType === f.name ? "on" : ""}`}
                  aria-pressed={crimeType === f.name}
                  onClick={() => setCrimeType((c) => toggle(c, f.name))}>
                  {f.name}<span className="facet-n">{f.count}</span>
                </button>
              ))}
            </div>
            <div className="facet-group">
              <span className="label">Status</span>
              {idx.statuses.map((f) => (
                <button key={f.name} className={`facet ${caseStatus === f.name ? "on" : ""}`}
                  aria-pressed={caseStatus === f.name}
                  onClick={() => setCaseStatus((c) => toggle(c, f.name))}>
                  {f.name}<span className="facet-n">{f.count}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <div className={`index-rows ${anyMo ? "" : "no-mo"}`} ref={rowsRef}>
        {error && (
          <div className="empty">
            <span className="empty-mark" aria-hidden>!</span>
            <h3>The case register could not be loaded</h3>
            <p>{error}</p>
          </div>
        )}
        {!idx && !error && (
          <div className="empty"><span className="spinner" /><p>Loading the register…</p></div>
        )}
        {idx?.cases.map((c) => (
          <div
            key={c.fir_id}
            className={`case-row ${activeFir === c.fir_id ? "on" : ""}`}
            role="button"
            tabIndex={0}
            onClick={() => onAsk(askAbout(c))}
            onKeyDown={(e) => { if (e.key === "Enter") onAsk(askAbout(c)); }}
            aria-label={`Open case ${c.fir_number}`}
          >
            <span className="case-no">{c.fir_number}</span>
            <div className="case-primary">
              <div className="case-type">{c.crime_type}</div>
              <div className="case-where">
                {c.district} · PS {c.ps_code} · {fmt(c.date_filed)}
                {c.ipc_sections?.length ? ` · IPC ${c.ipc_sections.join(", ")}` : ""}
              </div>
            </div>
            <div className="case-mo">{c.modus_operandi ?? ""}</div>
            <div className="case-end">
              <div className="case-acts">
                <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); onCopilot(c.fir_id); }}>
                  Briefing
                </button>
                <button className="btn btn-sm" onClick={(e) => {
                  e.stopPropagation();
                  // Opening the board straight from the register leaves the session
                  // with no open case, so the board's own note and lead forms — which
                  // run through the copilot — would refuse with "no case is open".
                  // Asking about the case first is also what an investigator does.
                  onAsk(askAbout(c));
                  onBoard(c.fir_id);
                }}>
                  Board
                </button>
              </div>
              <span className={`pill ${c.case_status === OPEN_STATUS ? "pill-open" : "pill-neutral"}`}>
                {c.case_status}
              </span>
            </div>
          </div>
        ))}
        {idx && !idx.cases.length && (
          <div className="empty">
            <span className="empty-mark" aria-hidden>⌕</span>
            <h3>No case matches that filter</h3>
            <p>Clear a facet, or search a different FIR number, district or method.</p>
          </div>
        )}
      </div>

      {idx && (
        <div className="index-foot">
          <span>
            {idx.matched > idx.cases.length
              ? `Showing ${idx.cases.length} of ${idx.matched.toLocaleString("en-IN")} matching cases`
              : `${idx.cases.length} ${idx.cases.length === 1 ? "case" : "cases"}`}
            {" · "}{districts} {districts === 1 ? "district" : "districts"}
          </span>
          <span>{idx.total.toLocaleString("en-IN")} visible at your rank</span>
        </div>
      )}
    </div>
  );
}
