"""The one schema definition. Everything else is generated from it.

Two consumers:
  * `data.provision`  -> creates the real Catalyst Data Store tables over the Admin API.
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
#
# `double` was 17 on the theory that Data Store's max_length is a character cap on the
# value's serialized form. Checked live and that theory doesn't hold: a column-update
# request asking for a wider double (max_length 25, decimal_digits 12) came back
# `status: success` with the returned spec unchanged at max_length 15 / decimal_digits
# 4 — Data Store silently clamps a `double` column to that precision regardless of what
# a provisioning or update request asks for, so no number sent here changes it, and 17
# was never the actual constraint in the first place. The real defect this was chasing
# (small PageRank values coming back inflated by 10^4-10^5, explained in
# data.ds._sdk_row's docstring) is fixed by never writing a value the column can't
# represent, not by asking for a bigger column. Left at 17 — the number the platform
# already enforces on its own — so this dict doesn't claim a control that doesn't exist.
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
    # Catalyst Authentication identifies a user by email; the ER's Employee has no email
    # column, and we do not add one — the ER is a hard requirement, not a starting point.
    # So identity bridges to the record here. Catalyst says *who signed in*; Employee stays
    # authoritative for what they may see (role, station), which is what packages/policy
    # reads. A Catalyst account with no row here is not an officer and gets nothing.
    "vx_officer_identity": [
        Col("Email", "varchar", unique=True, mandatory=True),
        Col("EmployeeID", "int", mandatory=True),
    ],
    "vx_person": [
        Col("PersonUID", "int", unique=True, mandatory=True),
        Col("CanonicalName", "varchar"),
        Col("NameKn", "varchar"),
        Col("DOB", "date"),
        Col("GenderID", "int"),
        Col("RiskScore", "double"),
        Col("IsHabitualOffender", "boolean"),
        # Written by data.gds. The ER records no gang, so we do not invent one: the
        # "gang" is the Louvain community over co-offending, named as what it is.
        Col("GangAffiliation", "varchar"),      # "Community 47"
        Col("PageRank", "double"),
        Col("CommunityID", "int"),
        Col("Betweenness", "double"),
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
        Col("CaseMasterID", "int"),
        # Detector OUTPUT, written by packages/ml_models — never by the generator, or the
        # AML models would be scoring their own answer key. `Detector` names which one
        # fired (rule-based structuring / GNN), because a flag a court cannot attribute
        # to a method is not evidence.
        Col("FlaggedSuspicious", "boolean"),
        Col("FlagType", "varchar"),
        Col("Detector", "varchar"),
        Col("FlagConfidence", "double"),
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
    # One row per exchange, not per message: the PDF export and multi-turn resumption both
    # want the question and its answer together. `Payload` is the JSON side-car (citations,
    # visualization, evidence, agent trace) — see data.sessions for what happens when a
    # turn's payload exceeds Data Store's 10,000-char text cap.
    "vx_conversation_turn": [
        Col("TurnID", "int", unique=True, mandatory=True),
        Col("SessionID", "varchar", mandatory=True),
        Col("TurnIndex", "int", mandatory=True),
        Col("Query", "text"),
        Col("Language", "varchar"),
        Col("FinalAnswer", "text"),
        Col("Payload", "text"),
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
        Col("Endpoint", "varchar"),
        Col("QueryText", "text"),
        Col("RequestHash", "varchar"),
        Col("ResponseHash", "varchar"),
        Col("PrevHash", "varchar"),
        Col("ChainHash", "varchar"),
        Col("AgentTrace", "text"),                   # JSON
        Col("CreatedAt", "datetime"),
    ],
    # The persistent per-case investigation board (industry-gap #1: every mature
    # platform researched — Gotham, i2 Analyst's Notebook, Maltego — treats a
    # durable, editable case artifact as the analyst's core object; Veritas had none
    # that survived past one chat session). One row per pinned/authored item, not one
    # table per category: ItemType distinguishes an investigator's own note from a
    # pinned record from a derived finding from a lead, which the UI and the
    # conversational layer must never blur together (see docs/VERITAS_HANDOFF.md).
    # References the authoritative record by (RefType, RefID) rather than copying it —
    # Content/Confidence/SourceQuery are a snapshot of what the officer saw *at pin
    # time*, for a board that must still render even if the retrieval layer's own
    # transient evidence_items have since rotated out of the conversation store.
    "vx_case_board_item": [
        Col("BoardItemID", "int", unique=True, mandatory=True),
        Col("CaseMasterID", "int", mandatory=True),      # -> CaseMaster.CaseMasterID
        # "evidence" | "person" | "lead" | "note" | "question" | "finding"
        Col("ItemType", "varchar", mandatory=True),
        # Provenance of a pinned/derived item: the EvidenceItem.source_type it came
        # from (FIR_RECORD, GRAPH_RELATIONSHIP, ...) or "vx_person" for a pinned
        # person. NULL for a note/lead/question authored directly by the officer —
        # that absence IS the "this is a human note, not a record" signal the UI reads.
        Col("RefType", "varchar"),
        Col("RefID", "varchar"),                         # the fir_id/person_id/evidence_id
        Col("Content", "text", mandatory=True),           # the text the board renders
        Col("Confidence", "double"),                      # snapshot of EvidenceItem.confidence, if any
        Col("SourceQuery", "text"),                       # snapshot of EvidenceItem.source_query, if any
        # Lead lifecycle: "open" | "pursued" | "dismissed". Also reused for a
        # question's "open" | "resolved". Unused (NULL) for evidence/person/note/finding.
        Col("Status", "varchar"),
        Col("Reason", "text"),                            # disposition rationale, officer-entered
        Col("CreatedBy", "int", mandatory=True),          # -> Employee.EmployeeID
        Col("CreatedAt", "datetime", mandatory=True),
        Col("UpdatedBy", "int"),
        Col("UpdatedAt", "datetime"),
    ],
    # Real Census/NSSO ground truth, keyed to the ER's District.DistrictID.
    # The one table here that is not synthetic: Census of India 2011, PCA, verbatim.
    # Every column is a ratio of two real published counts. `unemployment` and
    # `police_per_lakh` are ABSENT on purpose — neither exists at district level in any
    # real source, and the causal layer would rather name an unmeasured confounder than
    # adjust for a fabricated one. See data.socioeconomic.
    "vx_district_socioeconomic": [
        Col("DistrictID", "int", unique=True, mandatory=True),
        Col("Year", "int"),
        Col("Population", "bigint"),
        Col("LiteracyRate", "double"),
        Col("UrbanRatio", "double"),
        Col("PovertyIndex", "double"),
        Col("MarginalWorkerRate", "double"),
        Col("YouthRatio", "double"),
    ],
}

TABLES: dict[str, list[Col]] = {**ER_TABLES, **VX_TABLES}


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
    n_cols = sum(len(c) for c in TABLES.values())
    print(
        f"{len(ER_TABLES)} ER tables + {len(VX_TABLES)} vx tables "
        f"= {len(TABLES)}; {n_cols} columns"
    )
