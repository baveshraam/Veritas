"""Offline checks for financial-crime generation + its edge builders."""
import random

from data.generator.build import generate
from data.generator.financial import REPORTING_THRESHOLD, make_financial
from data.generator.graph_sync import (
    account_rows, involved_in_edges, linked_to_edges, owns_account_edges,
    transferred_to_edges, txn_rows,
)

_rng = random.Random(11)
_DS = generate(_rng, 500)
_FIN = make_financial(_rng, _DS)


def test_patterns_injected_and_labeled():
    labels = {t.injected_pattern for t in _FIN.transactions}
    assert "structuring" in labels and "layering" in labels
    # structuring deposits sit strictly below the reporting threshold
    for t in _FIN.transactions:
        if t.injected_pattern == "structuring":
            assert t.amount < REPORTING_THRESHOLD


def test_generator_never_pre_flags():
    # flagged_suspicious is a detector OUTPUT. The txn row must not carry it at all,
    # or the AML models would be scoring against their own answer key.
    for r in txn_rows(_FIN):
        assert "flagged_suspicious" not in r
        assert "flag_type" not in r and "detector" not in r


def test_graph_edges_reference_real_accounts_and_persons():
    account_ids = {a["account_id"] for a in account_rows(_FIN)}
    txn_ids = {t["txn_id"] for t in txn_rows(_FIN)}
    person_ids = {p.person_id for p in _DS.persons}
    fir_ids = {f.fir_id for f in _DS.firs}

    for e in owns_account_edges(_FIN):
        assert e["src_id"] in person_ids and e["dst_id"] in account_ids
    for e in transferred_to_edges(_FIN):
        assert e["src_id"] in account_ids and e["dst_id"] in account_ids
        assert e["amount"] is not None          # the money is the point of the edge
    for e in involved_in_edges(_FIN):
        assert e["src_id"] in account_ids and e["dst_id"] in txn_ids
    for e in linked_to_edges(_FIN):
        assert e["src_id"] in txn_ids and e["dst_id"] in fir_ids
