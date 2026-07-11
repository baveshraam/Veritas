"""Fellegi-Sunter linkage model — pure, no database.

The regressions locked in here each cost a real debugging pass:
  - EM on a blocked candidate set flips the FS axiom (m_name < u_name).
  - dob + dob_year as separate binary fields double-counts correlated evidence.
  - a candidate-set prior against a random-pair u links every name-blocked stranger.
All three surface as the same visible failure: two different people who happen to
share a birthday get merged into one identity.
"""
import random
from datetime import date

from ml_models.entity_resolution.fellegi_sunter import (
    _FIELDS, _Rec, _compare, _prior_match_prob, estimate_u, score_records,
)

_FIRST = ["Ramesh", "Suresh", "Manjunath", "Lakshmi", "Geetha", "Naveen",
          "Kavya", "Girish", "Mahesh", "Divya"]
_LAST = ["Gowda", "Reddy", "Patil", "Shetty", "Kulkarni", "Rao", "Bhat"]


def _population(seed: int = 3, n: int = 120, n_dupes: int = 10):
    """n distinct people + n_dupes re-registrations under a spelling variant."""
    rng = random.Random(seed)
    recs: list[_Rec] = []
    for i in range(n):
        recs.append(_Rec(
            person_id=f"p{i}",
            name_en=f"{rng.choice(_FIRST)} {rng.choice(_LAST)}",
            dob=date(rng.randint(1955, 2000), rng.randint(1, 12), rng.randint(1, 28)),
            gender=rng.choice("MF"),
            lat=12.9 + rng.uniform(-0.5, 0.5), lng=77.5 + rng.uniform(-0.5, 0.5)))

    truth: set[frozenset[str]] = set()
    for i, orig in enumerate(rng.sample(recs, n_dupes)):
        dup = _Rec(
            person_id=f"d{i}",
            name_en=orig.name_en.replace("esh", "esha").replace("Gowda", "Gouda"),
            dob=orig.dob,
            gender=orig.gender,
            lat=orig.lat, lng=orig.lng)          # same address — a re-registration
        if dup.name_en == orig.name_en:
            dup.name_en = orig.name_en + "a"
        recs.append(dup)
        truth.add(frozenset((dup.person_id, orig.person_id)))
    return recs, truth


def test_recovers_duplicates_without_false_positives():
    recs, truth = _population()
    results, _ = score_records(recs)
    links = {frozenset((r.person_id_a, r.person_id_b))
             for r in results if r.decision == "link"}
    assert truth <= links, f"missed duplicates: {len(truth - links)}"
    assert not (links - truth), f"false links: {links - truth}"


def test_same_birthday_strangers_are_not_merged():
    """The failure every earlier model variant produced: different name, different
    address, same DOB — must NOT link."""
    recs, _ = _population()
    shared = date(1977, 3, 9)
    recs.append(_Rec("x1", "Ganesh Patil", shared, "M", 14.08, 75.64))
    recs.append(_Rec("x2", "Venkatesh Deshpande", shared, "M", 15.42, 76.26))
    results, _ = score_records(recs)
    verdict = {frozenset((r.person_id_a, r.person_id_b)): r.decision for r in results}
    assert verdict.get(frozenset(("x1", "x2")), "non_link") != "link"


def test_em_respects_the_fellegi_sunter_axiom():
    recs, _ = _population()
    from ml_models.entity_resolution.fellegi_sunter import _candidate_pairs, _em
    pairs = sorted(_candidate_pairs(recs))
    gammas = [_compare(recs[a], recs[b]) for a, b in pairs]
    u = estimate_u(recs, random.Random(0))
    m, u, _ = _em(gammas, u, _prior_match_prob(len(recs)))
    for i, f in enumerate(_FIELDS):
        # strongest agreement must be likelier among matches than non-matches
        assert m[i][0] > u[i][0], f"axiom violated for {f}: m={m[i][0]} u={u[i][0]}"


def test_prior_is_a_cross_product_rate_not_a_candidate_rate():
    # must be tiny — it lives in the same space as the random-sampled u
    assert _prior_match_prob(600) < 0.01
    assert _prior_match_prob(1) == 0.0


def test_comparison_levels():
    a = _Rec("a", "Ramesh Gowda", date(1980, 5, 4), "M", 12.9, 77.5)
    same = _Rec("b", "Ramesha Gowda", date(1980, 5, 4), "M", 12.9, 77.5)
    assert _compare(a, same) == (0, 0, 0, 0)
    # transposed day -> DOB partial agreement, not disagreement
    keyed = _Rec("c", "Ramesh Gowda", date(1980, 5, 40 % 28 + 1), "M", 12.9, 77.5)
    assert _compare(a, keyed)[1] == 1
