"use client";
import { useEffect, useMemo, useState } from "react";
import { listCases } from "@/lib/api";
import type { CaseIndex, CaseRow } from "@/lib/types";

/** The case index — what the console shows before you have asked anything.
 *
 * A conversational console that opens on an empty prompt asks the officer to guess
 * what the system knows. This is the answer to "what is in here": every FIR they are
 * cleared to see, searchable, faceted by crime type and status. A case is not a
 * dead-end card — each one hands the chat a real, specific question about itself, so
 * browsing turns into asking without anyone having to invent a phrasing.
 */

// The four case_status values the record layer actually emits. Unknown -> "med",
// so a new status shows up as neutral rather than silently reading as resolved.
const STATUS_SEV: Record<string, string> = {
  Convicted: "low",
  Acquitted: "low",
  Chargesheeted: "med",
  "Under Investigation": "high",
};

function fmt(d: string): string {
  return new Date(d).toLocaleDateString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
  });
}

export default function CaseExplorer({
  onAsk,
  onCopilot,
}: {
  onAsk: (q: string) => void;
  onCopilot: (firId: string) => void;
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

  if (error) return <div className="viz-empty">{error}</div>;
  if (!idx) return <div className="viz-empty"><span className="spinner" /></div>;

  const toggle = (cur: string | null, v: string) => (cur === v ? null : v);

  return (
    <div className="explorer">
      <div className="stat-row">
        <div className="stat">
          <div className="stat-n">{idx.total.toLocaleString("en-IN")}</div>
          <div className="stat-l">cases you can see</div>
        </div>
        <div className="stat">
          <div className="stat-n">{idx.crime_types.length}</div>
          <div className="stat-l">crime types</div>
        </div>
        <div className="stat">
          <div className="stat-n">{districts}</div>
          <div className="stat-l">districts shown</div>
        </div>
      </div>

      <input
        className="search"
        value={q}
        placeholder="Search FIR number, crime, district, modus operandi…"
        onChange={(e) => setQ(e.target.value)}
      />

      <div className="facets">
        {idx.crime_types.slice(0, 8).map((f) => (
          <button
            key={f.name}
            className={`tab ${crimeType === f.name ? "on" : ""}`}
            onClick={() => setCrimeType((c) => toggle(c, f.name))}
          >
            {f.name} <span className="facet-n">{f.count}</span>
          </button>
        ))}
        {idx.statuses.map((f) => (
          <button
            key={f.name}
            className={`tab ${caseStatus === f.name ? "on" : ""}`}
            onClick={() => setCaseStatus((c) => toggle(c, f.name))}
          >
            {f.name} <span className="facet-n">{f.count}</span>
          </button>
        ))}
      </div>

      <div className="case-grid">
        {idx.cases.map((c: CaseRow) => (
          <div className="case" key={c.fir_id}>
            <div className="case-head">
              <span className="case-no">{c.fir_number}</span>
              <span className={`chip chip-${STATUS_SEV[c.case_status] ?? "med"}`}>
                {c.case_status}
              </span>
            </div>
            <div className="case-type">{c.crime_type}</div>
            <div className="case-meta">
              {c.district} · {c.ps_code} · {fmt(c.date_filed)}
              {c.ipc_sections?.length ? ` · IPC ${c.ipc_sections.join(", ")}` : ""}
            </div>
            {c.modus_operandi && <div className="case-mo">{c.modus_operandi}</div>}
            <div className="case-acts">
              <button
                className="btn btn-sm"
                onClick={() =>
                  // phrased to hit the FIR_LOOKUP intent: "fir" + "status of",
                  // and no word that scores for CRIME_SEARCH (show/list/cases)
                  onAsk(`What is the status of FIR ${c.fir_number}?`)
                }
              >
                Ask about this case
              </button>
              <button className="btn btn-sm" onClick={() => onCopilot(c.fir_id)}>
                Copilot brief
              </button>
            </div>
          </div>
        ))}
        {!idx.cases.length && (
          <div className="dim">No case matches that filter.</div>
        )}
      </div>

      {idx.matched > idx.cases.length && (
        <div className="dim" style={{ textAlign: "center", padding: "8px 0" }}>
          Showing {idx.cases.length} of {idx.matched} matching cases — narrow the search
          to see the rest.
        </div>
      )}
    </div>
  );
}
