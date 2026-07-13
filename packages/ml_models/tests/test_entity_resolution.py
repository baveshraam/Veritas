"""Fellegi-Sunter (1969) — the model that makes the organizers' ER answerable at all.

End-to-end accuracy is measured in `data/tests/test_dataset.py`, against the generator's
answer key. What is tested here is the *mechanism*: the comparators, the blocking key, the
three-way decision rule, and the constraints that are easy to get wrong and that silently
destroy it when you do.
"""
import random

import pytest

from ml_models.entity_resolution.fellegi_sunter import (
    LINK_THRESHOLD,
    POSSIBLE_THRESHOLD,
    _jaro_winkler,
    _norm_key,
    _Rec,
    cluster,
    score_records,
)


def _rec(aid: int, case: int, name: str, patronym: str = "Bharath",
         year: int | None = 1985, gender: int = 1,
         lat: float = 12.97, lng: float = 77.59) -> _Rec:
    return _Rec(accused_id=aid, case_id=case, name=name, patronym=patronym,
                birth_year=year, gender=gender, lat=lat, lng=lng)


# ------------------------------------------------------------------------- comparators
def test_jaro_winkler_rewards_a_shared_prefix():
    """Romanisation drift is overwhelmingly in the tail — Ramesh/Ramesha, Geetha/Geeta —
    so Winkler's prefix bonus is exactly the right shape for Indian name variants."""
    assert _jaro_winkler("Ramesh", "Ramesha") > 0.9
    assert _jaro_winkler("Ramesh", "Ramesha") > _jaro_winkler("Ramesh", "Suresh")
    assert _jaro_winkler("Ramesh", "Ramesh") == 1.0
    assert _jaro_winkler("", "Ramesh") == 0.0


@pytest.mark.parametrize("a,b", [
    ("Ramesh", "Ramesha"),
    ("Geetha", "Geeta"),
    ("Moorthy", "Murthy"),
])
def test_variants_collapse_to_one_blocking_key(a, b):
    """Blocking sets a *recall ceiling*: a pair whose keys differ is never scored at all. A
    key that separates two spellings of one man means he can never be recovered — no
    threshold, no comparator, nothing downstream can repair it."""
    assert _norm_key(a) == _norm_key(b)


def test_the_blocking_key_still_separates_different_names():
    assert _norm_key("Ramesh") != _norm_key("Suresh")


# ---------------------------------------------------------------------- the decision rule
def test_two_accused_on_the_same_case_are_never_the_same_person():
    """A hard constraint, not a probability. Two rows on one FIR are two people by
    definition — the ER numbers them A1 and A2. Without this, the model cheerfully merges
    two co-accused brothers with similar names into one offender who was actually two.
    """
    recs = [_rec(1, case=7, name="Ramesh Gowda"),
            _rec(2, case=7, name="Ramesha Gowda")]
    _, links = score_records(recs)
    assert links == []


def test_the_decision_is_three_way_not_a_single_cutoff():
    """Fellegi-Sunter's actual contribution: link, non-link, and an explicit clerical-review
    band between them. Collapsing that to one threshold turns a principled model back into
    fuzzy string matching with extra steps."""
    assert 0 < POSSIBLE_THRESHOLD < LINK_THRESHOLD < 1


# ------------------------------------------------------------------------------ clustering
def test_clustering_is_transitive():
    """A links B, B links C -> one person, even if A and C were never directly compared.
    Union-find is what turns pairwise decisions into people."""
    recs = [_rec(1, 1, "Ramesh"), _rec(2, 2, "Ramesha"), _rec(3, 3, "Rameshaa")]
    assert len(set(cluster(recs, links=[(0, 1), (1, 2)]).values())) == 1


def test_every_record_gets_a_person_including_singletons():
    """vx_person must be total over the record layer or half the joins go silently empty.
    A man seen once is still a man."""
    recs = [_rec(1, 1, "Ramesh"), _rec(2, 2, "Suresh"), _rec(3, 3, "Mahesh")]
    uid = cluster(recs, links=[])
    assert len(uid) == 3 and len(set(uid.values())) == 3


def test_the_person_id_is_stable_across_reruns():
    """PersonUID is the cluster's lowest AccusedMasterID — deterministic, and traceable to a
    record that actually exists. A random id would change on every rebuild and break every
    citation that pointed at it. (`_load` returns rows ordered by AccusedMasterID, which is
    what makes "lowest index" and "lowest id" the same thing.)"""
    recs = [_rec(4, 1, "Ramesh"), _rec(7, 2, "Ramesha"), _rec(9, 3, "Rameshaa")]
    assert set(cluster(recs, links=[(0, 1), (1, 2)]).values()) == {4}


# ------------------------------------------------------------------- the population effect
def test_recovers_re_registrations_without_merging_strangers():
    """The failure that matters is not a missed link — it is a false one.

    A model that links too eagerly produces one enormous "person" accused of everything, and
    then every downstream feature (priors, co-offending, risk) is nonsense. Assert both
    directions against a population with a known number of re-registrations.

    This runs over a *population*, not a pair, because that is the only way Fellegi-Sunter
    can be run at all: the m and u weights are estimated by EM over the candidate set, so a
    two-record test would be asking the model to calibrate itself on a sample of two. Each
    person also gets their own coordinates and their variant re-registers near them — a
    population where everyone shares one location has no location signal to weight, and EM
    would correctly learn that the field is worthless.
    """
    rng = random.Random(3)
    first = ["Ramesh", "Suresh", "Mahesh", "Ganesh", "Umesh", "Naveen", "Kiran", "Anil"]
    last = ["Gowda", "Nayak", "Reddy", "Shetty", "Rao", "Patil", "Hegde", "Murthy"]

    people = [{
        "name": f"{rng.choice(first)} {rng.choice(last)}",
        "patronym": rng.choice(first),
        "year": rng.randint(1960, 2000),
        "lat": 12.0 + rng.uniform(0, 4),
        "lng": 75.0 + rng.uniform(0, 3),
    } for _ in range(80)]

    recs: list[_Rec] = []
    truth: dict[int, int] = {}
    aid = case = 0
    for uid, p in enumerate(people):
        aid += 1
        case += 1
        recs.append(_rec(aid, case, p["name"], p["patronym"], p["year"],
                         lat=p["lat"], lng=p["lng"]))
        truth[aid] = uid

    for uid in range(15):                     # 15 re-register under a spelling variant
        p = people[uid]
        aid += 1
        case += 1
        variant = p["name"].replace("sh", "sha", 1) if "sh" in p["name"] else p["name"] + "a"
        recs.append(_rec(aid, case, variant, p["patronym"], p["year"],
                         lat=p["lat"] + 0.02, lng=p["lng"] + 0.02))   # offends near home
        truth[aid] = uid

    _, links = score_records(recs)
    uid_of = cluster(recs, links)

    ids = sorted(truth)
    tp = fp = fn = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            same_truth, same_got = truth[a] == truth[b], uid_of[a] == uid_of[b]
            tp += same_truth and same_got
            fp += (not same_truth) and same_got
            fn += same_truth and (not same_got)

    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    assert precision >= 0.9, f"{fp} pairs of strangers were merged (precision {precision:.2f})"
    assert recall >= 0.6, f"recovered only {tp} of the 15 re-registrations"
