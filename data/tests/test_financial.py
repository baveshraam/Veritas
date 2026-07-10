"""Offline checks for financial-crime generation + its graph builders."""
import random

from data.generator.build import generate
from data.generator.financial import REPORTING_THRESHOLD, make_financial
from data.generator.graph_sync import (
    account_nodes, involved_in_edges, linked_to_edges, owns_account_edges,
    transaction_nodes, transferred_to_edges,
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
    # flagged_suspicious is a detector output, not generated ground truth
    for n in transaction_nodes(_FIN):
        assert n["flagged_suspicious"] is False


def test_graph_edges_reference_real_accounts_and_persons():
    account_ids = {a["account_id"] for a in account_nodes(_FIN)}
    txn_ids = {t["txn_id"] for t in transaction_nodes(_FIN)}
    person_ids = {p.person_id for p in _DS.persons}
    fir_ids = {f.fir_id for f in _DS.firs}

    for e in owns_account_edges(_FIN):
        assert e["person_id"] in person_ids and e["account_id"] in account_ids
    for e in transferred_to_edges(_FIN):
        assert e["src"] in account_ids and e["dst"] in account_ids
    for e in involved_in_edges(_FIN):
        assert e["account_id"] in account_ids and e["txn_id"] in txn_ids
    for e in linked_to_edges(_FIN):
        assert e["txn_id"] in txn_ids and e["fir_id"] in fir_ids
