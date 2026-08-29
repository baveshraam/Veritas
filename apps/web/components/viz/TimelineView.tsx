"use client";
import { timelineEvidenceId } from "@/lib/api";
import type { TimelineEvent, TimelineResult } from "@/lib/types";

function fmtDate(iso: string): { d: string; y: string } {
  const t = new Date(iso);
  if (isNaN(t.getTime())) return { d: iso.slice(0, 10), y: "" };
  return {
    d: t.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),
    y: String(t.getFullYear()),
  };
}

/** Events that carry more weight than the rest of a chronology. Not every event
 *  deserves the same visual force — a filing or an arrest is a turning point in
 *  the case, a routine status note is not. */
const KEY = /\b(arrest|charge|charg|convict|acquit|filed|registered|seiz|surrender)/i;

/** One event row.
 *
 *  `kind` is load-bearing: a cross-case link that rests on Fellegi-Sunter's
 *  inferred identity match must never render indistinguishably from a directly
 *  stated fact in the file. It gets the same provenance rail and glyph the
 *  evidence column and the board use — one distinction, drawn one way,
 *  everywhere in the console. */
function Row({
  e, onSelect, onPin, active,
}: { e: TimelineEvent; onSelect?: (id: string) => void; onPin?: (id: string) => void; active?: boolean }) {
  const id = timelineEvidenceId(e);
  const derived = e.kind === "derived";
  const { d, y } = fmtDate(e.date);

  return (
    <button
      className={`tl-item ${active ? "on" : ""} ${derived ? "is-derived" : ""} ${KEY.test(e.description) ? "is-key" : ""}`}
      onClick={() => onSelect?.(id)}
    >
      <span className="tl-date">{d}<br />{y}</span>
      <span className="tl-dot" aria-hidden />
      <span className="tl-head">
        <span className={`prov prov-${derived ? "derived" : "record"}`}>
          {derived ? "Derived" : "Record"}
        </span>
        {e.entity_name && <span className="meta">{e.entity_name}</span>}
        {onPin && (
          <span className="tl-acts">
            <span
              role="button"
              tabIndex={0}
              className="btn btn-sm"
              onClick={(ev) => { ev.stopPropagation(); onPin(id); }}
              onKeyDown={(ev) => { if (ev.key === "Enter") { ev.stopPropagation(); onPin(id); } }}
              title="Save this event to the case's investigation board"
            >
              Pin
            </span>
          </span>
        )}
      </span>
      <span className="tl-desc">{e.description}</span>
    </button>
  );
}

/** The cross-entity investigation timeline: one chronology spanning a case's own
 *  dates, its accused persons' arrests and other cases, and money through any
 *  account they own. Shared by the workspace and the case overlay — same shape,
 *  same rendering, two ways into the same investigation. */
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
    <div className="timeline">
      {data?.connection && (
        <div className={`timeline-connection ${data.connection.has_direct_connection ? "yes" : "no"}`}>
          {data.connection.has_direct_connection
            ? data.connection.direct.map((c, i) => <div key={i}>{c.description}</div>)
            : (
              <div>
                No recorded connection between <b>{data.connection.person_a.name}</b> and{" "}
                <b>{data.connection.person_b.name}</b>. Events close together in time are
                not, on that basis alone, reported as connected.
              </div>
            )}
        </div>
      )}

      {events.length === 0 ? (
        <div className="empty">
          <span className="empty-mark" aria-hidden>◷</span>
          <h3>No dated events</h3>
          <p>Nothing in these records carries a date that could be placed on a chronology.</p>
        </div>
      ) : (
        <div className="timeline-rail">
          {events.map((e, i) => (
            <Row key={`${e.event_type}:${e.entity_id}:${e.date}:${i}`} e={e}
              onSelect={onSelect} onPin={onPin}
              active={activeEvidenceId === timelineEvidenceId(e)} />
          ))}
        </div>
      )}
    </div>
  );
}
