"""What the generated dataset must be true of, or the models downstream are meaningless.

Every property here is one that a model already found the hard way. A dataset can be
perfectly valid — every foreign key resolving, every row well-formed — and still be useless,
because it contains no signal for the thing you are asking a model to learn. These are the
signals, asserted.
"""
import math
from collections import Counter

import pytest

from data import ds, queries


# ---------------------------------------------------------------- referential integrity
def test_no_orphans_anywhere_in_the_er(dataset):
    """Every child row's parent exists. The ER declares these; nothing enforces them —
    Data Store has no foreign keys, so the generator is the only thing standing between us
    and a case that cites a station that was never created."""
    checks = [
        ("Accused", "CaseMasterID", "CaseMaster", "CaseMasterID"),
        ("Victim", "CaseMasterID", "CaseMaster", "CaseMasterID"),
        ("ComplainantDetails", "CaseMasterID", "CaseMaster", "CaseMasterID"),
        ("ActSectionAssociation", "CaseMasterID", "CaseMaster", "CaseMasterID"),
        ("ChargesheetDetails", "CaseMasterID", "CaseMaster", "CaseMasterID"),
        ("ArrestSurrender", "AccusedMasterID", "Accused", "AccusedMasterID"),
        ("CaseMaster", "PoliceStationID", "Unit", "UnitID"),
        ("CaseMaster", "PolicePersonID", "Employee", "EmployeeID"),
        ("Unit", "DistrictID", "District", "DistrictID"),
    ]
    for child, fk, parent, pk in checks:
        orphans = ds.scalar(
            f'SELECT COUNT("{fk}") AS c FROM "{child}" '
            f'WHERE "{fk}" NOT IN (SELECT "{pk}" FROM "{parent}")')
        assert orphans == 0, f"{orphans} orphaned {child}.{fk} -> {parent}.{pk}"


def test_crime_number_is_the_ers_18_digit_composite(dataset):
    """1 category + 4 district + 4 unit + 4 year + 5 serial. The number on the paper FIR."""
    rows = ds.query('SELECT "CrimeNo", "CaseNo" FROM "CaseMaster" LIMIT 50')
    for r in rows:
        assert len(r["CrimeNo"]) == 18 and r["CrimeNo"].isdigit(), r["CrimeNo"]
        assert r["CrimeNo"].endswith(r["CaseNo"])       # CaseNo is its last 9 digits


def test_crime_numbers_are_unique(dataset):
    nos = [r["CrimeNo"] for r in ds.query('SELECT "CrimeNo" FROM "CaseMaster"')]
    assert len(nos) == len(set(nos))


# ------------------------------------------------------------------------ the signals
def test_a_prior_record_actually_predicts_reoffending(dataset):
    """Preferential attachment, without which recidivism is unlearnable.

    Sample offenders uniformly and a prior record predicts nothing — the recidivism model
    then correctly learns there is no signal, scores ~0.5 AUC, and looks broken when it is
    in fact right. Real offending is heavily skewed. Assert the skew exists.
    """
    counts = Counter()
    for r in ds.query('SELECT "PersonUID" FROM "vx_accused_identity"'):
        counts[r["PersonUID"]] += 1

    offences = sorted(counts.values(), reverse=True)
    assert len(offences) > 20
    top_decile = offences[:max(1, len(offences) // 10)]
    share = sum(top_decile) / sum(offences)
    assert share > 0.25, (
        f"the top 10% of offenders account for only {share:.0%} of offences — "
        f"the distribution is too flat for a prior to predict anything")


def test_offenders_form_crews_not_a_random_graph(dataset):
    """Louvain's precondition, and it is easy to destroy.

    Drawing each co-accused independently makes co-offending a random graph over the active
    offenders — and a random graph has no community structure, so Louvain puts everyone in
    one community. That is a true statement about the data and a useless one about crime.
    """
    from data.gds import co_offending
    import networkx as nx

    g = co_offending()
    assert g.number_of_edges() > 0, "nobody co-offended with anybody"

    communities = nx.community.louvain_communities(g, weight="weight", seed=0)
    sizes = sorted((len(c) for c in communities), reverse=True)
    assert len(communities) >= 3, f"only {len(communities)} communities: {sizes}"
    assert sizes[0] < 0.8 * g.number_of_nodes(), (
        f"one community holds {sizes[0]} of {g.number_of_nodes()} people — "
        f"the co-offending graph has no crew structure")


def test_incidents_cluster_rather_than_scatter_uniformly(dataset):
    """DBSCAN/KDE's precondition. Placing incidents uniformly inside a district leaves no
    hotspot to find, and the hotspot model then correctly reports none."""
    from data.generator.refdata import district_id
    from data.districts import all_districts

    # the busiest district, which is where a hotspot should be most obvious
    counts = queries.case_counts_by_district()
    did = max(counts, key=counts.get)
    pts = [(r["latitude"], r["longitude"])
           for r in queries.cases_in_district(did)
           if r["latitude"] is not None]
    assert len(pts) >= 20

    # Nearest-neighbour distances under clustering are far shorter than under a uniform
    # scatter over the same bounding box. Compare the two directly.
    import numpy as np
    a = np.array(pts)
    d = np.linalg.norm(a[:, None, :] - a[None, :, :], axis=-1)
    np.fill_diagonal(d, np.inf)
    observed = float(np.mean(d.min(axis=1)))

    span = a.max(axis=0) - a.min(axis=0)
    area = float(span[0] * span[1]) or 1e-9
    uniform = 0.5 * math.sqrt(area / len(pts))       # expected NN distance, uniform Poisson

    assert observed < 0.7 * uniform, (
        f"mean nearest-neighbour distance {observed:.5f} vs {uniform:.5f} expected under a "
        f"uniform scatter — the incidents are not clustered, so there is no hotspot to find")


# --------------------------------------------------------------------- identity, resolved
def test_every_accused_row_resolves_to_a_person(dataset):
    """vx_person has to be total over the record layer, or half the joins go silently empty.
    A man seen once is still a man."""
    accused = ds.scalar('SELECT COUNT("AccusedMasterID") AS c FROM "Accused"')
    mapped = ds.scalar('SELECT COUNT("AccusedMasterID") AS c FROM "vx_accused_identity"')
    assert accused == mapped > 0


def test_resolution_recovers_people_recorded_under_name_variants(dataset):
    """The payoff of the whole identity layer, measured against the generator's answer key.

    Not a smoke test: this is precision/recall over every pair, and it is the number the
    "has he been booked under a different spelling" feature rests on.
    """
    truth = dataset.accused_truth                    # AccusedMasterID -> TruePerson.uid
    got = {r["AccusedMasterID"]: r["PersonUID"] for r in
           ds.query('SELECT "AccusedMasterID", "PersonUID" FROM "vx_accused_identity"')}
    assert set(got) == set(truth)

    ids = sorted(truth)
    tp = fp = fn = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            same_truth = truth[a] == truth[b]
            same_got = got[a] == got[b]
            tp += same_truth and same_got
            fp += (not same_truth) and same_got
            fn += same_truth and (not same_got)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    assert f1 > 0.90, f"entity resolution F1 ={f1:.3f} (p={precision:.3f} r={recall:.3f})"


def test_a_habitual_offender_appears_under_more_than_one_spelling(dataset, habitual):
    """The live-demo moment, asserted: the same man, recorded three different ways."""
    names = {r["AccusedName"] for r in ds.query(
        'SELECT "Accused"."AccusedName" FROM "vx_accused_identity" '
        'JOIN "Accused" '
        '  ON "vx_accused_identity"."AccusedMasterID" = "Accused"."AccusedMasterID" '
        'WHERE "vx_accused_identity"."PersonUID" = :uid', {"uid": habitual["PersonUID"]})}
    assert len(names) > 1, f"the most-connected offender has only one recorded spelling"
