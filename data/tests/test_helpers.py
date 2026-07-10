"""Offline checks for write-helper mapping + the documented import surface."""
from datetime import date
from types import SimpleNamespace


def test_public_import_surface():
    import data
    for name in ("SessionFocus", "get_session_focus", "upsert_session_focus",
                 "write_conversation_turn", "get_conversation_history",
                 "write_audit", "set_canonical_entity", "write_same_as_edge",
                 "flag_transaction"):
        assert hasattr(data, name), f"data.{name} not exported"


def test_session_focus_roundtrips_through_row_mapping():
    from data.models import SessionFocus
    from data.sessions import _focus_from_row, _focus_params

    focus = SessionFocus(
        active_person="11111111-1111-1111-1111-111111111111",
        active_fir="22222222-2222-2222-2222-222222222222",
        active_location="Bengaluru Urban",
        active_date_range=(date(2024, 1, 1), date(2024, 6, 30)),
    )
    p = _focus_params(focus)
    # simulate the DB round-trip: params become a row, row maps back to a focus
    row = SimpleNamespace(
        active_person=p["active_person"], active_fir=p["active_fir"],
        active_location=p["active_location"],
        active_date_from=p["active_date_from"], active_date_to=p["active_date_to"],
    )
    assert _focus_from_row(row) == focus


def test_empty_focus_maps_to_all_nulls():
    from data.models import SessionFocus
    from data.sessions import _focus_params
    p = _focus_params(SessionFocus())
    assert p == {"active_person": None, "active_fir": None, "active_location": None,
                 "active_date_from": None, "active_date_to": None}
