"""Conformance to the organizers' ER, and to the Data Store's limits.

The ER is a hard requirement, not a starting point: these tests exist so that a well-meaning
"improvement" to a table name or a column type fails loudly instead of quietly shipping a
schema we were not asked for.
"""
import pytest

from data.schema import ER_TABLES, TABLES, VX_TABLES, emit_sqlite

# Police_FIR_ER_Diagram.pdf, in full. Names exactly as the document spells them —
# including `inv_arrestsurrenderaccused` and `caste_master_id`.
ER_TABLE_NAMES = {
    "CaseMaster", "ComplainantDetails", "Victim", "Accused", "ArrestSurrender",
    "inv_arrestsurrenderaccused", "Act", "Section", "ActSectionAssociation",
    "CrimeHead", "CrimeSubHead", "CrimeHeadActSection", "ChargesheetDetails",
    "CaseCategory", "GravityOffence", "CaseStatusMaster", "OccupationMaster",
    "ReligionMaster", "CasteMaster", "Court", "State", "District", "UnitType", "Unit",
    "Rank", "Designation", "Employee",
}


def test_every_er_table_is_present_and_named_exactly():
    assert set(ER_TABLES) == ER_TABLE_NAMES


def test_our_additions_are_all_prefixed():
    """No one should ever have to guess which tables the organizers gave us."""
    assert all(t.startswith("vx_") for t in VX_TABLES)
    assert not any(t.startswith("vx_") for t in ER_TABLES)


def test_the_er_has_no_person_table():
    """The premise of the whole identity layer. If this ever fails, the ER changed and
    Fellegi-Sunter may no longer be necessary — which would be worth knowing."""
    assert "Person" not in ER_TABLES
    assert "person" not in {t.lower() for t in ER_TABLES}


def test_accused_personid_is_a_label_not_a_key():
    """The ER types Accused.PersonID as a per-case sort label ("A1"), not a foreign key.
    If this became an int we would be storing a cross-case identity the schema never had."""
    personid = next(c for c in ER_TABLES["Accused"] if c.name == "PersonID")
    assert personid.type == "varchar"
    assert not personid.unique


def test_caste_and_religion_are_stored_because_the_er_declares_them():
    """Storing is not scoring. They exist here and are read by no model — see
    ml_models.risk.features and the fairness rule in packages/policy."""
    cols = {c.name for c in ER_TABLES["ComplainantDetails"]}
    assert {"CasteID", "ReligionID"} <= cols


@pytest.mark.parametrize("table", sorted(TABLES))
def test_no_table_exceeds_the_data_store_column_cap(table):
    """A Data Store SELECT returns at most 20 columns. A table wider than that cannot be
    read in one query, and every read of it would silently need splitting."""
    assert len(TABLES[table]) <= 20, f"{table} has {len(TABLES[table])} columns"


def test_sqlite_ddl_covers_every_table():
    ddl = emit_sqlite()
    assert len(ddl) == len(TABLES)
    joined = " ".join(ddl)
    for table in TABLES:
        assert f'"{table}"' in joined
    # ROWID is emulated, so the same ZCQL runs on both backends.
    assert all("ROWID" in stmt for stmt in ddl)


def test_socioeconomic_omits_the_fields_no_real_source_publishes():
    """Unemployment and police-per-lakh do not exist at district level in any real Indian
    source. Adding them back would mean fabricating the causal layer's confounders."""
    cols = {c.name for c in VX_TABLES["vx_district_socioeconomic"]}
    assert "Unemployment" not in cols
    assert "PolicePerLakh" not in cols
    assert {"LiteracyRate", "UrbanRatio", "PovertyIndex", "MarginalWorkerRate"} <= cols
