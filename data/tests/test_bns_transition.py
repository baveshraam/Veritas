"""The Bharatiya Nyaya Sanhita, 2023 replaced the IPC for every offence committed on
or after 2024-07-01. Before this fix, every generated case cited only the IPC —
anachronistic for the majority of this dataset's own date range (it runs to
2026-07-01), and the kind of detail a real police panel notices immediately.
"""
from datetime import date

from data import ds
from data.generator import refdata as rd


def test_a_pre_cutover_offence_still_cites_the_ipc():
    act, sections = rd.act_and_sections_for("Theft", date(2023, 1, 1), ("379", "380"))
    assert act == "IPC"
    assert sections == ("379", "380")


def test_a_post_cutover_offence_cites_the_bns_equivalent():
    act, sections = rd.act_and_sections_for("Theft", date(2025, 1, 1), ("379", "380"))
    assert act == "BNS"
    assert sections == ("303(2)", "305")


def test_the_cutover_date_itself_is_bns_not_ipc():
    act, _ = rd.act_and_sections_for("Theft", rd.BNS_CUTOVER, ("379",))
    assert act == "BNS"


def test_ndps_and_it_act_crime_types_are_unaffected_by_the_transition():
    """NDPS and the IT Act were not touched by the BNS — a narcotics or cyber-crime
    case cites the same section under either code, at any date."""
    act, sections = rd.act_and_sections_for("Narcotics", date(2026, 1, 1), ("20", "21"))
    assert (act, sections) == ("NDPS", ("20", "21"))
    act, sections = rd.act_and_sections_for("Cyber Crime", date(2026, 1, 1), ("66", "66C"))
    assert (act, sections) == ("IT", ("66", "66C"))


def test_every_ipc_section_actually_cited_by_the_priors_has_a_bns_equivalent():
    """A KeyError here means a crime-types.csv edit added an IPC section this module's
    _IPC_TO_BNS mapping doesn't cover yet — the loudest possible failure, on purpose:
    a silently-uncited BNS section would surface as generated cases quietly reverting
    to IPC, not as an error."""
    from data.priors import crime_types
    for p in crime_types():
        if rd.act_for(p.crime_type) != "IPC":
            continue
        rd.act_and_sections_for(p.crime_type, date(2026, 1, 1), p.ipc_sections)


def test_generated_dataset_actually_carries_both_codes(dataset):
    """End-to-end: a real generated dataset (spanning ~3 years up to 2026-07-01, so it
    straddles the 2024-07-01 cutover) must show real ActSectionAssociation rows under
    both codes, not just IPC left over from before this fix."""
    codes = {r["ActID"] for r in ds.query('SELECT DISTINCT "ActID" FROM "ActSectionAssociation"')}
    assert "IPC" in codes
    assert "BNS" in codes


def test_a_bns_case_never_cites_an_ipc_section_or_vice_versa(dataset):
    """Every ActSectionAssociation row's (ActID, SectionID) pair must be one refdata
    actually emits as a Section master row for that act — no orphaned mix of a BNS
    case citing a bare IPC section number left over from the old code path."""
    have = {(r["ActCode"], r["SectionCode"])
            for r in ds.query('SELECT "ActCode", "SectionCode" FROM "Section"')}
    used = ds.query('SELECT DISTINCT "ActID", "SectionID" FROM "ActSectionAssociation"')
    for r in used:
        assert (r["ActID"], r["SectionID"]) in have, r


def test_backfill_repairs_a_dataset_seeded_before_the_fix(dataset):
    """A live, already-seeded dataset predates this fix and has every case citing the
    IPC regardless of date — exactly what data.generator.section_backfill exists to
    repair in place, without touching case/accused/identity/financial/graph rows."""
    from data.generator.section_backfill import backfill_act_sections

    case_ids = [r["CaseMasterID"] for r in ds.query('SELECT "CaseMasterID" FROM "CaseMaster"')]
    ds.execute('DELETE FROM "ActSectionAssociation"')
    ds.insert("ActSectionAssociation", [
        {"CaseMasterID": cid, "ActID": "IPC", "SectionID": "379",
         "ActOrderID": 1, "SectionOrderID": 1}
        for cid in case_ids])
    before_ids = {r["CaseMasterID"] for r in ds.query('SELECT "CaseMasterID" FROM "CaseMaster"')}

    touched = backfill_act_sections()

    assert touched > 0
    codes = {r["ActID"] for r in ds.query('SELECT DISTINCT "ActID" FROM "ActSectionAssociation"')}
    assert "BNS" in codes            # some cases in this dataset postdate the cutover
    after_ids = {r["CaseMasterID"] for r in ds.query('SELECT "CaseMasterID" FROM "CaseMaster"')}
    assert before_ids == after_ids   # no case added, removed, or renumbered
