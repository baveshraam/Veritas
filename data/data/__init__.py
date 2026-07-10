"""Veritas data foundation — schemas, connections, and write helpers.

Every other track reaches the databases through this package; nobody opens
their own connection or redefines a table shape. See data/README.md.
"""
from .audit import write_audit
from .models import ConversationTurn, SessionFocus
from .sessions import (
    get_conversation_history,
    get_session_focus,
    upsert_session_focus,
    write_conversation_turn,
)
from .transactions import flag_transaction, set_canonical_entity, write_same_as_edge

__all__ = [
    "SessionFocus", "ConversationTurn",
    "get_session_focus", "upsert_session_focus",
    "write_conversation_turn", "get_conversation_history",
    "write_audit", "set_canonical_entity", "write_same_as_edge", "flag_transaction",
]

