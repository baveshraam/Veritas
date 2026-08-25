"""Data-integrity checks over the built dataset.

Phase 1 added these because nothing in the repo asserted them. Every other suite
verified that a query *ran*; none verified that what came back was internally
consistent. "The query succeeded" and "the data is correct" are different claims, and
only the first one was ever being made.

The checks are driven by `data.schema` rather than by a hand-written list, so a table
added later is covered without anyone remembering to add it here. That matters more
than it sounds: the duplicate class of bug this suite exists to catch is exactly the
kind that arrives with a new table and a new loader.

Scope note. This runs against the SQLite dataset the `dataset` fixture builds, which is
the *same* code path (schema, generator, loaders, resolver, graph sync) the Catalyst
deployment runs — so a violation here is a violation there. What it cannot see is the
Data Store's own paging artifact; that is covered separately in `test_ds.py` and by the
ROWID dedupe in `data.ds._catalyst_select`.
"""
import pytest

from data import ds
from data.schema import TABLES


def _rows(table: str, cols: list[str]) -> list[dict]:
    quoted = ", ".join(f'"{c}"' for c in cols)
    return ds.query(f'SELECT {quoted} FROM "{table}"')


# --- uniqueness -------------------------------------------------------------------

def test_every_column_the_schema_declares_unique_actually_is(dataset):
    """The business keys. A duplicate CaseMasterID means two FIRs answer to one id, and
    every join downstream silently picks one of them."""
    offenders = {}
    for table, cols in TABLES.items():
        for col in cols:
            if not col.unique:
                continue
            values = [r[col.name] for r in _rows(table, [col.name])
                      if r[col.name] is not None]
            dupes = len(values) - len(set(values))
            if dupes:
                offenders[f"{table}.{col.name}"] = dupes
    assert offenders == {}, f"duplicate values in declared-unique columns: {offenders}"


def test_no_fir_number_is_issued_twice(dataset):
    """CrimeNo is the number on the paper FIR and the one an officer types into the
    console. Two rows sharing it makes an exact lookup ambiguous, which is the one
    thing an exact lookup must not be."""
    numbers = [r["CrimeNo"] for r in _rows("CaseMaster", ["CrimeNo"])]
    assert len(numbers) == len(set(numbers))
    assert all(numbers), "a FIR with no number cannot be looked up"


def test_a_transaction_appears_once(dataset):
    txns = [r["TxnID"] for r in _rows("vx_txn", ["TxnID"])]
    assert len(txns) == len(set(txns))


def test_an_account_appears_once(dataset):
    accts = [r["AccountID"] for r in _rows("vx_account", ["AccountID"])]
    assert len(accts) == len(set(accts))


# TRANSFERRED_TO is the one edge type that is legitimately repeated: it carries ONE ROW
# PER TRANSACTION, so acct:13 -> acct:10 appearing twice means two payments were made
# (TxnID 3 and 26), each with its own EdgeID, amount and date. Collapsing them would
# delete money from the trail. `load_graph()` builds a MultiDiGraph, which is what makes
# that representable — a DiGraph would silently keep only the last one.
#
# This was the first hypothesis of the Phase 1 duplication audit and it was wrong; the
# constant is written down here so the next person does not re-derive it from a failing
# assertion.
_PER_EVENT_EDGE_TYPES = {"TRANSFERRED_TO", "INVOLVED_IN"}


def test_the_graph_holds_no_duplicate_relationship_edge(dataset):
    """A repeated relationship edge double-counts in every weighted measure the graph
    feeds: CO_ACCUSED_WITH weight, PageRank, betweenness, and the community assignment
    the console labels a person with. Per-event edge types are excluded by name, not by
    a blanket DISTINCT — see _PER_EVENT_EDGE_TYPES."""
    edges = [(r["SrcId"], r["DstId"], r["EdgeType"]) for r in
             _rows("vx_graph_edge", ["SrcId", "DstId", "EdgeType"])
             if r["EdgeType"] not in _PER_EVENT_EDGE_TYPES]
    assert len(edges) == len(set(edges)), (
        f"{len(edges) - len(set(edges))} duplicate relationship edges in vx_graph_edge")


def test_every_transfer_edge_is_backed_by_a_transaction(dataset):
    """The other half of the rule above: TRANSFERRED_TO may repeat, but only as many
    times as vx_txn says money actually moved. More edges than transactions is the
    duplication that would otherwise hide behind 'it is allowed to repeat'."""
    import collections

    edges = collections.Counter(
        (r["SrcId"], r["DstId"]) for r in _rows("vx_graph_edge", ["SrcId", "DstId", "EdgeType"])
        if r["EdgeType"] == "TRANSFERRED_TO")
    txns = collections.Counter(
        (f'acct:{r["SrcAccountID"]}', f'acct:{r["DstAccountID"]}')
        for r in _rows("vx_txn", ["SrcAccountID", "DstAccountID"])
        if r["SrcAccountID"] is not None and r["DstAccountID"] is not None)
    assert edges == txns, (
        "transfer edges and transactions disagree: "
        f"{sum((edges - txns).values())} unbacked edge(s), "
        f"{sum((txns - edges).values())} unrepresented transaction(s)")


def test_one_accused_row_resolves_to_exactly_one_person(dataset):
    """vx_accused_identity is the identity layer's whole output. An AccusedMasterID
    mapped to two PersonUIDs would put one case in two people's histories."""
    links = _rows("vx_accused_identity", ["AccusedMasterID", "PersonUID"])
    seen = [l["AccusedMasterID"] for l in links]
    assert len(seen) == len(set(seen))


# --- referential consistency ------------------------------------------------------

def test_every_accused_row_belongs_to_a_real_case(dataset):
    cases = {r["CaseMasterID"] for r in _rows("CaseMaster", ["CaseMasterID"])}
    orphans = [r["AccusedMasterID"] for r in _rows("Accused", ["AccusedMasterID", "CaseMasterID"])
               if r["CaseMasterID"] not in cases]
    assert orphans == []


def test_every_resolved_identity_points_at_a_real_person_and_a_real_accused_row(dataset):
    people = {r["PersonUID"] for r in _rows("vx_person", ["PersonUID"])}
    accused = {r["AccusedMasterID"] for r in _rows("Accused", ["AccusedMasterID"])}
    bad = [l for l in _rows("vx_accused_identity", ["AccusedMasterID", "PersonUID"])
           if l["PersonUID"] not in people or l["AccusedMasterID"] not in accused]
    assert bad == []


def test_every_case_is_filed_at_a_real_station_in_a_real_district(dataset):
    units = {r["UnitID"]: r["DistrictID"] for r in _rows("Unit", ["UnitID", "DistrictID"])}
    districts = {r["DistrictID"] for r in _rows("District", ["DistrictID"])}
    bad_station, bad_district = [], []
    for r in _rows("CaseMaster", ["CaseMasterID", "PoliceStationID"]):
        if r["PoliceStationID"] not in units:
            bad_station.append(r["CaseMasterID"])
        elif units[r["PoliceStationID"]] not in districts:
            bad_district.append(r["CaseMasterID"])
    assert bad_station == [] and bad_district == []


def test_every_officer_belongs_to_a_real_station(dataset):
    units = {r["UnitID"] for r in _rows("Unit", ["UnitID"])}
    bad = [r["EmployeeID"] for r in _rows("Employee", ["EmployeeID", "UnitID"])
           if r["UnitID"] not in units]
    assert bad == []


def test_every_transaction_moves_between_two_real_accounts(dataset):
    accts = {r["AccountID"] for r in _rows("vx_account", ["AccountID"])}
    bad = [r["TxnID"] for r in _rows("vx_txn", ["TxnID", "SrcAccountID", "DstAccountID"])
           if r["SrcAccountID"] not in accts or r["DstAccountID"] not in accts]
    assert bad == []


def test_no_transaction_pays_an_account_from_itself(dataset):
    self_paying = [r["TxnID"] for r in
                   _rows("vx_txn", ["TxnID", "SrcAccountID", "DstAccountID"])
                   if r["SrcAccountID"] == r["DstAccountID"]]
    assert self_paying == []


def test_every_graph_person_node_is_a_resolved_person(dataset):
    """Node ids carry their own type (`person:412`). A person node with no vx_person
    row behind it is a node the console can render and no endpoint can open."""
    people = {str(r["PersonUID"]) for r in _rows("vx_person", ["PersonUID"])}
    dangling = set()
    for r in _rows("vx_graph_edge", ["SrcId", "DstId"]):
        for node in (r["SrcId"], r["DstId"]):
            if node and node.startswith("person:") and node.split(":", 1)[1] not in people:
                dangling.add(node)
    assert dangling == set()


def test_every_graph_case_node_is_a_real_case(dataset):
    cases = {str(r["CaseMasterID"]) for r in _rows("CaseMaster", ["CaseMasterID"])}
    dangling = set()
    for r in _rows("vx_graph_edge", ["SrcId", "DstId"]):
        for node in (r["SrcId"], r["DstId"]):
            if node and node.startswith("case:") and node.split(":", 1)[1] not in cases:
                dangling.add(node)
    assert dangling == set()


# --- semantics that a foreign key cannot express ----------------------------------

def test_the_money_graph_is_directed_and_stays_that_way(dataset):
    """TRANSFERRED_TO is the one edge the graph never symmetrises. If sync_graph writes
    the mirror edge the way it does for CO_ACCUSED_WITH, the Sankey shows a payment that
    never happened.

    "Directed" is not the same as "antisymmetric": two accounts really can pay each
    other, and 6 such pairs exist in this dataset. So the check is that every reverse
    edge is backed by a reverse *transaction* — a mirror sync_graph invented would have
    no transaction behind it, and blanket mirroring would make every edge reciprocal.
    """
    transfers = {(r["SrcId"], r["DstId"]) for r in
                 _rows("vx_graph_edge", ["SrcId", "DstId", "EdgeType"])
                 if r["EdgeType"] == "TRANSFERRED_TO"}
    real = {(f'acct:{r["SrcAccountID"]}', f'acct:{r["DstAccountID"]}')
            for r in _rows("vx_txn", ["SrcAccountID", "DstAccountID"])}

    mirrored = {(a, b) for a, b in transfers if (b, a) in transfers}
    assert mirrored <= real, "a reverse money edge exists with no transaction behind it"
    assert mirrored != transfers, "every transfer is reciprocal — the graph is symmetrised"


def test_no_case_is_registered_in_the_future_relative_to_its_own_chargesheet(dataset):
    filed = {r["CaseMasterID"]: ds.to_dt(r["CrimeRegisteredDate"])
             for r in _rows("CaseMaster", ["CaseMasterID", "CrimeRegisteredDate"])}
    backwards = []
    for cs in _rows("ChargesheetDetails", ["CaseMasterID", "csdate"]):
        d, f = ds.to_dt(cs["csdate"]), filed.get(cs["CaseMasterID"])
        if d and f and d < f:
            backwards.append(cs["CaseMasterID"])
    assert backwards == [], f"chargesheet dated before the FIR: {backwards[:5]}"


def test_a_person_carries_at_least_one_accused_row(dataset):
    """vx_person exists only to be the thing Accused rows resolve to. A person with no
    rows behind them was invented by the resolver rather than reconstructed."""
    linked = {l["PersonUID"] for l in _rows("vx_accused_identity", ["PersonUID"])}
    orphan_people = [r["PersonUID"] for r in _rows("vx_person", ["PersonUID"])
                     if r["PersonUID"] not in linked]
    assert orphan_people == []


def test_district_codes_round_trip_through_the_canonical_gazetteer(dataset):
    """The v11 bug was a producer emitting `str(DistrictID)` where every consumer parsed
    `KAnn`. One inconsistent identifier is enough to lose a whole turn."""
    from data.districts import canonical_code, canonical_name
    from data.generator.refdata import district_id

    for r in _rows("District", ["DistrictID", "DistrictName"]):
        code = canonical_code(r["DistrictName"])
        assert code, f"district {r['DistrictName']!r} is not in the gazetteer"
        assert canonical_name(code) is not None
        assert district_id(code) == r["DistrictID"], (
            f"{r['DistrictName']}: gazetteer says {district_id(code)}, "
            f"the District table says {r['DistrictID']}")


# --- determinism ------------------------------------------------------------------

def test_the_generator_is_deterministic_under_a_fixed_seed():
    """Two runs at the same seed must produce the same records. Without this, no
    measurement taken against generated data is reproducible — including the F1 the
    entity resolver is judged on."""
    import random

    from data.generator.build import generate

    a = generate(random.Random(1234), 40)
    b = generate(random.Random(1234), 40)

    assert list(a.tables) == list(b.tables)
    for table in a.tables:
        assert a.tables[table] == b.tables[table], f"{table} differs between two seeded runs"


def test_repeating_a_query_returns_the_same_rows_in_the_same_order(dataset):
    """Ordering is not incidental here: the console renders the first N rows, and an
    unstable order makes the same question look like a different answer."""
    q = ('SELECT "CaseMasterID", "CrimeNo" FROM "CaseMaster" '
         'ORDER BY "CrimeRegisteredDate" DESC')
    first = ds.query(q)
    assert first == ds.query(q) == ds.query(q)


# --- counts -----------------------------------------------------------------------

def test_the_dataset_holds_what_the_fixture_asked_for(dataset):
    """A loader that silently drops rows is the failure mode this catches: every other
    test would still pass on a smaller dataset."""
    from conftest import TEST_CASES

    assert ds.scalar('SELECT COUNT("CaseMasterID") AS c FROM "CaseMaster"') == TEST_CASES
    assert ds.scalar('SELECT COUNT("AccusedMasterID") AS c FROM "Accused"') > 0
    assert ds.scalar('SELECT COUNT("PersonUID") AS c FROM "vx_person"') > 0
    # More Accused rows than people is the whole premise of the identity layer: if they
    # were equal, nothing was ever resolved and every offender is still a first-timer.
    assert (ds.scalar('SELECT COUNT("AccusedMasterID") AS c FROM "Accused"')
            > ds.scalar('SELECT COUNT("PersonUID") AS c FROM "vx_person"'))
