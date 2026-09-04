"""The ER's master/lookup tables, built deterministically.

Everything here is reference data, not synthetic crime: the 31 real Karnataka districts,
the real IPC/NDPS/IT-Act sections our crime priors already cite, the real NCRB crime-head
taxonomy, the real police rank ladder. It is derived, not invented — the same seed CSVs
that drive the crime distribution drive these tables, so a crime typed "Narcotics" always
resolves to the NDPS act and the Narcotic Offences head, and never to a dangling id.

The ER models each of these as its own table with an INT key; that is what we emit.
"""
from __future__ import annotations

from datetime import date
from typing import NamedTuple

from ..districts import all_districts
from ..priors import crime_types

# The Bharatiya Nyaya Sanhita, 2023 replaced the IPC for every offence committed on or
# after this date (BNS s.1, commencement notification). NDPS and the IT Act were not
# touched by this transition and keep citing their own Act throughout. A dataset dated
# into 2025-2026 that cites only the IPC is citing a code no FIR filed after this date
# may lawfully use — this is what BNS_CUTOVER exists to fix.
BNS_CUTOVER = date(2024, 7, 1)

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
    "BNS": "Bharatiya Nyaya Sanhita, 2023",
    "NDPS": "Narcotic Drugs and Psychotropic Substances Act, 1985",
    "IT": "Information Technology Act, 2000",
}
_ACT_SHORT = {"IPC": "IPC", "BNS": "BNS", "NDPS": "NDPS Act", "IT": "IT Act"}

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
    # BNS equivalents of every IPC section above (NDPS and the IT Act were not touched
    # by the transition, so those two acts have no entry here — see act_and_sections_for).
    # Sourced from the Bureau of Police Research & Development's official "Correspondence
    # Table and Comparison Summary of the BNS, 2023 to the IPC, 1860"
    # (bprd.nic.in/uploads/pdf/COMPARISON%20SUMMARY%20BNS%20to%20IPC%20.pdf), cross-checked
    # against a second published IPC->BNS conversion table. Subsections marked "approx." in
    # a comment below were inferred from the surrounding subsection sequence in that table,
    # not read off it directly — the section family is sourced either way, the exact
    # sub-clause letter is the only place this is an inference rather than a lookup.
    "101(1)": "Punishment for murder (BNS)", "109(1)": "Attempt to murder (BNS)",
    "106(1)": "Causing death by negligence (BNS)", "80(1)": "Dowry death (BNS)",
    "115(2)": "Voluntarily causing hurt (BNS)", "118(1)": "Hurt by dangerous weapon (BNS)",
    "118(2)": "Grievous hurt by dangerous weapon (BNS)",
    "125(A)": "Act endangering life or personal safety of others (BNS)",
    "74": "Assault on woman with intent to outrage modesty (BNS)",
    "75": "Sexual harassment (BNS)",
    "137(2)": "Punishment for kidnapping (BNS)",
    "140(3)": "Kidnapping/abducting to secretly and wrongfully confine (BNS)",
    "64(1)": "Punishment for rape (BNS)", "303(2)": "Punishment for theft (BNS)",
    "305": "Theft in a dwelling house (BNS)", "308(2)": "Punishment for extortion (BNS)",
    "308(3)": "Extortion by putting a person in fear of injury (BNS, approx.)",
    "309(4)": "Punishment for robbery (BNS, approx.)",
    "309(3)": "Voluntarily causing hurt in committing robbery (BNS, approx.)",
    "310(2)": "Punishment for dacoity (BNS)",
    "310(4)": "Dacoity with attempt to cause death (BNS, approx.)",
    "316(2)": "Criminal breach of trust (BNS, approx.)",
    "316(5)": "Criminal breach of trust by public servant (BNS)",
    "318(4)": "Cheating and dishonestly inducing delivery of property (BNS)",
    "331(3)": "Lurking house-trespass to commit offence (BNS)",
    "331(4)": "House-trespass by night (BNS)",
    "85": "Cruelty by husband or relative (BNS)",
    "352": "Intentional insult to provoke breach of peace (BNS)",
    "351(2)": "Criminal intimidation (BNS, approx.)", "281": "Rash driving on a public way (BNS)",
    "189(1)": "Punishment for unlawful assembly (BNS, approx.)",
    "191(2)": "Punishment for rioting (BNS)", "191(3)": "Rioting armed with a deadly weapon (BNS)",
}

# IPC section -> its BNS equivalent, for every section actually cited by the crime
# priors (data/data/seed/derived/crime_types.csv). NDPS (Narcotics) and the IT Act
# (Cyber Crime) are untouched by BNS and are deliberately absent — they cite the same
# section under either code, at any date.
_IPC_TO_BNS: dict[str, str] = {
    "302": "101(1)", "307": "109(1)", "304A": "106(1)", "304B": "80(1)",
    "323": "115(2)", "324": "118(1)", "326": "118(2)", "337": "125(A)",
    "354": "74", "354A": "75", "363": "137(2)", "365": "140(3)",
    "376": "64(1)", "379": "303(2)", "380": "305", "384": "308(2)", "385": "308(3)",
    "392": "309(4)", "394": "309(3)", "395": "310(2)", "397": "310(4)",
    "406": "316(2)", "409": "316(5)", "420": "318(4)",
    "454": "331(3)", "457": "331(4)", "498A": "85", "504": "352", "506": "351(2)",
    "279": "281", "143": "189(1)", "147": "191(2)", "148": "191(3)",
}


def crime_type_names() -> list[str]:
    """The 20 canonical crime-type labels a query can name — used to recognise which
    one (if any) a free-text question is asking about, e.g. for CRIME_SEARCH counting."""
    return list(_CRIME_MAP)


def crime_head_id(crime_type: str) -> int:
    return _CRIME_MAP[crime_type][0]


def act_for(crime_type: str) -> str:
    return _CRIME_MAP[crime_type][1]


def act_and_sections_for(crime_type: str, offence_date: date,
                         ipc_sections: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    """The act and sections a case actually cites, given WHEN the offence happened.

    An FIR cites the law in force on the date of the offence, not the date it is typed
    up (BNS s.1(2); "if the offence was committed before 1 July 2024, the IPC applies").
    NDPS and IT Act crime types are untouched by the transition and always resolve to
    their own act. Every IPC-mapped crime type resolves to BNS for anything on or after
    BNS_CUTOVER — which is most of this dataset's date range, so leaving this at plain
    IPC would mean the majority of generated FIRs cite a code that was retired for new
    offences two years before this dataset's own "now".
    """
    act = act_for(crime_type)
    if act != "IPC" or offence_date < BNS_CUTOVER:
        return act, ipc_sections
    return "BNS", tuple(_IPC_TO_BNS[s] for s in ipc_sections)


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
        # A case is generated for one or the other act depending on its own offence
        # date (act_and_sections_for), so both variants' Section/CrimeHeadActSection
        # rows must exist as FK targets — NDPS/IT crime types have only one variant.
        variants = [(act, p.ipc_sections)]
        if act == "IPC":
            variants.append(("BNS", tuple(_IPC_TO_BNS[s] for s in p.ipc_sections)))
        for act_code, secs in variants:
            for sec in secs:
                if (act_code, sec) not in seen:
                    seen.add((act_code, sec))
                    sections.append({"ActCode": act_code, "SectionCode": sec,
                                     "SectionDescription": _SECTION_DESC.get(sec, f"Section {sec}"),
                                     "Active": True})
                head_act_sections.append({"CrimeHeadID": crime_head_id(p.crime_type),
                                          "ActCode": act_code, "SectionCode": sec})
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
    # Every IPC-mapped crime type's BNS variant must also resolve — a case dated on or
    # after BNS_CUTOVER will look up exactly these (ActCode, SectionCode) pairs.
    have_sections = {(r["ActCode"], r["SectionCode"]) for r in tables["Section"]}
    for p in crime_types():
        if act_for(p.crime_type) != "IPC":
            continue
        assert all(("IPC", s) in have_sections for s in p.ipc_sections), p.crime_type
        _, bns_secs = act_and_sections_for(p.crime_type, date(2025, 1, 1), p.ipc_sections)
        assert all(("BNS", s) in have_sections for s in bns_secs), p.crime_type
    print("refdata OK: " + ", ".join(f"{k}={len(v)}" for k, v in tables.items()))
