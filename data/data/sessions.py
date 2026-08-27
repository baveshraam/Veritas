"""Session-focus and conversation persistence — the only store for a stateless API.

Row<->model mapping is pure (`_focus_from_row`, `_focus_row`) so it's testable without a
database; the get/upsert/write functions are the thin ZCQL layer.

Two Data Store facts shape this module:
  * No UPSERT. There is no ON CONFLICT and no MERGE, so `upsert_session_focus` reads,
    then updates or inserts. Single-writer per session, so the race is not real here.
  * `text` caps at 10,000 characters. A turn's payload (map points, evidence bodies, the
    full agent trace) can exceed that, so `_pack` sheds the two heavy, regenerable parts
    before it truncates anything — citations and the trace, which the PDF export and the
    reasoning panel actually need, always survive.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from . import cache, ds
from .models import ConversationTurn, SessionFocus

_TEXT_CAP = 10_000
_PAYLOAD_BUDGET = 9_500      # leave headroom; Data Store rejects the row, it doesn't trim


def _focus_from_row(row: dict) -> SessionFocus:
    d_from, d_to = row.get("ActiveDateFrom"), row.get("ActiveDateTo")
    return SessionFocus(
        active_person=str(row["ActivePersonUID"]) if row.get("ActivePersonUID") else None,
        active_fir=str(row["ActiveCaseMasterID"]) if row.get("ActiveCaseMasterID") else None,
        active_location=row.get("ActiveLocation"),
        active_date_range=(d_from, d_to) if d_from and d_to else None,
    )


def _focus_row(focus: SessionFocus) -> dict:
    d_from, d_to = focus.active_date_range or (None, None)
    return {
        "ActivePersonUID": int(focus.active_person) if focus.active_person else None,
        "ActiveCaseMasterID": int(focus.active_fir) if focus.active_fir else None,
        "ActiveLocation": focus.active_location,
        "ActiveDateFrom": d_from,
        "ActiveDateTo": d_to,
    }


def _cache_key(session_id: str) -> str:
    return f"focus:{session_id}"


def get_session_focus(session_id: str) -> Optional[SessionFocus]:
    """Read-through Catalyst Cache. This is on the critical path of every single turn — the
    orchestrator cannot even route a query until it knows who "he" is."""
    cached = cache.get(_cache_key(session_id))
    if cached is not None:
        return SessionFocus(**cached)

    row = ds.one(
        'SELECT "ActivePersonUID", "ActiveCaseMasterID", "ActiveLocation", '
        '"ActiveDateFrom", "ActiveDateTo" FROM "vx_session" WHERE "SessionID" = :sid',
        {"sid": session_id},
    )
    if not row:
        return None
    focus = _focus_from_row(row)
    cache.put(_cache_key(session_id), focus.model_dump())
    return focus


def upsert_session_focus(session_id: str, officer_id: str, focus: SessionFocus,
                         language: str = "en") -> None:
    row = _focus_row(focus)
    row["UpdatedAt"] = datetime.now(timezone.utc)
    exists = ds.one('SELECT "SessionID" FROM "vx_session" WHERE "SessionID" = :sid',
                    {"sid": session_id})
    if exists:
        row["SessionID"] = session_id
        ds.update("vx_session", "SessionID", [row])
    else:
        row.update(SessionID=session_id, EmployeeID=int(officer_id), Language=language)
        ds.insert("vx_session", [row])

    # Write-through, after the row lands. A cache populated before the write could serve a
    # focus that a failed write means does not exist.
    cache.put(_cache_key(session_id), focus.model_dump())


def _pack(citations: list[dict], evidence_items: list[dict], visualization: dict,
          agent_trace: list[dict], result_context: Optional[dict] = None) -> str:
    """The turn's side-car, small enough for a `text` column.

    Citations and the agent trace are what the PDF export and the reasoning panel are
    made of, so they are never dropped. result_context is a handful of scalars plus an
    id list already capped at the same 5 ids a turn samples for citation, so it never
    meaningfully contributes to the size that triggers truncation — it survives
    truncation in the same tier as citations/trace, for the same reason: a follow-up
    ("only these?") needs it exactly when the turn it came from was too big to store
    whole. Evidence bodies and the visualization payload (which can be thousands of map
    points) are re-derivable from the citations, so they are what gives way instead.
    """
    full = {"citations": citations, "evidence_items": evidence_items,
            "visualization": visualization, "agent_trace": agent_trace,
            "result_context": result_context or {}}
    blob = json.dumps(full, default=str)
    if len(blob) <= _PAYLOAD_BUDGET:
        return blob
    return json.dumps({"citations": citations, "evidence_items": [], "visualization": {},
                       "agent_trace": agent_trace, "result_context": result_context or {},
                       "truncated": True}, default=str)


def write_conversation_turn(session_id: str, turn_index: int, query: str, language: str,
                            final_answer: str, citations: list[dict],
                            evidence_items: list[dict], visualization: dict,
                            agent_trace: list[dict],
                            result_context: Optional[dict] = None) -> None:
    ds.insert("vx_conversation_turn", [{
        "TurnID": ds.next_id("vx_conversation_turn", "TurnID"),
        "SessionID": session_id,
        "TurnIndex": turn_index,
        "Query": query[:_TEXT_CAP],
        "Language": language,
        "FinalAnswer": final_answer[:_TEXT_CAP],
        "Payload": _pack(citations, evidence_items, visualization, agent_trace, result_context),
        "CreatedAt": datetime.now(timezone.utc),
    }])


def get_conversation_history(session_id: str) -> list[ConversationTurn]:
    rows = ds.query(
        'SELECT "TurnIndex", "Query", "Language", "FinalAnswer", "Payload", "CreatedAt" '
        'FROM "vx_conversation_turn" WHERE "SessionID" = :sid ORDER BY "TurnIndex"',
        {"sid": session_id},
    )
    out = []
    for r in rows:
        p = json.loads(r["Payload"]) if r.get("Payload") else {}
        out.append(ConversationTurn(
            turn_index=r["TurnIndex"], query=r["Query"] or "",
            language=r["Language"] or "en", final_answer=r["FinalAnswer"] or "",
            citations=p.get("citations") or [],
            evidence_items=p.get("evidence_items") or [],
            visualization=p.get("visualization") or {},
            agent_trace=p.get("agent_trace") or [],
            created_at=r["CreatedAt"],
            result_context=p.get("result_context") or {},
        ))
    return out


if __name__ == "__main__":   # self-check: focus round-trips, an oversized turn still stores
    ds.reset_for_tests()
    cache._local.clear()
    focus = SessionFocus(active_person="42", active_location="Kolar")
    upsert_session_focus("s1", "7", focus)
    assert get_session_focus("s1").active_person == "42"

    upsert_session_focus("s1", "7", SessionFocus(active_person="99"))
    assert get_session_focus("s1").active_person == "99", "upsert must overwrite"

    huge = [{"content": "x" * 500} for _ in range(50)]        # ~25KB of evidence
    write_conversation_turn("s1", 0, "who?", "en", "him.", [{"index": 1}], huge,
                            {"points": list(range(2000))}, [{"step": "synthesis"}])
    (t,) = get_conversation_history("s1")
    assert t.citations == [{"index": 1}], "citations must survive truncation"
    assert t.agent_trace, "the trace must survive truncation"
    assert t.evidence_items == [], "evidence should be what gives way"
    print("sessions.py OK")
