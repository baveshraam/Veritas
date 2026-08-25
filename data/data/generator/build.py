"""Build an internally consistent synthetic dataset **in the organizers' ER shape**.

Pure functions: given a seeded Random and a case count, return rows that already satisfy
every foreign key in Police_FIR_ER_Diagram.pdf. No DB, no I/O — generator/load.py persists
them to the Catalyst Data Store.

The one thing to understand about this file: **their ER has no person.** An `Accused` row
belongs to exactly one case and carries a name string; `Accused.PersonID` is a sort label
("A1", "A2"), not an identity. So a habitual offender appearing in six FIRs is six
unrelated rows, and half of them may be spelled differently — "Ramesh Gowda" in one
station, "Ramesha Gouda" in the next. That is not a defect we inject for show; it is what
the schema structurally *is*, and it is what real police records look like.

So the generator keeps a private cast of `TruePerson`s that it never writes to the record
layer, and emits `Accused` rows *from* them, sometimes under a romanisation variant. The
ground-truth mapping is returned for scoring only. Recovering it — Accused rows -> people —
is the entity-resolution pass's job, and it is the only reason a question like "does he
have priors?" can be answered against this schema at all.

Two properties are load-bearing and easy to destroy; both are preserved from the previous
generator, where each was a real bug found by a model that correctly learned there was no
signal to find:
  * incidents cluster around activity centres, not uniformly in a district (or KDE/DBSCAN
    find no hotspot to find);
  * accused are drawn by preferential attachment on prior offences, in chronological
    order (or a prior record predicts nothing and recidivism is unlearnable).
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..districts import all_districts
from ..priors import CrimeTypePrior, district_weights, sample_crime_type, sample_district
from . import refdata as rd
from .geo import sample_point
from .names import full_record_name, sample_name, sample_patronym

NOW = date(2026, 7, 1)

# Modus-operandi text, per crime type. Several variants each — not decoration: a fixed
# single sentence per type meant every case of that type in that district collapsed to
# one narrative shape once date was normalised out (BUG-023, measured live: 60/60
# sampled cases per crime type reduced to a single template). All 20 canonical crime
# types are covered now, not the previous 8 — the other 12 fell back to a bare
# "<crime type> — routine method", which carried zero descriptive content at all.
_MO_VARIANTS: dict[str, list[str]] = {
    "Theft": [
        "Pickpocketing in a crowded market",
        "Handbag snatched from a parked two-wheeler",
        "Cash box lifted from an unattended shop counter",
    ],
    "Hurt": [
        "Altercation over a parking dispute escalating to blows",
        "Physical assault following a heated verbal argument",
        "Scuffle between neighbours over a boundary dispute",
    ],
    "House Burglary": [
        "Entry via rear window after dark while occupants away",
        "Lock broken on the main door during a daytime absence",
        "Compound wall scaled to reach an unlocked rear entrance",
    ],
    "Cheating": [
        "Fake investment scheme collecting advance deposits",
        "Impersonation of a government official to collect fees",
        "Forged documents used to secure a fraudulent loan",
    ],
    "Criminal Breach of Trust": [
        "Funds entrusted for a specific purpose diverted by the accused",
        "Society office-bearer misappropriating collected subscriptions",
        "Business partner withholding jointly-held proceeds",
    ],
    "Assault on Woman": [
        "Outraging modesty during an unwanted physical advance",
        "Verbal harassment escalating to unwanted physical contact",
        "Molestation reported by the complainant at a public place",
    ],
    "Criminal Intimidation": [
        "Threats issued over an unpaid debt",
        "Threat of harm made during a property dispute",
        "Intimidation delivered by phone following a business disagreement",
    ],
    "Motor Vehicle Theft": [
        "Two-wheeler lifted from an unguarded parking lot",
        "Car taken from outside the owner's residence overnight",
        "Vehicle key duplicated and used to remove it from a public lot",
    ],
    "Robbery": [
        "Chain-snatching from a two-wheeler pillion rider",
        "Bag robbed at knife-point on a secluded stretch of road",
        "Mobile phone snatched from a pedestrian at a bus stop",
    ],
    "Riot": [
        "Unlawful assembly turning violent during a public gathering",
        "Group clash breaking out during a local procession",
        "Stone-pelting between two groups after a festival dispute",
    ],
    "Cyber Crime": [
        "OTP-phishing call impersonating a bank official",
        "Fraudulent online marketplace listing collecting advance payment",
        "Unauthorised access to a social media account for extortion",
    ],
    "Rash Driving": [
        "Overspeeding vehicle losing control on a residential road",
        "Vehicle driven against oncoming traffic at a junction",
        "Signal jumped at high speed causing a collision",
    ],
    "Extortion": [
        "Demand for money under threat of harm to business premises",
        "Payment demanded to prevent publication of private material",
        "Protection money demanded from a roadside vendor",
    ],
    "Kidnapping": [
        "Minor lured away from a public place on a false pretext",
        "Person taken away by force during a personal dispute",
        "Abduction reported following a failed ransom demand",
    ],
    "Attempt to Murder": [
        "Assault with a sharp weapon following a prior dispute, victim survived",
        "Attack with a blunt weapon during a property dispute, victim survived",
        "Poisoning attempt reported by a family member, victim survived",
    ],
    "Murder": [
        "Assault with a blunt weapon following a prior dispute",
        "Fatal stabbing during a dispute between acquaintances",
        "Death following an assault at the victim's residence",
    ],
    "Rape": [
        "Sexual assault reported by the complainant against a known person",
        "Assault reported following a promise of marriage later broken",
        "Sexual assault reported at the accused's residence",
    ],
    "Dowry Death": [
        "Unnatural death of a married woman within the statutory period, dowry harassment alleged",
        "Death by burns reported at the matrimonial home, dowry demand alleged",
        "Death reported following sustained harassment for dowry",
    ],
    "Dacoity": [
        "Armed group robbing a residence at night",
        "Group robbery of a commercial establishment after business hours",
        "Armed gang intercepting a vehicle on a highway stretch",
    ],
    "Narcotics": [
        "Ganja transported concealed in a goods vehicle",
        "Contraband recovered during a routine vehicle check",
        "Narcotic substance seized from a residential premises",
    ],
}

_TIME_OF_DAY = [
    (5, "in the early morning hours"),
    (12, "during the morning"),
    (17, "in the afternoon"),
    (21, "in the evening"),
    (24, "late at night"),
]


def _time_of_day(hour: int) -> str:
    for ceiling, label in _TIME_OF_DAY:
        if hour < ceiling:
            return label
    return _TIME_OF_DAY[-1][1]


def _offender_count_phrase(n_accused: int) -> str:
    if n_accused <= 1:
        return "by a lone individual"
    if n_accused == 2:
        return "by two persons acting together"
    return f"by a group of {n_accused} persons"

RECIDIVISM_ALPHA = 4.0      # strength of preferential attachment to prior offenders
LOCAL_WEIGHT = 15.0         # how much more likely an accused is to live in the case district
CREW_WEIGHT = 40.0          # pull towards people the lead offender has already worked with
VARIANT_RATE = 0.35         # chance an accused is recorded under a spelling variant


@dataclass
class TruePerson:
    """A human. Deliberately NOT an ER table — the ER has no such concept.

    This is the generator's private ground truth. It is written to the record layer only
    indirectly, as name strings on Accused/Victim/Complainant rows.
    """
    uid: int
    name_en: str
    patronym: str                     # father's given name — stable across every case
    dob: date
    gender: str                       # M/F/T
    home_district: str                # KAnn
    lat: float
    lng: float
    offences: int = 0


@dataclass
class Dataset:
    """Rows keyed by ER table name, ready for data.ds.insert()."""
    tables: dict[str, list[dict]] = field(default_factory=dict)
    people: list[TruePerson] = field(default_factory=list)
    # AccusedMasterID -> TruePerson.uid. The answer key for entity resolution. Never loaded.
    accused_truth: dict[int, int] = field(default_factory=dict)

    def rows(self, table: str) -> list[dict]:
        return self.tables.setdefault(table, [])


# ------------------------------------------------------------------- police force / units
def make_units_and_employees(rng: random.Random) -> tuple[list[dict], list[dict]]:
    """Stations scale with each district's real crime weight.

    Bengaluru Urban carries ~28% of Karnataka's recorded crime and Kodagu well under 1%.
    Giving every district the same number of stations would misstate both the force
    distribution and the per-station caseload an IO sees under RBAC.
    """
    units: list[dict] = []
    employees: list[dict] = []
    weights = district_weights()
    emp_id = 1

    for d in all_districts():
        did = rd.district_id(d.code)
        hq_id = did * 100                       # district HQ
        units.append({"UnitID": hq_id, "UnitName": f"{d.name} District HQ", "TypeID": 3,
                      "ParentUnit": None, "NationalityID": rd.NATIONALITY_INDIA,
                      "StateID": rd.KARNATAKA_STATE_ID, "DistrictID": did, "Active": True})

        n_ps = max(2, round(weights[d.code] / 2))
        for i in range(1, n_ps + 1):
            uid = did * 100 + i
            units.append({"UnitID": uid, "UnitName": f"{d.name} PS-{i:02d}", "TypeID": 1,
                          "ParentUnit": hq_id, "NationalityID": rd.NATIONALITY_INDIA,
                          "StateID": rd.KARNATAKA_STATE_ID, "DistrictID": did, "Active": True})
            # A station is an SHO, three IOs and a DSP. The DSP is what makes the
            # "victim identity masked below DSP" policy rule exercisable at every station.
            for role, rank in (("SHO", 4), ("IO", 5), ("IO", 5), ("IO", 5), ("DSP", 3)):
                employees.append(_employee(rng, emp_id, did, uid, rank,
                                           rd.ROLE_TO_DESIGNATION[role]))
                emp_id += 1

    # A thin state-level layer: SP, IG, SCRB analyst, posted at the first district's HQ.
    for role, rank in (("SP", 2), ("IG", 1), ("SCRB_Analyst", 4)):
        d0 = all_districts()[0]
        employees.append(_employee(rng, emp_id, rd.district_id(d0.code), rd.district_id(d0.code) * 100,
                                   rank, rd.ROLE_TO_DESIGNATION[role]))
        emp_id += 1
    return units, employees


def _employee(rng: random.Random, eid: int, did: int, uid: int, rank: int,
              designation: int) -> dict:
    gender = "F" if rng.random() < 0.18 else "M"
    age = rng.randint(26, 58)
    return {
        "EmployeeID": eid, "DistrictID": did, "UnitID": uid, "RankID": rank,
        "DesignationID": designation, "KGID": f"KGID{eid:06d}",
        "FirstName": sample_name(rng, gender),
        "EmployeeDOB": date(NOW.year - age, rng.randint(1, 12), rng.randint(1, 28)),
        "GenderID": rd.GENDER[gender], "BloodGroupID": rng.randint(1, rd.BLOOD_GROUPS),
        "PhysicallyChallenged": rng.random() < 0.02,
        "AppointmentDate": date(NOW.year - rng.randint(1, age - 22), rng.randint(1, 12),
                                rng.randint(1, 28)),
    }


# ------------------------------------------------------------------------------- the cast
def make_people(rng: random.Random, n: int) -> list[TruePerson]:
    people = []
    for uid in range(1, n + 1):
        gender = "F" if rng.random() < 0.30 else "M"
        dc = sample_district(rng)
        age = rng.randint(18, 70)
        lat, lng = sample_point(rng, dc)
        people.append(TruePerson(
            uid=uid, name_en=sample_name(rng, gender), patronym=sample_patronym(rng),
            dob=date(NOW.year - age, rng.randint(1, 12), rng.randint(1, 28)),
            gender=gender, home_district=dc, lat=lat, lng=lng))
    return people


def _recorded_name(rng: random.Random, p: TruePerson) -> str:
    """How this person's name got typed into *this* FIR.

    The S/o / D/o form every Indian FIR uses. A third of the time the given name is a
    romanisation variant — which is precisely why the same human is unrecognisable across
    stations, and why entity resolution is not optional. The patronymic drifts too, but
    less often: it is copied from a document more often than heard aloud.
    """
    from ..nlp import transliterate

    name = p.name_en
    if rng.random() < VARIANT_RATE:
        variants = [v for v in transliterate(name) if v != name]
        name = rng.choice(variants) if variants else name
    patronym = p.patronym
    if rng.random() < VARIANT_RATE / 3:
        variants = [v for v in transliterate(patronym) if v != patronym]
        patronym = rng.choice(variants) if variants else patronym
    return full_record_name(name, patronym, p.gender)


def _recorded_age(rng: random.Random, p: TruePerson, on: date) -> int:
    """Age as written down: usually right, sometimes off by a year or two.

    Real FIRs record a stated age, not a verified DOB. The noise is what forces
    Fellegi-Sunter to weigh partial agreement instead of demanding an exact match.
    """
    true_age = on.year - p.dob.year
    return max(18, true_age + rng.choice([0, 0, 0, 0, 1, -1, 2, -2]))


# ---------------------------------------------------------------------------------- cases
def _case_status(rng: random.Random, prior: CrimeTypePrior) -> int:
    if rng.random() > prior.chargesheet_rate:
        return 1                                                # Under Investigation
    r = rng.random()
    if r < prior.conviction_rate:
        return 3                                                # Convicted
    if r < prior.conviction_rate + 0.25:
        return 4                                                # Acquitted
    return 2                                                    # Chargesheeted


def _crime_no(category: int, district: int, unit: int, year: int, serial: int) -> str:
    """The ER's format: 1 category + 4 district + 4 unit + 4 year + 5 serial = 18 digits.

    e.g. FIR 1 0443 0006 2026 00001 -> "104430006202600001". A separate serial runs per
    (station, category, year), exactly as the diagram specifies.
    """
    return f"{category:1d}{district:04d}{unit:04d}{year:04d}{serial:05d}"


def _pick_accused(rng: random.Random, pool: list[TruePerson], complainant: TruePerson,
                  district: str, crews: dict[int, Counter]) -> list[TruePerson]:
    """Three forces decide who did it: prior offending, proximity, and who they run with.

    Preferential attachment on priors. Uniform sampling means a prior record predicts
    nothing about future offending, so there is no habitual cohort and a recidivism model
    correctly learns there is no signal. Real offending is heavily skewed. Weighting by
    1 + ALPHA * priors reproduces that skew — and it only works because cases are generated
    oldest-first, so a "prior" genuinely precedes the offence it predicts.

    Locality. Offenders overwhelmingly offend near where they live; they do not commute
    across Karnataka at random. Drawing them state-wide (which is what this did first)
    scatters one man's cases across 31 districts, and then *where a crime happened carries
    no information about who did it* — which destroys entity resolution's second-strongest
    signal (measured: m[location] came out identical to u[location], i.e. exactly zero
    evidence). LOCAL_WEIGHT restores it. The residual cross-district draw is real too: it
    is what organised crime looks like.

    Triadic closure — the crew. Drawing every co-accused independently from the pool was
    the remaining defect, and it was a bad one: it makes co-offending a *random* graph over
    the active offenders, and a random graph has no community structure. Louvain duly found
    one giant community containing 254 of 255 people, which is a true statement about the
    data and a useless one about crime. Real offenders reoffend with the people they already
    offended with. Weighting each additional accused by how often they have worked with this
    case's lead (CREW_WEIGHT) is what makes a crew a crew — and it is the thing Louvain is
    there to recover. The gang label is a *consequence* of this structure, not an input to
    it: nothing downstream reads TruePerson.gang, and the ER records no gang at all.
    """
    k = rng.choices([1, 2, 3, 4], weights=[55, 25, 12, 8], k=1)[0]
    base = [(1.0 + RECIDIVISM_ALPHA * p.offences)
            * (LOCAL_WEIGHT if p.home_district == district else 1.0)
            for p in pool]

    chosen: list[TruePerson] = []
    for _ in range(60):
        if len(chosen) == k:
            break
        if not chosen:
            weights = base
        else:
            # Everyone after the lead is drawn towards the lead's known associates.
            crew = crews[chosen[0].uid]
            weights = [b * (1.0 + CREW_WEIGHT * crew[p.uid]) for b, p in zip(base, pool)]
        p = rng.choices(pool, weights=weights, k=1)[0]
        if p.uid == complainant.uid or p in chosen:
            continue
        chosen.append(p)

    for a in chosen:                      # record the crew ties this case just created
        for b in chosen:
            if a.uid != b.uid:
                crews[a.uid][b.uid] += 1
    return chosen


def _narrative(rng: random.Random, crime_type: str, district: str, filed: datetime,
               occ_from: datetime, n_accused: int) -> str:
    """Case-specific narrative text, built entirely from facts this case already has:
    the crime type, the district, when it was filed, when it actually occurred (for the
    time-of-day phrase), and how many people were accused (for the offender-count
    phrase) — no field here is invented; every one is a real, already-generated
    attribute of this case. The MO clause is a per-case draw from a pool of variants
    for this crime type (all 20 types now covered, not 8), so two cases of the same
    type in the same district no longer collapse to one template once date is
    normalised out (BUG-023).
    """
    variants = _MO_VARIANTS.get(crime_type)
    mo = rng.choice(variants) if variants else f"{crime_type} — routine method"
    when = _time_of_day(occ_from.hour)
    who = _offender_count_phrase(n_accused)
    return (f"On {filed:%d %b %Y}, a case of {crime_type.lower()} was registered in "
            f"{district} district. {mo}, {when}, {who}. "
            f"Investigation is being carried out as per procedure.")


def generate(rng: random.Random, n_cases: int) -> Dataset:
    ds = Dataset()
    ds.tables.update(rd.build())                     # masters first: every FK below resolves

    units, employees = make_units_and_employees(rng)
    ds.tables["Unit"] = units
    ds.tables["Employee"] = employees

    people = make_people(rng, max(20, int(n_cases * 0.7)))
    ds.people = people

    # Stations and their staff, indexed for lookup during case generation.
    stations = [u for u in units if u["TypeID"] == 1]
    by_district: dict[int, list[dict]] = {}
    for u in stations:
        by_district.setdefault(u["DistrictID"], []).append(u)
    ios: dict[int, list[int]] = {}
    for e in employees:
        if e["DesignationID"] in (rd.ROLE_TO_DESIGNATION["IO"], rd.ROLE_TO_DESIGNATION["SHO"]):
            ios.setdefault(e["UnitID"], []).append(e["EmployeeID"])

    # Oldest-first. See _pick_accused.
    filed_dates = sorted(_rand_datetime(rng, rng.randint(1, 1095)) for _ in range(n_cases))

    serial: dict[tuple[int, int, int], int] = {}     # (unit, category, year) -> running no
    ids = dict(case=0, comp=0, vic=0, acc=0, arr=0, cs=0)
    # Who has offended with whom, so far. The crew structure Louvain is meant to recover.
    crews: dict[int, Counter] = defaultdict(Counter)

    for filed in filed_dates:
        prior = sample_crime_type(rng)
        dc = sample_district(rng)
        did = rd.district_id(dc)
        unit = rng.choice(by_district[did])
        uid = unit["UnitID"]
        io = rng.choice(ios[uid])
        year = filed.year
        category = rd.CASE_CATEGORY["FIR"]
        key = (uid, category, year)
        serial[key] = serial.get(key, 0) + 1

        ids["case"] += 1
        case_id = ids["case"]
        occ_from = filed - timedelta(hours=rng.randint(2, 240))     # crime precedes the report
        occ_to = min(occ_from + timedelta(hours=rng.randint(0, 12)), filed)
        lat, lng = sample_point(rng, dc)
        dname = _district_name(dc)
        status = _case_status(rng, prior)

        # Picked before CaseMaster so the narrative can honestly say how many people
        # were accused — a real fact about this case, not an invented one.
        complainant = rng.choice(people)
        accused_list = _pick_accused(rng, people, complainant, dc, crews)

        ds.rows("CaseMaster").append({
            "CaseMasterID": case_id,
            "CrimeNo": _crime_no(category, did, uid, year, serial[key]),
            "CaseNo": f"{year:04d}{serial[key]:05d}",
            "CrimeRegisteredDate": filed.date(),
            "PolicePersonID": io, "PoliceStationID": uid,
            "CaseCategoryID": category,
            "GravityOffenceID": rd.gravity_id(prior.crime_type),
            "CrimeMajorHeadID": rd.crime_head_id(prior.crime_type),
            "CrimeMinorHeadID": rd.sub_head_id(prior.crime_type),
            "CaseStatusID": status, "CourtID": did,
            "IncidentFromDate": occ_from, "IncidentToDate": occ_to,
            "InfoReceivedPSDate": filed,
            "latitude": lat, "longitude": lng,
            "BriefFacts": _narrative(rng, prior.crime_type, dname, filed, occ_from,
                                     len(accused_list)),
        })

        # ActSectionAssociation — the ER's replacement for a TEXT[] of IPC sections.
        act = rd.act_for(prior.crime_type)
        for order, sec in enumerate(prior.ipc_sections, start=1):
            ds.rows("ActSectionAssociation").append({
                "CaseMasterID": case_id, "ActID": act, "SectionID": sec,
                "ActOrderID": 1, "SectionOrderID": order})

        ids["comp"] += 1
        ds.rows("ComplainantDetails").append({
            "ComplainantID": ids["comp"], "CaseMasterID": case_id,
            "ComplainantName": _recorded_name(rng, complainant),
            "AgeYear": _recorded_age(rng, complainant, filed.date()),
            "OccupationID": rng.randint(1, len(rd.OCCUPATIONS)),
            "ReligionID": rng.randint(1, len(rd.RELIGIONS)),
            "CasteID": rng.randint(1, len(rd.CASTES)),
            "GenderID": rd.GENDER[complainant.gender]})

        # Victims: property crime often has the complainant as the sole victim; crimes
        # against the body always name one.
        for _ in range(rng.choices([1, 2], weights=[85, 15])[0]):
            v = complainant if rng.random() < 0.6 else rng.choice(people)
            ids["vic"] += 1
            ds.rows("Victim").append({
                "VictimMasterID": ids["vic"], "CaseMasterID": case_id,
                "VictimName": _recorded_name(rng, v),
                "AgeYear": _recorded_age(rng, v, filed.date()),
                "GenderID": rd.GENDER[v.gender],
                "VictimPolice": "1" if rng.random() < 0.01 else "0"})

        for n, person in enumerate(accused_list, start=1):
            person.offences += 1
            ids["acc"] += 1
            acc_id = ids["acc"]
            ds.accused_truth[acc_id] = person.uid          # the answer key. Never loaded.
            ds.rows("Accused").append({
                "AccusedMasterID": acc_id, "CaseMasterID": case_id,
                "AccusedName": _recorded_name(rng, person),
                "AgeYear": _recorded_age(rng, person, filed.date()),
                "GenderID": rd.GENDER[person.gender],
                "PersonID": f"A{n}"})                      # a sort label, per the ER

            if rng.random() < 0.7:                         # arrested
                ids["arr"] += 1
                arr_id = ids["arr"]
                ds.rows("ArrestSurrender").append({
                    "ArrestSurrenderID": arr_id, "CaseMasterID": case_id,
                    "ArrestSurrenderTypeID": rd.ARREST_TYPE[
                        "Surrender" if rng.random() < 0.12 else "Arrest"],
                    "ArrestSurrenderDate": filed.date() + timedelta(days=rng.randint(0, 30)),
                    "ArrestSurrenderStateId": rd.KARNATAKA_STATE_ID,
                    "ArrestSurrenderDistrictId": did, "PoliceStationID": uid,
                    "IOID": io, "CourtID": did, "AccusedMasterID": acc_id,
                    "IsAccused": True, "IsComplainantAccused": False})
                ds.rows("inv_arrestsurrenderaccused").append(
                    {"ArrestSurrenderID": arr_id, "AccusedMasterID": acc_id})

        if status in (2, 3, 4):                            # chargesheeted or beyond
            ids["cs"] += 1
            ds.rows("ChargesheetDetails").append({
                "CSID": ids["cs"], "CaseMasterID": case_id,
                "csdate": filed + timedelta(days=rng.randint(30, 180)),
                "cstype": "A", "PolicePersonID": io})
        elif rng.random() < 0.05:                          # closed as false / undetected
            ids["cs"] += 1
            ds.rows("ChargesheetDetails").append({
                "CSID": ids["cs"], "CaseMasterID": case_id,
                "csdate": filed + timedelta(days=rng.randint(60, 240)),
                "cstype": rng.choice(["B", "C"]), "PolicePersonID": io})

    return ds


def _rand_datetime(rng: random.Random, days_back: int) -> datetime:
    base = datetime(NOW.year, NOW.month, NOW.day) - timedelta(days=days_back)
    return base + timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0, 59))


def _district_name(code: str) -> str:
    from ..districts import canonical_name
    return canonical_name(code) or code


if __name__ == "__main__":
    ds = generate(random.Random(7), 500)

    cases = {r["CaseMasterID"] for r in ds.tables["CaseMaster"]}
    assert len(cases) == 500

    # Every CrimeNo is the ER's 18-digit format, and unique.
    nos = [r["CrimeNo"] for r in ds.tables["CaseMaster"]]
    assert all(len(n) == 18 and n.isdigit() for n in nos), "CrimeNo is not 18 digits"
    assert len(set(nos)) == len(nos), "CrimeNo collision"
    # CaseNo is the last 9 digits of CrimeNo, per the diagram's highlighted note.
    assert all(r["CaseNo"] == r["CrimeNo"][-9:] for r in ds.tables["CaseMaster"])

    # Referential integrity: no child row may point at a case that doesn't exist.
    for t in ("ComplainantDetails", "Victim", "Accused", "ArrestSurrender",
              "ActSectionAssociation", "ChargesheetDetails"):
        assert all(r["CaseMasterID"] in cases for r in ds.tables[t]), t
    accused = {r["AccusedMasterID"] for r in ds.tables["Accused"]}
    assert all(r["AccusedMasterID"] in accused for r in ds.tables["ArrestSurrender"])
    assert all(r["AccusedMasterID"] in accused for r in ds.tables["inv_arrestsurrenderaccused"])
    units = {r["UnitID"] for r in ds.tables["Unit"]}
    emps = {r["EmployeeID"] for r in ds.tables["Employee"]}
    assert all(r["PoliceStationID"] in units for r in ds.tables["CaseMaster"])
    assert all(r["PolicePersonID"] in emps for r in ds.tables["CaseMaster"])

    # The two properties that models actually depend on.
    repeat = sum(1 for p in ds.people if p.offences > 2)
    assert repeat > 0, "no habitual offenders — recidivism would be unlearnable"
    canonical = {p.uid: full_record_name(p.name_en, p.patronym, p.gender) for p in ds.people}
    variants = sum(1 for a in ds.tables["Accused"]
                   if a["AccusedName"] != canonical[ds.accused_truth[a["AccusedMasterID"]]])
    assert variants > 0, "no name variants — entity resolution would have nothing to find"

    print(f"build OK: cases={len(cases)} accused={len(accused)} "
          f"habitual={repeat} name-variants={variants}/{len(accused)} "
          f"units={len(units)} employees={len(emps)}")
