"""GET /explain — the provenance chain behind ONE result.

This is the REST half of the same question the conversational surface answers with
`EXPLAIN_REASONING` ("why is this person connected?"). It exists because the other
way an officer points at a result is by clicking it — a node in the network, a case
on the map, an event on the timeline — and a click carries no sentence for the
interpreter to route.

Both halves call `rag_agent.provenance.explain`, so a result explained by clicking and
the same result explained by typing are one explanation rendered twice, not two
explanations that can drift apart. See `packages/rag_agent/rag_agent/provenance.py`.

The evidence item itself is looked up in the session's own last turn, because that is
where the fields the explanation reads (`source_type`, `authoritative`,
`confidence_kind`) actually live. Where the click came from a surface that never went
through /chat — the Copilot overlay's timeline tab, a map point on a re-rendered
visualization — the `evidence_id` alone is enough for most kinds, since the prefix
convention is what dispatch runs on.

Policy: the officer's own role and station are passed into `explain`, which uses them
for every record read it makes. A graph path may legitimately run through a case at
another station; the hop is still reported, and the case behind it is named only where
this officer may see it (see `provenance._case_labels`).
"""
from fastapi import APIRouter, Depends, Query
from rag_agent import provenance

from ..audit import record
from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()


def _item_from_session(session_id: str | None, evidence_id: str) -> dict:
    """The stored evidence item this id refers to, or a bare stand-in.

    A stand-in is not a degraded answer for most kinds — `hotspot:`, `forecast:`,
    `risk:`, `flow:`, `assoc:` and `same_as:` all explain from the id and the record
    layer alone. It matters only for `timeline:`, whose authoritative-vs-derived split
    is carried on the item, and `fir:`, whose "why THIS case" line is sharper when the
    retrieving operation is known.
    """
    if not session_id:
        return {"evidence_id": evidence_id}
    try:
        from data import get_conversation_history
        history = get_conversation_history(session_id)
    except Exception:
        return {"evidence_id": evidence_id}
    for turn in reversed(history or []):
        for e in turn.evidence_items or []:
            if e.get("evidence_id") == evidence_id:
                return e
    return {"evidence_id": evidence_id}


def _context(session_id: str | None) -> tuple[str, str | None, str | None]:
    """(operation, subject person id, open case id) for this session's latest state.

    The operation is what makes "why THIS case" answerable — the same FIR record is on
    screen for a completely different reason depending on whether it was looked up by
    number, matched a filter, or was ranked as similar to another case. The subject is
    what makes a co-offending path computable at all, and the open case is what lets an
    accused row be explained in both the name the file uses and the canonical one.
    """
    if not session_id:
        return "", None, None
    op, subject, case = "", None, None
    try:
        from data import get_conversation_history, get_session_focus
        history = get_conversation_history(session_id)
        if history:
            rc = history[-1].result_context or {}
            op = rc.get("operation") or (rc.get("last_request") or {}).get("operation") or ""
        focus = get_session_focus(session_id)
        if focus:
            subject, case = focus.active_person, focus.active_fir
    except Exception:
        pass
    return op, subject, case


@router.get("/explain")
async def explain(
    evidence_id: str = Query(..., description="e.g. assoc:877, fir:1043, hotspot:KA05:0"),
    session_id: str | None = None,
    case_id: str | None = None,
    officer: Officer = Depends(current_officer),
):
    item = _item_from_session(session_id, evidence_id)
    operation, subject_id, session_case = _context(session_id)
    d = provenance.explain(item, role=officer.role, ps=officer.ps_code,
                           operation=operation, subject_id=subject_id,
                           case_id=case_id or session_case)
    payload = d.model_dump()
    record(officer.officer_id, session_id, "/explain", {"evidence_id": evidence_id}, payload)
    return payload
