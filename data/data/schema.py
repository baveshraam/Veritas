"""The one schema definition. Everything else is generated from it.

Two consumers:
  * `emit_iac()`      -> project-template.json, which `catalyst iac:import` turns
                         into real Catalyst Data Store tables. Data Store has no
                         CREATE TABLE — IaC is the only programmatic path in.
  * `emit_sqlite()`   -> DDL for the offline/test backend in `data.ds`.

Tables 1-27 are the Karnataka Police ER diagram, reproduced verbatim: their names,
their columns, their spelling (`caste_master_id`, `csdate`, `CrimeHeadName`). Do not
"improve" them — conformance to that document is a hard requirement.

`vx_*` tables are ours (Veritas eXtension). They are prefixed so that no one can ever
mistake our additions for the organizers' schema.

Two facts about Data Store that shape every table below:
  * Every table gets an auto-generated ROWID BigInt primary key. You cannot declare
    your own. So the ER's `CaseMasterID INT PK` is modelled as a unique Int column.
  * We do not use Data Store's native ForeignKey column type. It can only reference a
    parent's ROWID, but the ER's foreign keys reference business keys (CaseMasterID,
    ActCode). Using it would silently change the schema we were told to implement.
    Relationships are by value, as the ER declares them; ZCQL joins any two columns.
"""
from __future__ import annotations

from typing import Literal, NamedTuple

DataType = Literal["int", "bigint", "varchar", "text", "double", "boolean", "date", "datetime"]

# Data Store's own caps. varchar truncates at 255, text at 10_000.
_MAX_LEN: dict[str, int] = {"varchar": 255, "text": 10_000, "int": 10, "bigint": 19, "double": 17}


class Col(NamedTuple):
    name: str
    type: DataType
    unique: bool = False
    mandatory: bool = False


# --------------------------------------------------------------------------------------
# 1-27: the organizers' ER (Police_FIR_ER_Diagram.pdf), verbatim.
# --------------------------------------------------------------------------------------
ER_TABLES: dict[str, list[Col]] = {
    "CaseMaster": [
        Col("CaseMasterID", "int", unique=True, mandatory=True),
        # 1 category + 4 district + 4 unit + 4 year + 5 serial = 18 chars.
        Col("CrimeNo", "varchar", unique=True, mandatory=True),
        Col("CaseNo", "varchar"),                    # last 9 digits of CrimeNo
        Col("CrimeRegisteredDate", "date"),
        Col("PolicePersonID", "int"),                # -> Employee.EmployeeID
        Col("PoliceStationID", "int"),               # -> Unit.UnitID
        Col("CaseCategoryID", "int"),
        Col("GravityOffenceID", "int"),
        Col("CrimeMajorHeadID", "int"),              # -> CrimeHead.CrimeHeadID
        Col("CrimeMinorHeadID", "int"),              # -> CrimeSubHead.CrimeSubHeadID
        Col("CaseStatusID", "int"),
        Col("CourtID", "int"),
        Col("IncidentFromDate", "datetime"),
        Col("IncidentToDate", "datetime"),
        Col("InfoReceivedPSDate", "datetime"),
        Col("latitude", "double"),                   # lowercase in the ER; kept
        Col("longitude", "double"),
        Col("BriefFacts", "text"),
    ],
    "ComplainantDetails": [
        Col("ComplainantID", "int", unique=True, mandatory=True),
        Col("CaseMasterID", "int", mandatory=True),
        Col("ComplainantName", "varchar"),
        Col("AgeYear", "int"),
        Col("OccupationID", "int"),
        # CasteID/ReligionID exist because the ER declares them. They are never read by
        # any model — see the fairness rule in packages/policy. Storing != scoring.
        Col("ReligionID", "int"),
        Col("CasteID", "int"),                       # -> CasteMaster.caste_master_id
        Col("GenderID", "int"),
    ],
    "Victim": [
        Col("VictimMasterID", "int", unique=True, mandatory=True),
        Col("CaseMasterID", "int", mandatory=True),
        Col("VictimName", "varchar"),
        Col("AgeYear", "int"),
        Col("GenderID", "int"),
        Col("VictimPolice", "varchar"),              # "1"/"0" — VARCHAR in the ER, not BIT
    ],
    "Accused": [
        Col("AccusedMasterID", "int", unique=True, mandatory=True),
        Col("CaseMasterID", "int", mandatory=True),
        Col("AccusedName", "varchar"),
        Col("AgeYear", "int"),
        Col("GenderID", "int"),
        # NOT a foreign key. The ER defines it as a per-case sort label: "A1, A2, A3".
        # Cross-case identity does not exist in this schema — we derive it (vx_person).
        Col("PersonID", "varchar"),
    ],
    "ArrestSurrender": [
        Col("ArrestSurrenderID", "int", unique=True, mandatory=True),
        Col("CaseMasterID", "int", mandatory=True),
        Col("ArrestSurrenderTypeID", "int"),
        Col("ArrestSurrenderDate", "date"),
        Col("ArrestSurrenderStateId", "int"),        # ER's own casing: ...Id, not ...ID
        Col("ArrestSurrenderDistrictId", "int"),
        Col("PoliceStationID", "int"),
        Col("IOID", "int"),                          # -> Employee.EmployeeID
        Col("CourtID", "int"),
        Col("AccusedMasterID", "int"),
        Col("IsAccused", "boolean"),
        Col("IsComplainantAccused", "boolean"),
    ],
    # Appears only in the ER's Relationship Matrix, never in its table definitions.
    # One arrest event can link multiple accused, so the junction is required.
    "inv_arrestsurrenderaccused": [
        Col("ArrestSurrenderID", "int", mandatory=True),
        Col("AccusedMasterID", "int", mandatory=True),
    ],
    "Act": [
        Col("ActCode", "varchar", unique=True, mandatory=True),
        Col("ActDescription", "varchar"),
        Col("ShortName", "varchar"),
        Col("Active", "boolean"),
    ],
    # The ER declares no PK here; (ActCode, SectionCode) is the effective composite key.
    "Section": [
        Col("ActCode", "varchar", mandatory=True),
        Col("SectionCode", "varchar", mandatory=True),
        Col("SectionDescription", "varchar"),
        Col("Active", "boolean"),
    ],
    "ActSectionAssociation": [
        Col("CaseMasterID", "int", mandatory=True),
        # The ER types these INT but points them at Act.ActCode / Section.SectionCode,
        # which are VARCHAR. The referenced key wins — an INT here could not hold "NDPS".
        Col("ActID", "varchar", mandatory=True),
        Col("SectionID", "varchar", mandatory=True),
        Col("ActOrderID", "int"),
        Col("SectionOrderID", "int"),
    ],
    "CrimeHead": [
        Col("CrimeHeadID", "int", unique=True, mandatory=True),
        Col("CrimeGroupName", "varchar"),
        Col("Active", "boolean"),
    ],
    "CrimeSubHead": [
        Col("CrimeSubHeadID", "int", unique=True, mandatory=True),
        Col("CrimeHeadID", "int"),
        Col("CrimeHeadName", "varchar"),             # yes, "CrimeHeadName" on the SubHead
        Col("SeqID", "int"),
    ],
    "CrimeHeadActSection": [
        Col("CrimeHeadID", "int", mandatory=True),
        Col("ActCode", "varchar", mandatory=True),
        Col("SectionCode", "varchar"),
    ],
    "ChargesheetDetails": [
        Col("CSID", "int", unique=True, mandatory=True),
        Col("CaseMasterID", "int", mandatory=True),
        Col("csdate", "datetime"),
        Col("cstype", "varchar"),                    # A=Chargesheet, B=False, C=Undetected
        Col("PolicePersonID", "int"),
    ],
    "CaseCategory": [
        Col("CaseCategoryID", "int", unique=True, mandatory=True),
        Col("LookupValue", "varchar"),               # FIR, UDR, PAR, Zero FIR
    ],
    "GravityOffence": [
        Col("GravityOffenceID", "int", unique=True, mandatory=True),
        Col("LookupValue", "varchar"),               # Heinous, Non-Heinous
    ],
    "CaseStatusMaster": [
        Col("CaseStatusID", "int", unique=True, mandatory=True),
        Col("CaseStatusName", "varchar"),
    ],
    "CasteMaster": [
        Col("caste_master_id", "int", unique=True, mandatory=True),   # ER's snake_case
        Col("caste_master_name", "varchar"),
    ],
    "ReligionMaster": [
        Col("ReligionID", "int", unique=True, mandatory=True),
        Col("ReligionName", "varchar"),
    ],
    "OccupationMaster": [
        Col("OccupationID", "int", unique=True, mandatory=True),
        Col("OccupationName", "varchar"),
    ],
    "Court": [
        Col("CourtID", "int", unique=True, mandatory=True),
        Col("CourtName", "varchar"),
        Col("DistrictID", "int"),
        Col("StateID", "int"),
        Col("Active", "boolean"),
    ],
    "District": [
        Col("DistrictID", "int", unique=True, mandatory=True),
        Col("DistrictName", "varchar"),
        Col("StateID", "int"),
        Col("Active", "boolean"),
    ],
    "State": [
        Col("StateID", "int", unique=True, mandatory=True),
        Col("StateName", "varchar"),
        Col("NationalityID", "int"),
        Col("Active", "boolean"),
    ],
    "Unit": [
        Col("UnitID", "int", unique=True, mandatory=True),
        Col("UnitName", "varchar"),
        Col("TypeID", "int"),
        Col("ParentUnit", "int"),                    # self-reference -> Unit.UnitID
        Col("NationalityID", "int"),
        Col("StateID", "int"),
        Col("DistrictID", "int"),
        Col("Active", "boolean"),
    ],
    "UnitType": [
        Col("UnitTypeID", "int", unique=True, mandatory=True),
        Col("UnitTypeName", "varchar"),
        Col("CityDistState", "varchar"),             # City / District / State
        Col("Hierarchy", "int"),
        Col("Active", "boolean"),
    ],
    # "Rank" is a reserved word in most SQL dialects. It is the ER's table name, so it
    # stays; data.ds quotes every identifier for exactly this reason.
    "Rank": [
        Col("RankID", "int", unique=True, mandatory=True),
        Col("RankName", "varchar"),
        Col("Hierarchy", "int"),                     # lower = higher rank
        Col("Active", "boolean"),
    ],
    "Designation": [
        Col("DesignationID", "int", unique=True, mandatory=True),
        Col("DesignationName", "varchar"),           # Investigating Officer, SHO, ...
        Col("Active", "boolean"),
        Col("SortOrder", "int"),
    ],
    "Employee": [
        Col("EmployeeID", "int", unique=True, mandatory=True),
        Col("DistrictID", "int"),
        Col("UnitID", "int"),
        Col("RankID", "int"),
        Col("DesignationID", "int"),
        Col("KGID", "varchar"),                      # Karnataka Government ID
        Col("FirstName", "varchar"),
        Col("EmployeeDOB", "date"),
        Col("GenderID", "int"),
        Col("BloodGroupID", "int"),
        Col("PhysicallyChallenged", "boolean"),
        Col("AppointmentDate", "date"),
    ],
}

# --------------------------------------------------------------------------------------
# Ours. Prefixed vx_ so the organizers' schema stays unambiguous.
#
# The ER has no cross-case person identity: an `Accused` row belongs to exactly one FIR,
# and `Accused.PersonID` is a sort label. "Has this man been arrested before?" is
# therefore not answerable by lookup in their schema — it has to be *inferred*. That is
# what vx_person + vx_accused_identity hold: the output of Fellegi-Sunter record linkage
# over Accused rows. It is the single most load-bearing thing we add to their data model.
# --------------------------------------------------------------------------------------
VX_TABLES: dict[str, list[Col]] = {
    "vx_person": [
        Col("PersonUID", "int", unique=True, mandatory=True),
        Col("CanonicalName", "varchar"),
        Col("NameKn", "varchar"),
        Col("DOB", "date"),
        Col("GenderID", "int"),
        Col("RiskScore", "double"),
        Col("IsHabitualOffender", "boolean"),
        Col("GangAffiliation", "varchar"),
    ],
    "vx_accused_identity": [
        Col("AccusedMasterID", "int", unique=True, mandatory=True),
        Col("PersonUID", "int", mandatory=True),
        Col("MatchConfidence", "double"),            # Fellegi-Sunter agreement weight
    ],
    "vx_account": [
        Col("AccountID", "int", unique=True, mandatory=True),
        Col("PersonUID", "int"),
        Col("Bank", "varchar"),
        Col("AccountType", "varchar"),
        Col("OpenedDate", "date"),
    ],
    "vx_txn": [
        Col("TxnID", "int", unique=True, mandatory=True),
        Col("SrcAccountID", "int"),
        Col("DstAccountID", "int"),
        Col("Amount", "double"),
        Col("TxnDate", "datetime"),
        Col("Channel", "varchar"),
        Col("FlaggedSuspicious", "boolean"),
        Col("CaseMasterID", "int"),
    ],
    "vx_graph_edge": [
        Col("EdgeID", "int", unique=True, mandatory=True),
        Col("SrcId", "varchar", mandatory=True),
        Col("DstId", "varchar", mandatory=True),
        Col("EdgeType", "varchar", mandatory=True),
        Col("Weight", "double"),
        Col("Props", "text"),                        # JSON blob
    ],
    "vx_session": [
        Col("SessionID", "varchar", unique=True, mandatory=True),
        Col("EmployeeID", "int", mandatory=True),
        Col("ActivePersonUID", "int"),
        Col("ActiveCaseMasterID", "int"),
        Col("ActiveLocation", "varchar"),
        Col("ActiveDateFrom", "date"),
        Col("ActiveDateTo", "date"),
        Col("Language", "varchar"),
        Col("UpdatedAt", "datetime"),
    ],
    "vx_conversation_turn": [
        Col("TurnID", "int", unique=True, mandatory=True),
        Col("SessionID", "varchar", mandatory=True),
        Col("TurnIndex", "int", mandatory=True),
        Col("Role", "varchar"),                      # officer | assistant
        Col("Content", "text"),
        Col("CreatedAt", "datetime"),
    ],
    # Data Store has no RULE and no trigger, so the database cannot make the audit log
    # physically append-only. Instead each row carries the hash of the previous row:
    # ChainHash = sha256(PrevHash + ResponseHash). Tampering with or deleting any row
    # breaks every hash after it. The DB can't make it impossible; the chain makes it
    # undeniable. See data.audit.verify_chain().
    "vx_audit_log": [
        Col("AuditID", "int", unique=True, mandatory=True),
        Col("EmployeeID", "int", mandatory=True),
        Col("SessionID", "varchar"),
        Col("QueryText", "text"),
        Col("ResponseHash", "varchar"),
        Col("PrevHash", "varchar"),
        Col("ChainHash", "varchar"),
        Col("AgentTrace", "text"),                   # JSON
        Col("CreatedAt", "datetime"),
    ],
    # Real Census/NSSO ground truth, keyed to the ER's District.DistrictID.
    "vx_district_socioeconomic": [
        Col("DistrictID", "int", unique=True, mandatory=True),
        Col("Year", "int"),
        Col("LiteracyRate", "double"),
        Col("Unemployment", "double"),
        Col("PovertyIndex", "double"),
        Col("Population", "bigint"),
        Col("UrbanRatio", "double"),
        Col("PolicePerLakh", "double"),
    ],
}

TABLES: dict[str, list[Col]] = {**ER_TABLES, **VX_TABLES}


def emit_iac(project_name: str) -> dict:
    """project-template.json for `catalyst iac:import`.

    Data Store exposes no CREATE TABLE over API, CLI or SDK — the console is the only
    documented way in. IaC import is the exception, so the whole schema ships as one
    committed file instead of 36 tables of manual clicking.
    """
    datastore: list[dict] = []
    for table, cols in TABLES.items():
        datastore.append(
            {"type": "table", "name": table, "properties": {"table_name": table}, "dependsOn": []}
        )
        for c in cols:
            props: dict = {
                "column_name": c.name,
                "data_type": c.type,
                "is_unique": c.unique,
                "is_mandatory": c.mandatory,
            }
            if c.type in _MAX_LEN:
                props["max_length"] = _MAX_LEN[c.type]
            datastore.append(
                {
                    "type": "column",
                    "name": f"{table}-{c.name}",
                    "properties": props,
                    "dependsOn": [f"Datastore.table.{table}"],
                }
            )
    return {
        "name": project_name,
        "version": "1.0.0",
        "parameters": {},
        "components": {"Datastore": datastore},
    }


_SQLITE_TYPE = {
    "int": "INTEGER", "bigint": "INTEGER", "double": "REAL", "boolean": "INTEGER",
    "varchar": "TEXT", "text": "TEXT", "date": "TEXT", "datetime": "TEXT",
}


def emit_sqlite() -> list[str]:
    """DDL for data.ds's offline backend. ROWID is emulated so ZCQL runs unchanged."""
    ddl = []
    for table, cols in TABLES.items():
        defs = ['"ROWID" INTEGER PRIMARY KEY AUTOINCREMENT']
        for c in cols:
            line = f'"{c.name}" {_SQLITE_TYPE[c.type]}'
            if c.unique:
                line += " UNIQUE"
            if c.mandatory:
                line += " NOT NULL"
            defs.append(line)
        defs += ['"CREATEDTIME" TEXT', '"MODIFIEDTIME" TEXT']
        ddl.append(f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(defs)})')
    return ddl


if __name__ == "__main__":
    import json
    import sys

    n_er, n_vx = len(ER_TABLES), len(VX_TABLES)
    n_cols = sum(len(c) for c in TABLES.values())
    out = emit_iac(sys.argv[1] if len(sys.argv) > 1 else "Veritas")
    print(json.dumps(out, indent=2))
    print(
        f"\n{n_er} ER tables + {n_vx} vx tables = {len(TABLES)}; {n_cols} columns",
        file=sys.stderr,
    )
