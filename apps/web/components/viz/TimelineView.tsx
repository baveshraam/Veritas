"use client";
import { timelineEvidenceId } from "@/lib/api";
import type { TimelineEvent, TimelineResult } from "@/lib/types";

const ENTITY_LABEL: Record<string, string> = {
  case: "case", person: "person", transaction: "transaction",
};

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso.slice(0, 10)
    : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

/** One event row. `kind` is the load-bearing badge here — the same discipline the
 *  investigation board already applies to a derived finding vs. a pinned record:
 *  a cross-case link that rests on Fellegi-Sunter's inferred identity match must
 *  never render indistinguishably from a directly stated ER fact. */
function Row({
  e, onSelect, onPin, active,
}: { e: TimelineEvent; onSelect?: (id: string) => void; onPin?: (id: string) => void; active?: boolean }) {
  const id = timelineEvidenceId(e);
  return (
    <div
      className={`timeline-item ${active ? "active" : ""}`}
      onClick={() => onSelect?.(id)}
    >
      <div className="timeline-dot" />
      <div className="timeline-body">
        <div className="timeline-row-head">
          <span className="copilot-date">{fmtDate(e.date)}</span>
          {e.entity_name && (
            <span className="chip chip-low" title={ENTITY_LABEL[e.entity_type] ?? e.entity_type}>
              {e.entity_name}
            </span>
          )}
          <span className={`board-kind ${e.kind === "derived" ? "board-kind-finding" : "board-kind-evidence"}`}>
            {e.kind === "derived" ? "derived" : "record"}
          </span>
          {onPin && (
            <button
              className="btn btn-sm"
              style={{ marginLeft: "auto" }}
              onClick={(ev) => { ev.stopPropagation(); onPin(id); }}
              title="Save this event to the case's investigation board"
            >
              Pin
            </button>
          )}
        </div>
        <div className="timeline-desc">{e.description}</div>
      </div>
    </div>
  );
}

/** The cross-entity investigation timeline (docs/INDUSTRY_GAP_ANALYSIS.md §7 item
 *  3) — one chronological list spanning a case's own dates, its accused persons'
 *  arrests and OTHER cases, and money through any account they own. Shared by the
 *  chat-driven context pane (TIMELINE/TIMELINE_CONNECTION intents) and the
 *  Copilot overlay's own Timeline tab (Copilot.tsx) — same shape, same rendering,
 *  two entry points into the same investigation. */
export default function TimelineView({
  data, onSelect, onPin, activeEvidenceId,
}: {
  data: TimelineResult;
  onSelect?: (id: string) => void;
  onPin?: (id: string) => void;
  activeEvidenceId?: string | null;
}) {
  const events = data?.events ?? [];

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      {data?.connection && (
        <div className={`timeline-connection ${data.connection.has_direct_connection ? "yes" : "no"}`}>
          {data.connection.has_direct_connection
            ? data.connection.direct.map((d, i) => <div key={i}>{d.description}</div>)
            : <div>No recorded connection between {data.connection.person_a.name} and{" "}
                {data.connection.person_b.name}. Events near each other in time are not,
                on that basis alone, reported as connected.</div>}
        </div>
      )}

      {events.length === 0 ? (
        <div className="viz-empty">
          <div style={{ fontSize: 22, opacity: 0.4 }}>◷</div>
          <div>No dated events are recorded for this timeline.</div>
        </div>
      ) : (
        <div className="timeline-rail">
          {events.map((e, i) => (
            <Row key={`${e.event_type}:${e.entity_id}:${e.date}:${i}`} e={e} onSelect={onSelect}
                onPin={onPin} active={activeEvidenceId === timelineEvidenceId(e)} />
          ))}
        </div>
      )}
    </div>
  );
}
