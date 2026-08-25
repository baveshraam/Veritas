"""Investigation Copilot — cross-case discovery must explain itself, not just score.

North Star / Phase 2: "same crime type" must not silently pass as "genuinely similar
case", and a returned match must say WHY it was returned. These tests exercise the
real dataset fixture (identity resolution, financial layer, graph, and the vector
index all built) because `_similar_cases` is exactly the retrieval + explanation path
an officer sees in the Copilot brief.
"""
from data import ds

from rag_agent.copilot.brief import generate_copilot_brief


def test_similar_cases_carry_an_explanation_not_a_bare_score(indexed):
    """Every returned candidate must say why it was returned — a percentage alone
    (BUG-023's original defect: exposing an embedding score with no structured
    reason) does not tell an officer whether it's method, section, or district that
    actually matched."""
    case_id = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" LIMIT 1')[0]["CaseMasterID"]
    brief = generate_copilot_brief(str(case_id), "IG", "")

    for c in brief.similar_cases:
        assert "explanation" in c and c["explanation"]
        assert "matched_features" in c
        assert "similarity" in c
        # The explanation is either a list of real structured reasons, or an honest
        # statement that none were found — never silence, and never just a number.
        if c["matched_features"]:
            assert c["explanation"] != ""
        else:
            assert "narrative text similarity only" in c["explanation"]


def test_structurally_matched_cases_outrank_pure_narrative_matches(indexed):
    """A case sharing crime type/section/district/MO with the source case must not be
    ranked below one that only happens to embed close in narrative-text space — that
    is exactly how "same crime type" stopped being distinguishable from "genuinely
    similar case" in the first place."""
    case_id = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" LIMIT 1')[0]["CaseMasterID"]
    brief = generate_copilot_brief(str(case_id), "IG", "")

    strengths = [c["match_strength"] for c in brief.similar_cases]
    assert strengths == sorted(strengths, reverse=True), (
        "similar_cases is not ordered by structured match strength first")


def test_same_crime_type_alone_is_named_as_only_one_reason_among_several(indexed):
    """A same-crime-type-only match must be distinguishable from a match that also
    shares a section, district, or the case-specific MO clause — collapsing all of
    these into one similarity float is the defect this feature replaces."""
    cases = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" LIMIT 10')
    seen_multi_feature = False
    for row in cases:
        brief = generate_copilot_brief(str(row["CaseMasterID"]), "IG", "")
        for c in brief.similar_cases:
            if c["match_strength"] > 1:
                seen_multi_feature = True
                assert ";" in c["explanation"], "multiple reasons must read as multiple reasons"
    assert seen_multi_feature, (
        "no sampled case had a similar-case match on more than one structured "
        "feature — narrative diversity or the explanation logic may be broken")
