"""Build an internally consistent synthetic dataset in memory.

Pure functions: given a seeded Random and a FIR count, return dataclass rows with
referential integrity already wired (every FIR's complainant/IO/accused point at
real generated persons/officers). No DB, no I/O — data/generator/load.py persists
the result, data/generator/graph_sync.py mirrors it to Neo4j. Kept pure so the
whole build is unit-testable without a running database.
"""
import hashlib
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..priors import CrimeTypePrior, sample_crime_type, sample_district
from .geo import sample_point
from .names import sample_name

NOW = date(2026, 7, 1)
ROLES = ("IO", "SHO", "DSP", "SP", "IG", "SCRB_Analyst")
BAIL_STATUSES = ("Not Applied", "Granted", "Rejected", "Pending")
GANGS = ("Sikhwal Gang", "KGF Syndicate", "Nayak Group", "Hubli Chain-Snatchers",
         "Coastal Smuggling Ring", "Peenya Auto-Lifters")

_MO = {
    "Theft": "Pickpocketing in a crowded market",
    "House Burglary": "Entry via rear window after dark while occupants away",
    "Motor Vehicle Theft": "Two-wheeler lifted from an unguarded parking lot",
    "Robbery": "Chain-snatching from a two-wheeler pillion rider",
    "Cheating": "Fake investment scheme collecting advance deposits",
    "Cyber Crime": "OTP-phishing call impersonating a bank official",
    "Murder": "Assault with a blunt weapon following a prior dispute",
    "Narcotics": "Ganja transported concealed in a goods vehicle",
}


@dataclass
class Officer:
    officer_id: str
    badge_no: str
    name: str
    ps_code: str
    district_code: str
    role: str


@dataclass
class Person:
    person_id: str
    scrb_id: str
    name_en: str
    name_kn: str | None
    dob: date
    gender: str
    address_geom: str          # WKT
    aadhaar_hash: str
    criminal_history: bool
    risk_score: float | None
    gang_affiliation: str | None
    canonical_entity_id: str | None


@dataclass
class Fir:
    fir_id: str
    ps_code: str
    district_code: str
    fir_number: str
    date_filed: datetime
    ipc_sections: list[str]
    crime_type: str
    occurrence_from: datetime
    occurrence_to: datetime
    location_geom: str          # WKT
    district: str
    taluk: str
    complainant_id: str
    io_id: str
    case_status: str
    modus_operandi: str
    narrative: str


@dataclass
class CriminalRecord:
    record_id: str
    person_id: str
    fir_id: str
    role: str
    arrest_date: date | None
    bail_status: str
    conviction: bool


@dataclass
class Dataset:
    officers: list[Officer] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    firs: list[Fir] = field(default_factory=list)
    criminal_records: list[CriminalRecord] = field(default_factory=list)


def _uid() -> str:
    return str(uuid.uuid4())


def _aadhaar_hash(rng: random.Random) -> str:
    digits = "".join(str(rng.randint(0, 9)) for _ in range(12))
    return hashlib.sha256(digits.encode()).hexdigest()


def _ps_codes_for(district_code: str, n: int) -> list[str]:
    return [f"{district_code}-PS{i:02d}" for i in range(1, n + 1)]


def make_officers(rng: random.Random, districts: list[str]) -> list[Officer]:
    """~3 stations per active district, a handful of officers each, roles skewed to IO/SHO."""
    officers: list[Officer] = []
    seq = 1
    for dc in districts:
        for ps in _ps_codes_for(dc, 3):
            for role in ("SHO", "IO", "IO", "IO", "DSP"):
                officers.append(Officer(
                    officer_id=_uid(), badge_no=f"KAB{seq:05d}",
                    name=sample_name(rng, rng.choice("MF")),
                    ps_code=ps, district_code=dc, role=role))
                seq += 1
    # a thin senior/analyst layer, one per state
    for role in ("SP", "IG", "SCRB_Analyst"):
        officers.append(Officer(_uid(), f"KAB{seq:05d}", sample_name(rng, "M"),
                                districts[0] + "-HQ", districts[0], role))
        seq += 1
    return officers


def make_persons(rng: random.Random, n: int) -> list[Person]:
    persons: list[Person] = []
    for i in range(n):
        gender = "F" if rng.random() < 0.30 else "M"
        dc = sample_district(rng)
        age = rng.randint(18, 70)
        dob = date(NOW.year - age, rng.randint(1, 12), rng.randint(1, 28))
        persons.append(Person(
            person_id=_uid(), scrb_id=f"SCRB{i:07d}",
            name_en=sample_name(rng, gender), name_kn=None,
            dob=dob, gender=gender, address_geom=sample_point(rng, dc),
            aadhaar_hash=_aadhaar_hash(rng),
            criminal_history=False, risk_score=None,
            gang_affiliation=None, canonical_entity_id=None))
    return persons


def _case_status(rng: random.Random, prior: CrimeTypePrior) -> str:
    if rng.random() > prior.chargesheet_rate:
        return "Under Investigation"
    # chargesheeted → resolved by court per conviction rate
    r = rng.random()
    if r < prior.conviction_rate:
        return "Convicted"
    if r < prior.conviction_rate + 0.25:
        return "Acquitted"
    return "Chargesheeted"


def make_firs(rng: random.Random, officers: list[Officer], persons: list[Person],
              n: int) -> tuple[list[Fir], list[CriminalRecord]]:
    by_ps: dict[str, list[Officer]] = {}
    for o in officers:
        if o.role in ("IO", "SHO"):
            by_ps.setdefault(o.ps_code, []).append(o)
    active_ps = list(by_ps)

    firs: list[Fir] = []
    records: list[CriminalRecord] = []
    year_seq: dict[int, int] = {}
    accused_pool = persons

    for _ in range(n):
        prior = sample_crime_type(rng)
        ps = rng.choice(active_ps)
        dc = ps.split("-")[0]
        district = _district_name(dc)
        io = rng.choice(by_ps[ps])

        filed = _rand_datetime(rng, days_back=rng.randint(1, 1095))
        occ_from = filed - timedelta(hours=rng.randint(2, 240))   # crime precedes the report
        occ_to = min(occ_from + timedelta(hours=rng.randint(0, 12)), filed)
        yr = filed.year
        year_seq[yr] = year_seq.get(yr, 0) + 1

        complainant = rng.choice(persons)
        fir = Fir(
            fir_id=_uid(), ps_code=ps, district_code=dc,
            fir_number=f"{year_seq[yr]:04d}/{yr}",
            date_filed=filed, ipc_sections=list(prior.ipc_sections),
            crime_type=prior.crime_type, occurrence_from=occ_from, occurrence_to=occ_to,
            location_geom=sample_point(rng, dc), district=district, taluk=district,
            complainant_id=complainant.person_id, io_id=io.officer_id,
            case_status=_case_status(rng, prior),
            modus_operandi=_MO.get(prior.crime_type, f"{prior.crime_type} — routine method"),
            narrative=_stub_narrative(prior.crime_type, district, filed))
        firs.append(fir)

        for accused in _pick_accused(rng, accused_pool, complainant):
            accused.criminal_history = True
            arrested = rng.random() < 0.7
            records.append(CriminalRecord(
                record_id=_uid(), person_id=accused.person_id, fir_id=fir.fir_id,
                role="Accused",
                arrest_date=(filed.date() + timedelta(days=rng.randint(0, 30))) if arrested else None,
                bail_status=rng.choice(BAIL_STATUSES) if arrested else "Not Applied",
                conviction=(fir.case_status == "Convicted")))
    return firs, records


def _pick_accused(rng: random.Random, pool: list[Person], complainant: Person) -> list[Person]:
    k = rng.choices([1, 2, 3, 4], weights=[55, 25, 12, 8], k=1)[0]
    chosen: list[Person] = []
    while len(chosen) < k:
        p = rng.choice(pool)
        if p.person_id != complainant.person_id and p not in chosen:
            if p.gang_affiliation is None and rng.random() < 0.15:
                p.gang_affiliation = rng.choice(GANGS)
            chosen.append(p)
    return chosen


def _rand_datetime(rng: random.Random, days_back: int) -> datetime:
    base = datetime(NOW.year, NOW.month, NOW.day) - timedelta(days=days_back)
    return base + timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0, 59))


def _stub_narrative(crime_type: str, district: str, filed: datetime) -> str:
    return (f"On {filed:%d %b %Y}, a case of {crime_type.lower()} was registered in "
            f"{district} district. Investigation is being carried out as per procedure.")


def _district_name(code: str) -> str:
    from ..districts import canonical_name
    return canonical_name(code) or code


def generate(rng: random.Random, n_firs: int) -> Dataset:
    """Top-level: derive person/officer counts from FIR count, build a coherent set."""
    n_persons = max(20, int(n_firs * 0.7))
    # only spin up stations in districts that will actually carry crime volume
    districts = sorted({sample_district(rng) for _ in range(min(31, n_firs))})
    officers = make_officers(rng, districts)
    persons = make_persons(rng, n_persons)
    firs, records = make_firs(rng, officers, persons, n_firs)
    return Dataset(officers=officers, persons=persons, firs=firs, criminal_records=records)


if __name__ == "__main__":
    ds = generate(random.Random(7), 500)
    print(f"officers={len(ds.officers)} persons={len(ds.persons)} "
          f"firs={len(ds.firs)} records={len(ds.criminal_records)}")
