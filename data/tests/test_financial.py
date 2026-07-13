"""The financial layer, and the one rule that makes the AML numbers mean anything.

`FlaggedSuspicious` is a **detector output**. The generator must never set it, and the
injected-pattern labels must never live in the table the detectors read — otherwise every
AML model is scoring its own answer key and the metrics are theatre.
"""
import json
import os
import random

from data import ds
from data.generator.financial import REPORTING_THRESHOLD, make_financial


def test_the_generator_never_pre_flags_a_transaction():
    """The single most important invariant in this file."""
    rng = random.Random(1)
    people = [{"PersonUID": i, "IsHabitualOffender": i % 3 == 0} for i in range(1, 400)]
    accounts, txns, labels = make_financial(rng, people, list(range(1, 200)))

    assert txns
    assert not any(t["FlaggedSuspicious"] for t in txns)
    assert all("injected_pattern" not in t for t in txns)


def test_the_labels_are_returned_separately_from_the_rows():
    """Ground truth is a return value, not a column. Whoever writes the rows to the database
    physically cannot write the answer key with them."""
    rng = random.Random(1)
    people = [{"PersonUID": i, "IsHabitualOffender": True} for i in range(1, 300)]
    _, txns, labels = make_financial(rng, people, [1, 2, 3])

    assert labels
    assert set(labels.values()) <= {"structuring", "layering"}
    assert set(labels) <= {t["TxnID"] for t in txns}


def test_flag_columns_are_empty_in_the_built_dataset(dataset):
    """End-to-end: after a full generator run, nothing is flagged until a detector runs."""
    flagged = ds.scalar('SELECT COUNT("TxnID") AS c FROM "vx_txn" '
                        'WHERE "FlaggedSuspicious" = 1')
    assert flagged == 0


def test_the_aml_answer_key_is_written_outside_the_database(dataset):
    path = os.environ["VERITAS_AML_LABELS"]
    labels = json.loads(open(path).read())
    assert labels, "no injected patterns to train against"

    txn_ids = {r["TxnID"] for r in ds.query('SELECT "TxnID" FROM "vx_txn"')}
    assert {int(k) for k in labels} <= txn_ids


def test_structuring_deposits_sit_just_below_the_reporting_threshold(dataset):
    """The pattern the rule-based detector is built to catch. If the injected deposits were
    not sub-threshold, the detector would be looking for something that isn't there."""
    labels = json.loads(open(os.environ["VERITAS_AML_LABELS"]).read())
    ids = [int(k) for k, v in labels.items() if v == "structuring"]
    assert ids

    rows = ds.query('SELECT "Amount" FROM "vx_txn" WHERE "TxnID" IN :ids', {"ids": ids})
    assert all(0 < r["Amount"] < REPORTING_THRESHOLD for r in rows)


def test_layering_produces_a_multi_hop_trail(dataset):
    """The pattern the rule-based detector structurally cannot see, and the GNN exists for.
    A chain, not a fan-in: each hop moves to a new account."""
    labels = json.loads(open(os.environ["VERITAS_AML_LABELS"]).read())
    ids = [int(k) for k, v in labels.items() if v == "layering"]
    assert ids

    rows = ds.query('SELECT "SrcAccountID", "DstAccountID" FROM "vx_txn" '
                    'WHERE "TxnID" IN :ids', {"ids": ids})
    accounts = {r["SrcAccountID"] for r in rows} | {r["DstAccountID"] for r in rows}
    assert len(accounts) >= 3, "a laundering 'chain' through fewer than three accounts"


def test_accounts_belong_to_resolved_people(dataset):
    """An account belongs to a human. Opening one per Accused row would scatter a launderer's
    money across a dozen identities and make the whole layer meaningless."""
    orphans = ds.scalar('SELECT COUNT("AccountID") AS c FROM "vx_account" '
                        'WHERE "PersonUID" NOT IN (SELECT "PersonUID" FROM "vx_person")')
    assert orphans == 0
