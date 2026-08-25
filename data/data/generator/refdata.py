"""The ER's master/lookup tables, built deterministically.

Everything here is reference data, not synthetic crime: the 31 real Karnataka districts,
the real IPC/NDPS/IT-Act sections our crime priors already cite, the real NCRB crime-head
taxonomy, the real police rank ladder. It is derived, not invented — the same seed CSVs
that drive the crime distribution drive these tables, so a crime typed "Narcotics" always
resolves to the NDPS act and the Narcotic Offences head, and never to a dangling id.

The ER models each of these as its own table with an INT key; that is what we emit.
"""
from __future__ import annotations

from typing import NamedTuple

from ..districts import all_districts
from ..priors import crime_types

KARNATAKA_STATE_ID = 29                       # the real census/vehicle code for Karnataka
NATIONALITY_INDIA = 1

# ER lookups with no master table in the diagram — the columns are described as "lookup
# value" ints, so the mapping lives here and nowhere else.
GENDER = {"M": 1, "F": 2, "T": 3}
CASE_CATEGORY = {"FIR": 1, "UDR": 3, "PAR": 4, "Zero FIR": 8}   # the ER's own leading digit
ARREST_TYPE = {"Arrest": 1, "Surrender": 2}

# NCRB major heads. CaseMaster.CrimeMajorHeadID points here.
CRIME_HEADS: dict[int, str] = {
    1: "Crimes Against Body",
    2: "Crimes Against Property",
    3: "Economic Offences",
    4: "Cyber Crimes",
    5: "Crimes Against Women",
    6: "Narcotic Offences",
    7: "Crimes Against Public Tranquility",
}

# crime_type (from the seeded priors) -> (major head, act code)
_CRIME_MAP: dict[str, tuple[int, str]] = {
    "Theft": (2, "IPC"),
    "Hurt": (1, "IPC"),
    "House Burglary": (2, "IPC"),
    "Cheating": (3, "IPC"),
    "Criminal Breach of Trust": (3, "IPC"),
    "Assault on Woman": (5, "IPC"),
    "Criminal Intimidation": (1, "IPC"),
    "Motor Vehicle Theft": (2, "IPC"),
    "Robbery": (2, "IPC"),
    "Riot": (7, "IPC"),
    "Cyber Crime": (4, "IT"),
    "Rash Driving": (1, "IPC"),
    "Extortion": (2, "IPC"),
    "Kidnapping": (1, "IPC"),
    "Attempt to Murder": (1, "IPC"),
    "Murder": (1, "IPC"),
    "Rape": (5, "IPC"),
    "Dowry Death": (5, "IPC"),
    "Dacoity": (2, "IPC"),
    "Narcotics": (6, "NDPS"),
}

# The ER's GravityOffence. Heinous is a real KSP classification, not a coin flip: it is
# the offences that carry >=7 years, which is what drives the DSP-and-above masking rule.
_HEINOUS = {"Murder", "Attempt to Murder", "Rape", "Dowry Death", "Dacoity", "Kidnapping",
            "Robbery", "Narcotics"}
GRAVITY = {"Heinous": 1, "Non-Heinous": 2}

CASE_STATUSES = ["Under Investigation", "Chargesheeted", "Convicted", "Acquitted", "Closed"]

# Rank hierarchy: lower number = higher authority, exactly as the ER specifies.
RANKS = [(1, "IGP", 1), (2, "SP", 2), (3, "DSP", 3), (4, "Police Inspector", 4),
         (5, "Sub Inspector", 5), (6, "Head Constable", 6), (7, "Constable", 7)]
# Designation is the *job*, which is what our RBAC roles actually are.
DESIGNATIONS = [(1, "IG", 1), (2, "SP", 2), (3, "DSP", 3), (4, "SHO", 4),
                (5, "Investigating Officer", 5), (6, "SCRB Analyst", 6)]
# packages/policy speaks these six role names. The ER speaks DesignationID. One mapping,
# here, so policy never has to know about the ER and the ER never has to know about policy.
DESIGNATION_TO_ROLE = {1: "IG", 2: "SP", 3: "DSP", 4: "SHO", 5: "IO", 6: "SCRB_Analyst"}
ROLE_TO_DESIGNATION = {v: k for k, v in DESIGNATION_TO_ROLE.items()}

UNIT_TYPES = [(1, "Police Station", "City", 3), (2, "Circle Office", "District", 2),
              (3, "District HQ", "District", 2), (4, "State HQ", "State", 1)]

OCCUPATIONS = ["Agriculture", "Daily Wage Labour", "Government Employee", "Private Employee",
               "Business", "Student", "Homemaker", "Driver", "Unemployed", "Retired"]
# Present because the ER declares them. Never read by any model — see packages/policy.
RELIGIONS = ["Hindu", "Muslim", "Christian", "Jain", "Sikh", "Buddhist", "Other"]
CASTES = ["General", "OBC", "SC", "ST", "Not Recorded"]

BLOOD_GROUPS = 8


class ActSection(NamedTuple):
    act_code: str
    section_code: str
    description: str


_ACTS = {
    "IPC": "Indian Penal Code, 1860",
    "NDPS": "Narcotic Drugs and Psychotropic Substances Act, 1985",
    "IT": "Information Technology Act, 2000",
}
_ACT_SHORT = {"IPC": "IPC", "NDPS": "NDPS Act", "IT": "IT Act"}

_SECTION_DESC = {
    "302": "Punishment for murder", "307": "Attempt to murder",
    "304A": "Causing death by negligence", "304B": "Dowry death",
    "323": "Voluntarily causing hurt", "324": "Hurt by dangerous weapon",
    "326": "Grievous hurt by dangerous weapon", "337": "Causing hurt by act endangering life",
    "354": "Assault on woman with intent to outrage modesty", "354A": "Sexual harassment",
    "363": "Kidnapping", "365": "Kidnapping with intent to confine",
    "376": "Punishment for rape", "379": "Punishment for theft",
    "380": "Theft in dwelling house", "384": "Punishment for extortion",
    "385": "Putting person in fear of injury to commit extortion",
    "392": "Punishment for robbery", "394": "Voluntarily causing hurt in committing robbery",
    "395": "Punishment for dacoity", "397": "Robbery or dacoity with attempt to cause death",
    "406": "Criminal breach of trust", "409": "Criminal breach of trust by public servant",
    "420": "Cheating and dishonestly inducing delivery of property",
    "454": "Lurking house-trespass to commit offence", "457": "House-trespass by night",
    "498A": "Cruelty by husband or relative", "504": "Intentional insult to provoke breach of peace",
    "506": "Criminal intimidation", "279": "Rash driving on a public way",
    "143": "Punishment for unlawful assembly", "147": "Punishment for rioting",
    "148": "Rioting armed with a deadly weapon",
    "20": "Punishment for contravention in relation to cannabis",
    "21": "Punishment for contravention in relation to manufactured drugs",
    "22": "Punishment for contravention in relation to psychotropic substances",
    "66": "Computer related offences", "66C": "Identity theft",
    "66D": "Cheating by personation by using computer resource",
}


def crime_type_names() -> list[str]:
    """The 20 canonical crime-type labels a query can name — used to recognise which
    one (if any) a free-text question is asking about, e.g. for CRIME_SEARCH counting."""
    return list(_CRIME_MAP)


def crime_head_id(crime_type: str) -> int:
    return _CRIME_MAP[crime_type][0]


def act_for(crime_type: str) -> str:
    return _CRIME_MAP[crime_type][1]


def gravity_id(crime_type: str) -> int:
    return GRAVITY["Heinous"] if crime_type in _HEINOUS else GRAVITY["Non-Heinous"]


def sub_head_id(crime_type: str) -> int:
    """CrimeSubHeadID, stable across runs: the crime type's index in the priors CSV."""
    return _SUB_HEADS[crime_type]


_SUB_HEADS: dict[str, int] = {p.crime_type: i for i, p in enumerate(crime_types(), start=1)}


def district_id(code: str) -> int:
    """KA07 -> 7. The ER wants an INT DistrictID; our canonical codes are KAnn."""
    return int(code[2:])


def build() -> dict[str, list[dict]]:
    """Every ER master table, as rows ready for data.ds.insert()."""
    out: dict[str, list[dict]] = {}

    out["State"] = [{"StateID": KARNATAKA_STATE_ID, "StateName": "Karnataka",
                     "NationalityID": NATIONALITY_INDIA, "Active": True}]

    out["District"] = [{"DistrictID": district_id(d.code), "DistrictName": d.name,
                        "StateID": KARNATAKA_STATE_ID, "Active": True}
                       for d in all_districts()]

    out["UnitType"] = [{"UnitTypeID": i, "UnitTypeName": n, "CityDistState": lvl,
                        "Hierarchy": h, "Active": True} for i, n, lvl, h in UNIT_TYPES]

    out["Rank"] = [{"RankID": i, "RankName": n, "Hierarchy": h, "Active": True}
                   for i, n, h in RANKS]

    out["Designation"] = [{"DesignationID": i, "DesignationName": n, "Active": True,
                           "SortOrder": s} for i, n, s in DESIGNATIONS]

    out["Court"] = [{"CourtID": district_id(d.code), "CourtName": f"District & Sessions Court, {d.name}",
                     "DistrictID": district_id(d.code), "StateID": KARNATAKA_STATE_ID,
                     "Active": True} for d in all_districts()]

    out["CaseCategory"] = [{"CaseCategoryID": v, "LookupValue": k}
                           for k, v in CASE_CATEGORY.items()]
    out["GravityOffence"] = [{"GravityOffenceID": v, "LookupValue": k}
                             for k, v in GRAVITY.items()]
    out["CaseStatusMaster"] = [{"CaseStatusID": i, "CaseStatusName": n}
                               for i, n in enumerate(CASE_STATUSES, start=1)]
    out["OccupationMaster"] = [{"OccupationID": i, "OccupationName": n}
                               for i, n in enumerate(OCCUPATIONS, start=1)]
    out["ReligionMaster"] = [{"ReligionID": i, "ReligionName": n}
                             for i, n in enumerate(RELIGIONS, start=1)]
    out["CasteMaster"] = [{"caste_master_id": i, "caste_master_name": n}
                          for i, n in enumerate(CASTES, start=1)]

    out["CrimeHead"] = [{"CrimeHeadID": i, "CrimeGroupName": n, "Active": True}
                        for i, n in CRIME_HEADS.items()]
    out["CrimeSubHead"] = [{"CrimeSubHeadID": sub_head_id(p.crime_type),
                            "CrimeHeadID": crime_head_id(p.crime_type),
                            "CrimeHeadName": p.crime_type,
                            "SeqID": sub_head_id(p.crime_type)}
                           for p in crime_types()]

    out["Act"] = [{"ActCode": code, "ActDescription": desc, "ShortName": _ACT_SHORT[code],
                   "Active": True} for code, desc in _ACTS.items()]

    sections, seen = [], set()
    head_act_sections = []
    for p in crime_types():
        act = act_for(p.crime_type)
        for sec in p.ipc_sections:
            if (act, sec) not in seen:
                seen.add((act, sec))
                sections.append({"ActCode": act, "SectionCode": sec,
                                 "SectionDescription": _SECTION_DESC.get(sec, f"Section {sec}"),
                                 "Active": True})
            head_act_sections.append({"CrimeHeadID": crime_head_id(p.crime_type),
                                      "ActCode": act, "SectionCode": sec})
    out["Section"] = sections
    out["CrimeHeadActSection"] = head_act_sections
    return out


if __name__ == "__main__":
    tables = build()
    # Every FK a CaseMaster row will emit must resolve, or the whole dataset is dangling.
    heads = {r["CrimeHeadID"] for r in tables["CrimeHead"]}
    subs = {r["CrimeSubHeadID"] for r in tables["CrimeSubHead"]}
    acts = {r["ActCode"] for r in tables["Act"]}
    for p in crime_types():
        assert crime_head_id(p.crime_type) in heads, p.crime_type
        assert sub_head_id(p.crime_type) in subs, p.crime_type
        assert act_for(p.crime_type) in acts, p.crime_type
    assert {r["ActCode"] for r in tables["Section"]} <= acts
    assert len(tables["District"]) == 31, len(tables["District"])
    assert len({r["CrimeSubHeadID"] for r in tables["CrimeSubHead"]}) == len(tables["CrimeSubHead"])
    print("refdata OK: " + ", ".join(f"{k}={len(v)}" for k, v in tables.items()))
