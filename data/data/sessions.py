"""Session-focus and conversation persistence — the only store for a stateless API.

Row<->model mapping is pure (`_focus_from_row`, `_focus_params`) so it's testable
without a DB; the get/upsert/write functions are the thin SQL layer.
"""
import json
from typing import Optional

from sqlalchemy import text

from .db import get_session
from .models import ConversationTurn, SessionFocus


def _focus_from_row(row) -> SessionFocus:
    date_range = None
    if row.active_date_from and row.active_date_to:
        date_range = (row.active_date_from, row.active_date_to)
    return SessionFocus(
        active_person=str(row.active_person) if row.active_person else None,
        active_fir=str(row.active_fir) if row.active_fir else None,
        active_location=row.active_location,
        active_date_range=date_range,
    )


def _focus_params(focus: SessionFocus) -> dict:
    d_from, d_to = focus.active_date_range or (None, None)
    return {
        "active_person": focus.active_person,
        "active_fir": focus.active_fir,
        "active_location": focus.active_location,
        "active_date_from": d_from,
        "active_date_to": d_to,
    }


def get_session_focus(session_id: str) -> Optional[SessionFocus]:
    with get_session() as s:
        row = s.execute(text(
            "SELECT active_person, active_fir, active_location, "
            "active_date_from, active_date_to FROM session WHERE session_id = :sid"
        ), {"sid": session_id}).first()
    return _focus_from_row(row) if row else None


def upsert_session_focus(session_id: str, officer_id: str, focus: SessionFocus) -> None:
    params = {"sid": session_id, "oid": officer_id, **_focus_params(focus)}
    with get_session() as s:
        s.execute(text(
            "INSERT INTO session (session_id, officer_id, active_person, active_fir, "
            "  active_location, active_date_from, active_date_to, last_turn_at) "
            "VALUES (:sid, :oid, CAST(:active_person AS uuid), CAST(:active_fir AS uuid), "
            "  :active_location, :active_date_from, :active_date_to, NOW()) "
            "ON CONFLICT (session_id) DO UPDATE SET "
            "  active_person = EXCLUDED.active_person, active_fir = EXCLUDED.active_fir, "
            "  active_location = EXCLUDED.active_location, "
            "  active_date_from = EXCLUDED.active_date_from, "
            "  active_date_to = EXCLUDED.active_date_to, last_turn_at = NOW()"
        ), params)


def write_conversation_turn(session_id: str, turn_index: int, query: str, language: str,
                            final_answer: str, citations: list[dict],
                            evidence_items: list[dict], visualization: dict,
                            agent_trace: list[dict]) -> None:
    with get_session() as s:
        s.execute(text(
            "INSERT INTO conversation_turn (session_id, turn_index, query, language, "
            "  final_answer, citations, evidence_items, visualization, agent_trace) "
            "VALUES (:sid, :idx, :q, :lang, :ans, CAST(:cit AS jsonb), CAST(:ev AS jsonb), "
            "  CAST(:viz AS jsonb), CAST(:trace AS jsonb))"
        ), {
            "sid": session_id, "idx": turn_index, "q": query, "lang": language,
            "ans": final_answer, "cit": json.dumps(citations),
            "ev": json.dumps(evidence_items), "viz": json.dumps(visualization),
            "trace": json.dumps(agent_trace),
        })


def get_conversation_history(session_id: str) -> list[ConversationTurn]:
    with get_session() as s:
        rows = s.execute(text(
            "SELECT turn_index, query, language, final_answer, citations, "
            "  evidence_items, visualization, agent_trace, created_at "
            "FROM conversation_turn WHERE session_id = :sid ORDER BY turn_index"
        ), {"sid": session_id}).all()
    return [ConversationTurn(
        turn_index=r.turn_index, query=r.query, language=r.language,
        final_answer=r.final_answer, citations=r.citations or [],
        evidence_items=r.evidence_items or [], visualization=r.visualization or {},
        agent_trace=r.agent_trace or [], created_at=r.created_at,
    ) for r in rows]
