"""The audit chain and session persistence — the two places Data Store's limits bite hardest.

The audit chain is the more important of the two. Postgres made the log physically immutable
with `RULE ... DO INSTEAD NOTHING`; Data Store has no rules and no triggers, so that
guarantee had to be rebuilt in the data itself. These tests are what says it actually works —
without them, "append-only" is a claim in a docstring.
"""
import pytest

from data import cache, ds
from data.audit import GENESIS, verify_chain, write_audit
from data.models import SessionFocus
from data.sessions import (
    _focus_from_row,
    _focus_row,
    get_conversation_history,
    get_session_focus,
    upsert_session_focus,
    write_conversation_turn,
)


@pytest.fixture(autouse=True)
def fresh():
    ds.reset_for_tests()
    cache._local.clear()          # the focus cache outlives the database otherwise


# ------------------------------------------------------------------------- audit chain
def test_an_intact_chain_verifies():
    for i in range(5):
        write_audit("7", "s1", "/chat", f"req{i}", f"resp{i}", [{"step": "synthesis"}])
    assert verify_chain() == (True, None)


def test_the_chain_starts_at_genesis():
    write_audit("7", "s1", "/chat", "r", "resp", [])
    row = ds.one('SELECT "PrevHash" FROM "vx_audit_log" WHERE "AuditID" = 1')
    assert row["PrevHash"] == GENESIS


def test_altering_a_row_breaks_the_chain_at_that_row():
    for i in range(4):
        write_audit("7", "s1", "/chat", f"req{i}", f"resp{i}", [])
    ds.execute("""UPDATE "vx_audit_log" SET "ResponseHash" = 'forged' WHERE "AuditID" = 2""")

    intact, first_bad = verify_chain()
    assert not intact and first_bad == 2


def test_deleting_a_row_breaks_the_chain():
    for i in range(4):
        write_audit("7", "s1", "/chat", f"req{i}", f"resp{i}", [])
    ds.execute('DELETE FROM "vx_audit_log" WHERE "AuditID" = 2')

    intact, first_bad = verify_chain()
    assert not intact and first_bad == 3, "removing a row must break its successor"


def test_the_log_stores_hashes_not_plaintext_answers():
    """Tamper-evidence, not a transcript. The conversation lives in vx_conversation_turn."""
    write_audit("7", "s1", "/chat", "reqhash", "resphash", [], query_text="who is Ramesh")
    row = ds.one('SELECT "ResponseHash", "QueryText" FROM "vx_audit_log"')
    assert row["ResponseHash"] == "resphash"
    cols = {c.name for c in __import__("data.schema", fromlist=["x"]).VX_TABLES["vx_audit_log"]}
    assert "FinalAnswer" not in cols and "ResponseText" not in cols


# --------------------------------------------------------------------- session focus
def test_focus_maps_both_ways_without_a_database():
    focus = SessionFocus(active_person="41", active_fir="7",
                         active_location="Bengaluru Urban")
    row = _focus_row(focus)
    assert row["ActivePersonUID"] == 41 and row["ActiveCaseMasterID"] == 7
    assert _focus_from_row(row) == focus


def test_empty_focus_maps_to_all_nulls():
    assert _focus_row(SessionFocus()) == {
        "ActivePersonUID": None, "ActiveCaseMasterID": None, "ActiveLocation": None,
        "ActiveDateFrom": None, "ActiveDateTo": None}


def test_focus_upserts_rather_than_duplicating():
    """Data Store has no ON CONFLICT. Without the read-then-update, the follow-up question
    "does HE have priors" would resolve against a stale row."""
    upsert_session_focus("s1", "7", SessionFocus(active_person="41"))
    upsert_session_focus("s1", "7", SessionFocus(active_person="99"))

    assert get_session_focus("s1").active_person == "99"
    assert ds.scalar('SELECT COUNT("SessionID") AS c FROM "vx_session"') == 1


def test_unknown_session_has_no_focus():
    assert get_session_focus("nope") is None


# ------------------------------------------------------------------ conversation turns
def test_a_turn_round_trips():
    write_conversation_turn("s1", 0, "who is he?", "en", "Ramesh Gowda.",
                            [{"index": 1}], [{"content": "x"}], {"kind": "map"},
                            [{"step": "synthesis"}])
    (t,) = get_conversation_history("s1")
    assert t.query == "who is he?" and t.final_answer == "Ramesh Gowda."
    assert t.citations == [{"index": 1}]
    assert t.visualization == {"kind": "map"}


def test_an_oversized_turn_sheds_evidence_bodies_and_keeps_their_identity():
    """`text` caps at 10,000 characters and Data Store rejects the row rather than trimming
    it. Citations and the trace are what the PDF export and the reasoning panel are made of,
    so they are never what gives way.

    Evidence BODIES give way; evidence IDENTITY does not. Dropping the items wholesale was
    lossy in a way that produced wrong answers rather than missing ones — a later turn reads
    `source_type`/`source_id`/`authoritative` off these items to answer "why is this here"
    and "where are the related cases", and with the list empty it fell back to defaults, so a
    recorded transfer on a truncated timeline explained itself as a probabilistic identity
    inference. Both found live."""
    huge = [{"evidence_id": f"timeline:money_in:{i}:2026-01-01", "source_type": "FIR_RECORD",
             "source_id": str(i), "authoritative": True, "confidence": 0.9,
             "confidence_kind": "support", "content": "x" * 500} for i in range(50)]
    write_conversation_turn("s1", 0, "q", "en", "a", [{"index": 1}], huge,
                            {"points": list(range(3000))}, [{"step": "synthesis"}])

    (t,) = get_conversation_history("s1")
    assert t.citations == [{"index": 1}]
    assert t.agent_trace == [{"step": "synthesis"}]
    assert t.visualization == {}
    assert len(t.evidence_items) == 50
    kept = t.evidence_items[0]
    assert kept["evidence_id"] == "timeline:money_in:0:2026-01-01"
    assert kept["source_id"] == "0" and kept["authoritative"] is True
    assert "content" not in kept          # the body is what gave way


def test_a_turn_too_large_even_for_skeletons_still_stores_its_citations():
    """The last resort. 20,000 evidence ids will not fit under any tier, and the turn
    must still be readable rather than rejected by the Data Store."""
    huge = [{"evidence_id": f"fir:{i}", "source_type": "FIR_RECORD", "source_id": str(i),
             "content": "x"} for i in range(20_000)]
    write_conversation_turn("s1", 0, "q", "en", "a", [{"index": 1}], huge, {},
                            [{"step": "synthesis"}])
    (t,) = get_conversation_history("s1")
    assert t.citations == [{"index": 1}]
    assert t.evidence_items == []


def test_history_comes_back_in_turn_order():
    for i in range(3):
        write_conversation_turn("s1", i, f"q{i}", "en", f"a{i}", [], [], {}, [])
    assert [t.turn_index for t in get_conversation_history("s1")] == [0, 1, 2]


def test_the_focus_cache_is_a_cache_not_a_second_source_of_truth():
    """Catalyst Cache sits in front of the focus stack because it is read on every turn. It
    must never answer with something the database does not say — so the write goes through
    after the row lands, and a cold cache reconstructs from the row."""
    upsert_session_focus("s1", "7", SessionFocus(active_person="41"))
    cache._local.clear()                                  # simulate a cold container
    assert get_session_focus("s1").active_person == "41"  # rebuilt from the Data Store

    upsert_session_focus("s1", "7", SessionFocus(active_person="99"))
    assert get_session_focus("s1").active_person == "99"  # and never serves a stale one
