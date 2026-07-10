"""Cross-folder data shapes owned here.

SessionFocus lives here (not in packages/rag_agent) for one implementable reason:
data's write helpers take/return it, and data must not import rag_agent (rag_agent
already imports data — the reverse would be circular). SessionFocus is a pure 1:1
mapping of the `session` table's active_* columns, so data is its natural home;
rag_agent imports it from here. ConversationTurn was already data-owned.
"""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel


class SessionFocus(BaseModel):
    active_person: Optional[str] = None       # person_id (UUID as str), NOT scrb_id
    active_fir: Optional[str] = None          # fir_id (UUID as str), NOT fir_number
    active_location: Optional[str] = None     # district/taluk name
    active_date_range: Optional[tuple[date, date]] = None   # (from, to)


class ConversationTurn(BaseModel):
    turn_index: int
    query: str
    language: Literal["en", "kn"]
    final_answer: str
    citations: list[dict]
    evidence_items: list[dict]
    visualization: dict
    agent_trace: list[dict]
    created_at: datetime
