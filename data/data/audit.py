"""Append-only audit trail. apps/api calls write_audit on every request.

Stores SHA-256 hashes (not plaintext) plus the agent trace. The table is
immutable at the DB level (rules in sql/002); this is the only writer.
"""
import json

from sqlalchemy import text

from .db import get_session


def write_audit(officer_id: str, session_id: str, endpoint: str,
                request_hash: str, response_hash: str, agent_trace: list[dict]) -> None:
    with get_session() as s:
        s.execute(text(
            "INSERT INTO audit_log (officer_id, session_id, endpoint, "
            "  request_hash, response_hash, agent_trace) "
            "VALUES (:oid, :sid, :ep, :reqh, :resph, CAST(:trace AS jsonb))"
        ), {
            "oid": officer_id, "sid": session_id, "ep": endpoint,
            "reqh": request_hash, "resph": response_hash,
            "trace": json.dumps(agent_trace),
        })
