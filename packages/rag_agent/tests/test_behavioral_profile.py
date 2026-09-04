"""Evidence-backed behavioral profile — see behavioral_profile.py's own module
docstring for what this is and isn't (never demographic; distinct from a risk
score; every finding names the FIR numbers it rests on).
"""
import pytest

from rag_agent import behavioral_profile as bp
from rag_agent.agents import sql_agent


@pytest.fixture(autouse=True)
def _no_database_needed(request, monkeypatch):
    """Every test in this file except the real-dataset one below builds cases with
    made-up fir_ids ("1", "2", "3") that don't exist as real CaseMasterIDs — the
    two findings that genuinely need a database (time-of-day, stable associates)
    are stubbed out here so the MO/geo/escalation tests can exercise build_profile
    purely, without those fake ids ever reaching ds.query."""
    if request.node.name == "test_build_profile_runs_end_to_end_against_a_real_habitual_offender":
        return
    monkeypatch.setattr(bp, "_hours_by_case", lambda fir_ids: {})
    monkeypatch.setattr(bp, "_stable_associates", lambda person_uid, fir_ids: [])


def _case(fir_id, *, crime_type="Theft", district="Mandya", lat=12.5, lng=76.9,
         narrative="", date_filed="2025-01-01", fir_number=None):
    return {"fir_id": fir_id, "fir_number": fir_number or f"FIR-{fir_id}",
           "crime_type": crime_type, "district": district, "lat": lat, "lng": lng,
           "narrative": narrative, "date_filed": date_filed, "case_status": "Under Investigation"}


# --- pure helpers ----------------------------------------------------------------

def test_mo_clause_extracts_the_middle_sentence():
    narrative = ("On 04 Jan 2025, X PS registered a case of theft in Mandya "
                "district. Pickpocketing in a crowded market, in the afternoon, "
                "by a lone individual.")
    assert bp._mo_clause(narrative) == "Pickpocketing in a crowded market"


def test_haversine_of_the_same_point_is_zero():
    assert bp._haversine_km(12.5, 76.9, 12.5, 76.9) == 0.0


def test_time_bucket_covers_the_full_day():
    assert bp._time_bucket(3) == "early morning (before 5 AM)"
    assert bp._time_bucket(9) == "morning"
    assert bp._time_bucket(15) == "afternoon"
    assert bp._time_bucket(19) == "evening"
    assert bp._time_bucket(23) == "late night"


# --- build_profile: fewer than 3 cases is a history, not a pattern ---------------

def test_fewer_than_three_cases_produces_no_findings():
    cases = [_case("1"), _case("2")]
    assert bp.build_profile("999", cases) == []


# --- recurring method (does not need the database) -------------------------------

def test_a_recurring_mo_clause_is_reported_with_its_case_ids():
    mo = "A distinctive break-in through a rear service hatch"
    cases = [
        _case("1", narrative=f"On 1 Jan 2025, PS registered a case of theft in "
                             f"Mandya district. {mo}, in the afternoon."),
        _case("2", narrative=f"On 2 Feb 2025, PS registered a case of theft in "
                             f"Mandya district. {mo}, in the evening."),
        _case("3", narrative="On 3 Mar 2025, PS registered a case of theft in "
                             "Mandya district. A different method entirely, "
                             "at night."),
    ]
    findings = bp.build_profile("999", cases)
    mo_findings = [f for f in findings if "recurs" in f["claim"]]
    assert mo_findings, "a method repeated across 2 of 3 cases must be reported"
    assert set(mo_findings[0]["fir_ids"]) == {"1", "2"}


def test_no_recurring_mo_when_every_case_has_a_different_method():
    cases = [
        _case("1", narrative="On 1 Jan 2025, PS registered a case of theft in "
                             "Mandya district. Method A, in the afternoon."),
        _case("2", narrative="On 2 Feb 2025, PS registered a case of theft in "
                             "Mandya district. Method B, in the evening."),
        _case("3", narrative="On 3 Mar 2025, PS registered a case of theft in "
                             "Mandya district. Method C, at night."),
    ]
    findings = bp.build_profile("999", cases)
    assert not [f for f in findings if "recurs" in f["claim"]]


# --- geographic range --------------------------------------------------------------

def test_a_tight_geographic_cluster_is_reported_as_one_area():
    cases = [_case(str(i), lat=12.50 + i * 0.001, lng=76.90 + i * 0.001,
                   district="Mandya") for i in range(3)]
    findings = bp.build_profile("999", cases)
    geo = [f for f in findings if "radius" in f["claim"] or "district(s)" in f["claim"]]
    assert geo
    assert "radius" in geo[0]["claim"]


def test_a_wide_geographic_spread_names_every_district():
    cases = [
        _case("1", lat=12.5, lng=76.9, district="Mandya"),
        _case("2", lat=15.3, lng=75.1, district="Belagavi"),
        _case("3", lat=17.9, lng=79.5, district="Bidar"),
    ]
    findings = bp.build_profile("999", cases)
    geo = [f for f in findings if "district(s)" in f["claim"]]
    assert geo
    assert "Mandya" in geo[0]["claim"] and "Belagavi" in geo[0]["claim"]


# --- escalation, read only from the record's own gravity classification -----------

def test_escalation_reported_when_a_heinous_offence_follows_a_non_heinous_one():
    cases = [
        _case("1", crime_type="Theft", date_filed="2024-01-01"),
        _case("2", crime_type="Theft", date_filed="2024-06-01"),
        _case("3", crime_type="Murder", date_filed="2025-01-01"),
    ]
    findings = bp.build_profile("999", cases)
    esc = [f for f in findings if "severity has increased" in f["claim"]]
    assert esc
    assert esc[0]["fir_ids"] == ["1", "3"]


def test_no_escalation_claim_when_every_case_is_the_same_gravity():
    cases = [_case(str(i), crime_type="Theft", date_filed=f"2024-0{i+1}-01")
            for i in range(3)]
    findings = bp.build_profile("999", cases)
    assert not [f for f in findings if "severity has increased" in f["claim"]]


# --- end to end against the real generated dataset --------------------------------

def test_build_profile_runs_end_to_end_against_a_real_habitual_offender(habitual):
    pid = str(habitual["PersonUID"])
    cases = sql_agent.person_record(pid)
    findings = bp.build_profile(pid, cases)
    # A real habitual offender may or may not clear every individual bar (that
    # depends on chance in the generated data), but every finding that IS produced
    # must cite real case ids belonging to this person — never an invented one.
    case_ids = {c["fir_id"] for c in cases}
    for f in findings:
        assert set(f["fir_ids"]) <= case_ids, f
        assert f["claim"], "every finding must have real content"
