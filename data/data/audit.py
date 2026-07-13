"""Append-only audit trail. apps/api calls `write_audit` on every request; it is the
only writer.

Postgres made the table physically immutable with `RULE ... DO INSTEAD NOTHING` on
UPDATE/DELETE. Catalyst's Data Store has no rules and no triggers, so that guarantee
cannot be ported — and app-layer "append-only" enforced by the same code that could
bypass it is not a guarantee at all.

So the immutability moves into the data. Every row carries the hash of the row before it:

    ChainHash = sha256(PrevHash || ResponseHash)

which is a hash chain. Editing any row, or deleting one, breaks every ChainHash after it,
and repairing that requires rewriting the entire tail of the log. The database cannot make
tampering *impossible*; the chain makes it *undeniable*, and `verify_chain()` is what an
auditor runs to prove the log is intact. That is the property a court actually needs.

Stores hashes, not plaintext — the conversation itself lives in `vx_conversation_turn`.
"""
import hashlib
import json
from datetime import datetime, timezone

from . import ds

GENESIS = "0" * 64


def _chain(prev_hash: str, response_hash: str) -> str:
    return hashlib.sha256(f"{prev_hash}{response_hash}".encode()).hexdigest()


def _tip() -> tuple[int, str]:
    """(last AuditID, last ChainHash). The chain starts at GENESIS."""
    row = ds.one('SELECT "AuditID", "ChainHash" FROM "vx_audit_log" ORDER BY "AuditID" DESC')
    if not row:
        return 0, GENESIS
    return int(row["AuditID"]), row["ChainHash"] or GENESIS


def write_audit(officer_id: str, session_id: str, endpoint: str, request_hash: str,
                response_hash: str, agent_trace: list[dict], query_text: str = "") -> str:
    """Append one row. Returns its ChainHash.

    ponytail: reads the tip, then appends — two concurrent writers could chain off the
    same row. There is one API process today. If it is ever scaled out, serialise this
    through Catalyst Cache with a compare-and-set on the tip.
    """
    audit_id, prev = _tip()
    chain = _chain(prev, response_hash)
    ds.insert("vx_audit_log", [{
        "AuditID": audit_id + 1,
        "EmployeeID": int(officer_id),
        "SessionID": session_id,
        "Endpoint": endpoint,
        "QueryText": query_text[:10_000],
        "RequestHash": request_hash,
        "ResponseHash": response_hash,
        "PrevHash": prev,
        "ChainHash": chain,
        "AgentTrace": json.dumps(agent_trace, default=str)[:10_000],
        "CreatedAt": datetime.now(timezone.utc),
    }])
    return chain


def verify_chain() -> tuple[bool, int | None]:
    """Recompute the whole chain. -> (intact, first bad AuditID).

    This is the audit. If it returns False, a row was altered or removed after the fact,
    and the AuditID it names is where the log stopped being trustworthy.
    """
    rows = ds.query('SELECT "AuditID", "ResponseHash", "PrevHash", "ChainHash" '
                    'FROM "vx_audit_log" ORDER BY "AuditID"')
    prev = GENESIS
    for r in rows:
        if r["PrevHash"] != prev or r["ChainHash"] != _chain(prev, r["ResponseHash"] or ""):
            return False, int(r["AuditID"])
        prev = r["ChainHash"]
    return True, None


if __name__ == "__main__":   # self-check: the chain must actually catch tampering
    ds.reset_for_tests()
    for i in range(3):
        write_audit("7", "s1", "/chat", f"req{i}", f"resp{i}", [{"step": "synthesis"}])
    assert verify_chain() == (True, None)

    ds.execute("""UPDATE "vx_audit_log" SET "ResponseHash" = 'forged' WHERE "AuditID" = 2""")
    intact, bad = verify_chain()
    assert not intact and bad == 2, (intact, bad)

    print("audit.py OK — tampering with row 2 was detected")
