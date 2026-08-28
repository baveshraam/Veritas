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


def test_narratives_do_not_collapse_to_one_shape_per_crime_type(dataset):
    """BUG-023's regression guard. Measured live: 60/60 sampled cases per crime type
    reduced to exactly one narrative shape once date/district were normalised out — 12
    of 20 crime types had a fixed fallback string with zero descriptive content at
    all. No test caught it, because nothing checked BriefFacts content beyond exact-
    string uniqueness. This asserts real per-crime-type variety, for every crime type
    present in the sample, not just the ones that happened to have MO text before.
    """
    rows = ds.query('SELECT "CrimeMinorHeadID", "BriefFacts" FROM "CaseMaster"')
    counts: dict = {}
    shapes: dict = {}
    for r in rows:
        # Normalise out the one genuinely case-identifying fact this check isn't
        # about (the date) so two truly-identical-shape narratives can't hide behind
        # a different date; district/time/MO/offender-count all stay in the string.
        shape = r["BriefFacts"].split("district. ", 1)[-1]
        ct = r["CrimeMinorHeadID"]
        counts[ct] = counts.get(ct, 0) + 1
        shapes.setdefault(ct, set()).add(shape)

    assert len(shapes) >= 15, f"only {len(shapes)} crime subtypes appear in this sample"
    # Only crime types with enough occurrences for diversity to be statistically
    # meaningful — a subtype that drew exactly 1 case in this small fixture can only
    # ever show 1 shape, and that is a sample-size artifact, not a collapsed template.
    testable = {k: v for k, v in shapes.items() if counts[k] >= 5}
    assert testable, "no crime subtype had enough occurrences to test diversity"
    thin = {k: len(v) for k, v in testable.items() if len(v) < 2}
    assert not thin, (
        f"{len(thin)} crime subtype(s) with >=5 cases still collapse to one shape: {thin}")


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


# ------------------------------------------------------- narrative investigative signal
def test_a_narrative_states_the_facts_an_officer_would_actually_search_on(dataset):
    """`BriefFacts` is the ONLY free text in the schema, so it is the entire input to the
    vector index, to "similar cases", and to every semantic search the console runs. It
    used to state four things (date, crime type, district, one MO clause) and nothing
    else — measured on the live 10,000-case dataset, that produced 592 distinct strings
    once the date was normalised out, with one template covering 520 cases.

    The facts asserted here are the ones an investigator types into a search box and the
    ones that make one case distinguishable from another, and every one of them is a
    column this same row already carries. None was reachable from the text before.
    """
    rows = ds.query('SELECT "CaseMasterID", "BriefFacts", "CaseStatusID" FROM "CaseMaster"')
    texts = [r["BriefFacts"] for r in rows if r["BriefFacts"]]
    assert texts

    stations = {u["UnitName"] for u in ds.query('SELECT "UnitName" FROM "Unit"')}
    assert sum(any(s and s in t for s in stations) for t in texts) == len(texts), \
        "a narrative that does not name the registering station cannot be searched by station"

    # The sections invoked. This is what lets the lexical half of hybrid retrieval answer
    # "IPC 457" — exactly what an investigator types and exactly what a dense embedding
    # cannot represent.
    assert sum("under section" in t for t in texts) == len(texts)

    # The closing sentence follows the case's OWN status. Every case previously ended with
    # "Investigation is being carried out as per procedure." — on a convicted case that is
    # not merely repetitive, it is false.
    from data.generator.build import _CLOSINGS
    for r in rows:
        if not r["BriefFacts"]:
            continue
        expected = _CLOSINGS.get(int(r["CaseStatusID"]), _CLOSINGS[1])
        assert r["BriefFacts"].endswith(tuple(expected)), (
            "case %s (status %s) ends with a closing belonging to a different status: %r"
            % (r["CaseMasterID"], r["CaseStatusID"], r["BriefFacts"][-70:]))


def test_a_named_locality_is_the_activity_centre_the_coordinates_actually_fall_in(dataset):
    """The spatial layer and the text layer must describe the same fact.

    Activity centres are the only real spatial structure in this dataset — they are why
    KDE and DBSCAN find anything at all — but they had no name, so nothing about them
    reached the text an officer searches: two burglaries 300m apart in one market were,
    as far as retrieval was concerned, unrelated. This asserts the naming is *derived
    from the coordinates on the row*, not drawn alongside them, so the narrative and the
    hotspot on the map cannot disagree.
    """
    import re

    from data.districts import all_districts
    from data.generator.geo import locality

    code_for = {d.name: d.code for d in all_districts()}
    rows = ds.query(
        'SELECT "CaseMaster"."BriefFacts", "CaseMaster"."latitude", '
        '       "CaseMaster"."longitude", "District"."DistrictName" AS "district" '
        'FROM "CaseMaster" '
        'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
        'JOIN "District" ON "Unit"."DistrictID" = "District"."DistrictID"')

    named = 0
    for r in rows:
        expected = locality(float(r["latitude"]), float(r["longitude"]),
                            code_for[r["district"]])
        m = re.search(r" near ([^,]+),", r["BriefFacts"])
        assert (m.group(1) if m else "") == expected, (
            "narrative says %r but the coordinates fall in %r"
            % (m.group(1) if m else "(no locality)", expected))
        named += bool(expected)

    # A background incident genuinely did not happen at an activity centre and must stay
    # unnamed — inventing a locality for it would fabricate the one fact this layer
    # exists to record.
    assert 0.5 < named / len(rows) < 0.95, (
        "%d/%d narratives name a locality — either the background draws are being named "
        "(invention) or the clustered ones are not (no signal)" % (named, len(rows)))


def test_a_repeat_offenders_method_carries_across_their_own_cases(dataset):
    """An offender who breaks in the same way twice is what an investigator is actually
    looking for, and it is what makes "cases with the same modus operandi as this one" a
    lead rather than noise. The generator used to give the MO an independent draw per
    case, so a crew's five burglaries described five unrelated methods.

    Asserted against a PERMUTATION NULL rather than an absolute threshold, because an
    absolute one proves nothing here: MO variants are drawn per crime type, so any two
    cases of a type already agree a third of the time by chance. Reshuffling the same MO
    labels among the same cases *within each crime type* destroys exactly one thing — the
    tie to the offender — and leaves every other structure (crime-type mix, how many
    cases each person has) identical. Beating that null is evidence of the tie itself.
    """
    import collections
    import random

    from data.generator.build import _MO_VARIANTS

    variants = [v for vs in _MO_VARIANTS.values() for v in vs]
    briefs = {r["CaseMasterID"]: r["BriefFacts"]
              for r in ds.query('SELECT "CaseMasterID", "BriefFacts" FROM "CaseMaster"')}
    ctype = {r["CaseMasterID"]: r["CrimeMinorHeadID"] for r in
             ds.query('SELECT "CaseMasterID", "CrimeMinorHeadID" FROM "CaseMaster"')}
    identity = {r["AccusedMasterID"]: r["PersonUID"] for r in
                ds.query('SELECT "AccusedMasterID", "PersonUID" FROM "vx_accused_identity"')}
    # A1 only: an MO habit belongs to whoever chose the method, and A1 is the ER's own
    # ordering label for the lead accused on a case.
    lead = {r["CaseMasterID"]: identity[r["AccusedMasterID"]]
            for r in ds.query('SELECT "CaseMasterID", "AccusedMasterID", "PersonID" '
                              'FROM "Accused"')
            if str(r["PersonID"]).upper() == "A1" and r["AccusedMasterID"] in identity}

    groups, pool = collections.defaultdict(list), collections.defaultdict(list)
    for cid, uid in lead.items():
        m = next((v for v in variants if v in (briefs.get(cid) or "")), None)
        if m:
            groups[(uid, ctype.get(cid))].append(m)
            pool[ctype.get(cid)].append(m)

    def modal_share(gs):
        num = den = 0
        for ms in gs.values():
            if len(ms) < 2:
                continue
            num += collections.Counter(ms).most_common(1)[0][1]
            den += len(ms)
        return (num / den if den else 0.0), den

    observed, n = modal_share(groups)
    assert n >= 20, "only %d case-attributions by a repeat lead offender — too few" % n

    nulls = []
    for seed in range(5):
        rnd = random.Random(seed)
        shuffled = {k: list(v) for k, v in pool.items()}
        for v in shuffled.values():
            rnd.shuffle(v)
        it = {k: iter(v) for k, v in shuffled.items()}
        nulls.append(modal_share(
            {k: [next(it[k[1]]) for _ in ms] for k, ms in groups.items()})[0])
    null = sum(nulls) / len(nulls)

    assert observed > null + 0.08, (
        "an offender's method does not carry across their own cases: observed modal-MO "
        "share %.4f vs permutation null %.4f (n=%d)" % (observed, null, n))


def test_a_group_offence_is_recorded_as_a_group_offence(dataset):
    """Dacoity is robbery "by five or more persons" (IPC 391); rioting requires an
    unlawful assembly, also of five (IPC 146/141).

    The accused count used to be drawn from one distribution for every crime type, which
    produced dacoities committed by a lone individual — a contradiction inside a single
    record, and one only visible once the narrative started stating the offender count
    out loud. It also flattened the co-offending graph: the two crime types that should
    contribute the densest cliques were contributing the same one-to-two person edges as
    a pickpocketing.
    """
    from data.generator.build import _GROUP_OFFENCE_SIZES

    counts = Counter(r["CaseMasterID"] for r in
                     ds.query('SELECT "CaseMasterID" FROM "Accused"'))
    rows = ds.query('SELECT "CaseMaster"."CaseMasterID", "CrimeSubHead"."CrimeHeadName" '
                    'AS "crime_type" FROM "CaseMaster" JOIN "CrimeSubHead" ON '
                    '"CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID"')
    checked = 0
    for r in rows:
        sizes = _GROUP_OFFENCE_SIZES.get(r["crime_type"])
        if not sizes:
            continue
        checked += 1
        assert counts.get(r["CaseMasterID"], 0) >= min(sizes), (
            "%s case %s has %d accused"
            % (r["crime_type"], r["CaseMasterID"], counts.get(r["CaseMasterID"], 0)))
    assert checked, "no group offence in the sample — this property was not exercised"
