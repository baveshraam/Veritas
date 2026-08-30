"""GET /search — the one search box, over cases and people.

Separate from `GET /cases` on purpose. `/cases` is the browsable REGISTER: it returns
a page of rows plus the facet counts the index's filters are built from, and its `q` is
a filter on that listing. This is a SEARCH: ranked, typed, mixed cases and people, with
each hit carrying the fields that actually matched it.

Policy is applied inside `rag_agent.search`, in the same place and by the same function
the register uses (`can_view_fir`), so what you can find is exactly what you can list —
and a person is returned only when at least one of their cases is visible to you.
"""
from fastapi import APIRouter, Depends, Query
from rag_agent import search as search_agent

from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()


@router.get("/search")
async def unified_search(
    q: str = Query("", description="FIR number, crime, district, station, section, "
                                   "status, modus operandi, or a person's name"),
    limit: int = 20,
    officer: Officer = Depends(current_officer),
):
    # Deliberately NOT audited: this is a keystroke-rate lookup over titles the officer
    # is already entitled to list, and writing an audit row per keystroke would bury
    # the record of what they actually opened under the record of what they typed.
    # Opening any of these hits goes through /fir, /person or /chat, each of which
    # audits.
    hits = search_agent.search(q, officer.role, officer.ps_code, limit=min(limit, 50))
    return {"query": q, "hits": [h.as_dict() for h in hits], "total": len(hits)}
