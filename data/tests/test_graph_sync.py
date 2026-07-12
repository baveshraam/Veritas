"""Offline checks for the graph edge-list builders — no database."""
import random

from data.generator.build import generate
from data.generator.graph_sync import (
    _EDGE_COLS, accused_in_edges, co_accused_edges, member_of_edges,
    occurred_at_edges, victim_in_edges,
)

_DS = generate(random.Random(9), 300)


def test_every_edge_has_exactly_the_insert_columns():
    """executemany binds the full column set per row — a missing key is a runtime
    error, not a NULL."""
    for edges in (accused_in_edges(_DS), victim_in_edges(_DS), member_of_edges(_DS),
                  occurred_at_edges(_DS), co_accused_edges(_DS)):
        assert edges
        for e in edges:
            assert set(e) == set(_EDGE_COLS)


def test_edge_endpoints_reference_real_records():
    person_ids = {p.person_id for p in _DS.persons}
    fir_ids = {f.fir_id for f in _DS.firs}
    gangs = {p.gang_affiliation for p in _DS.persons if p.gang_affiliation}

    for e in accused_in_edges(_DS) + victim_in_edges(_DS):
        assert e["src_id"] in person_ids and e["src_label"] == "Person"
        assert e["dst_id"] in fir_ids and e["dst_label"] == "CrimeEvent"
    for e in member_of_edges(_DS):
        assert e["src_id"] in person_ids and e["dst_id"] in gangs
    assert gangs  # generator seeds gang affiliations


def test_co_accused_is_deduped_ordered_and_strength_counted():
    edges = co_accused_edges(_DS)
    seen = set()
    for e in edges:
        a, b = e["src_id"], e["dst_id"]
        assert a < b                                  # one row per unordered pair
        assert (a, b) not in seen
        seen.add((a, b))
        assert e["strength"] >= 1
        assert e["edge_type"] == "CO_ACCUSED_WITH"


def test_money_flow_is_the_only_directed_relation():
    """data.graph mirrors every symmetric relation but TRANSFERRED_TO. Reversing a
    payment would invent money that never moved, so the builders must not emit one."""
    from data.graph import _SYMMETRIC
    assert "TRANSFERRED_TO" not in _SYMMETRIC
    for e in accused_in_edges(_DS) + co_accused_edges(_DS):
        assert e["edge_type"] in _SYMMETRIC
