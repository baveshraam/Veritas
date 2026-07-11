"""Tamper-evident audit write. Called on every request that touches records.

Hashes, not content: audit_log proves *what was asked and answered* without becoming
a second copy of the case file. The plaintext conversation lives in
data.conversation_turn — two tables, two purposes (see data/README.md).
"""
import hashlib
import json
from typing import Any

from data import write_audit


def sha256(payload: Any) -> str:
    if not isinstance(payload, (str, bytes)):
        payload = json.dumps(payload, sort_keys=True, default=str)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def record(officer_id: str, session_id: str | None, endpoint: str,
           request_payload: Any, response_payload: Any,
           agent_trace: list[dict] | None = None) -> None:
    write_audit(
        officer_id=officer_id,
        # NULL, not "" — audit_log.session_id is a UUID column and the record
        # endpoints (/fir, /person, /copilot) are not session-scoped.
        session_id=session_id or None,
        endpoint=endpoint,
        request_hash=sha256(request_payload),
        response_hash=sha256(response_payload),
        agent_trace=agent_trace or [],
    )
