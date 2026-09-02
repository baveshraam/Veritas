"""Veritas data foundation — schemas, connections, and write helpers.

Every other track reaches the databases through this package; nobody opens
their own connection or redefines a table shape. See CLAUDE.md §3.
"""
from .audit import verify_chain, write_audit
from .models import ConversationTurn, SessionFocus
from .nlp import (
    Entity,
    ner_extract,
    speech_to_text,
    text_to_speech,
    translate,
    transliterate,
)
from .sessions import (
    get_conversation_history,
    get_session_focus,
    list_sessions,
    upsert_session_focus,
    write_conversation_turn,
)
from .transactions import clear_flags, flag_transaction

__all__ = [
    "SessionFocus", "ConversationTurn",
    "get_session_focus", "upsert_session_focus",
    "write_conversation_turn", "get_conversation_history", "list_sessions",
    "write_audit", "verify_chain", "flag_transaction", "clear_flags",
    "Entity", "ner_extract", "transliterate", "translate",
    "speech_to_text", "text_to_speech",
]

