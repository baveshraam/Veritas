"""The search box: what an officer types, and what must come back.

The defect these are written against is a single line — the old filter asked whether
the WHOLE query appeared inside ONE field, so every multi-word search returned nothing
while the register held the answer. Two words is not an edge case; it is how anybody
searches, and no test in this repo covered it.
"""
import pytest
from rag_agent import search as S


def test_tokenize_drops_the_words_that_carry_no_selectivity():
    assert S.tokenize("show me theft cases in mandya") == ["theft", "mandya"]
    assert S.tokenize("Find all the House Burglary FIRs") == ["house", "burglary"]
    # A query made only of stopwords keeps them: searching for "the" and finding
    # nothing is a better answer than searching for nothing and returning everything.
    assert S.tokenize("show me the cases") == ["show", "me", "the", "cases"]
    assert S.tokenize("") == []


def test_every_word_must_match_something_and_word_order_does_not_matter(dataset):
    """The bug, stated as a test. "theft mandya" is not a substring of the crime type,
    nor of the district, nor of any narrative — so the old per-field substring check
    returned nothing at all."""
    from data import ds
    row = ds.one('SELECT "DistrictName" FROM "District" '
                 'JOIN "Unit" ON "Unit"."DistrictID" = "District"."DistrictID" '
                 'JOIN "CaseMaster" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
                 'JOIN "CrimeSubHead" '
                 '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID" '
                 'WHERE "CrimeSubHead"."CrimeHeadName" = :ct', {"ct": "Theft"})
    if not row:
        pytest.skip("this dataset has no theft case to search for")
    district = row["DistrictName"]

    forward = S.search(f"theft {district}", "IG", "")
    reversed_ = S.search(f"{district} theft", "IG", "")
    assert forward, "a two-word search over two real fields found nothing"
    # A search box is not a sentence: word order carries no meaning in one.
    assert {h.id for h in forward} == {h.id for h in reversed_}
    top = forward[0]
    assert top.kind == "case"
    assert "crime" in top.why and "district" in top.why


def test_a_word_that_matches_nothing_excludes_the_row(dataset):
    """The AND is the whole point. An OR over tokens would return every theft case
    for "theft zzzznotaword", which reads as a successful search."""
    assert S.search("theft zzzznotaword", "IG", "") == []


def test_an_exact_fir_number_outranks_every_other_kind_of_match(dataset):
    from data import ds
    row = ds.one('SELECT "CrimeNo" FROM "CaseMaster"')
    hits = S.search(row["CrimeNo"], "IG", "")
    assert hits, "an exact FIR number found nothing"
    assert hits[0].ident == row["CrimeNo"]
    assert hits[0].why == ["exact FIR number"]


def test_a_person_is_findable_by_name(dataset, habitual):
    """People are the entity this platform exists to reconstruct, and the search box
    could not find one at all."""
    name = habitual["CanonicalName"]
    hits = S.search(name, "IG", "")
    people = [h for h in hits if h.kind == "person"]
    assert people, f"searching for {name!r} returned no person"
    assert people[0].title == name
    assert "case(s) you can see" in people[0].subtitle


def test_a_person_with_no_visible_case_is_not_findable_by_an_io(dataset, habitual):
    """A name is a record too. The identity layer must not become a way around the
    station filter — an IO who cannot read any of this person's cases must not be
    able to confirm the person exists by typing their name."""
    from data import ds
    from rag_agent.agents import sql_agent

    name = habitual["CanonicalName"]
    cases = sql_agent.person_record(str(habitual["PersonUID"]))
    theirs = {c["ps_code"] for c in cases}
    other = ds.one('SELECT "UnitID" FROM "Unit" WHERE "UnitID" NOT IN :mine',
                   {"mine": [int(p) for p in theirs]})
    if not other:
        pytest.skip("every station in this dataset holds one of this person's cases")

    hits = S.search(name, "IO", str(other["UnitID"]))
    assert not [h for h in hits if h.kind == "person"], \
        "an IO found a person none of whose cases they can read"


def test_a_bare_number_is_tried_as_both_a_section_and_a_station(dataset):
    """379 is a valid IPC section AND a valid station-code shape. Choosing between
    them by pattern picked one and silently dropped the other — "379" was read as a
    station, matched none, and fell through to whichever narratives held the digits."""
    from rag_agent.agents import sql_agent
    if not sql_agent.crime_heads_for_section("379"):
        pytest.skip("this dataset registers no offence under section 379")
    hits = S.search("379", "IG", "")
    assert any("section 379" in w for h in hits for w in h.why), \
        "a section number was not searched as a section"


def test_a_station_code_finds_that_stations_cases(dataset):
    from data import ds
    ps = str(ds.one('SELECT "PoliceStationID" FROM "CaseMaster"')["PoliceStationID"])
    hits = S.search(ps, "IG", "")
    station_hits = [h for h in hits if f"police station {ps}" in h.why]
    assert station_hits, f"searching for station {ps} found none of its cases"


def test_modus_operandi_text_is_searchable_but_ranks_below_structured_fields(dataset):
    """Narrative search is genuinely useful and genuinely the weakest signal: prose
    that happens to contain a word is not the same as a field the officer chose."""
    hits = S.search("theft", "IG", "", limit=40)
    by_why = {tuple(h.why): h.score for h in hits}
    structured = [s for w, s in by_why.items() if "crime" in w]
    narrative_only = [s for w, s in by_why.items() if w == ("modus operandi",)]
    if structured and narrative_only:
        assert min(structured) > max(narrative_only)


def test_search_never_returns_a_case_the_officer_cannot_see(dataset):
    from data import ds
    from policy import can_view_fir
    ps = str(ds.one('SELECT "PoliceStationID" FROM "CaseMaster"')["PoliceStationID"])
    for term in ("theft", "hurt", "mandya", "convicted"):
        for hit in S.search(term, "IO", ps, limit=30):
            if hit.kind != "case":
                continue
            row = ds.one('SELECT "PoliceStationID" FROM "CaseMaster" '
                         'WHERE "CaseMasterID" = :cid', {"cid": int(hit.id)})
            assert can_view_fir("IO", ps, str(row["PoliceStationID"])), \
                f"search leaked a case from another station for {term!r}"


def test_an_empty_query_returns_nothing_rather_than_everything(dataset):
    assert S.search("", "IG", "") == []
    assert S.search("   ", "IG", "") == []
