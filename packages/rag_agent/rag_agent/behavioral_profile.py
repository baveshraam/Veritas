"""Evidence-backed behavioral profile — "behavioral profiling" done the way the
challenge actually means it, not the way a risk score does. A risk score
(packages/ml_models/.../risk/scoring.py) is one number. This is the readable
pattern underneath the cases that number would be scored from: a recurring method,
a time-of-day habit, the geographic range someone actually operates in, an
escalation in offence severity where the record genuinely shows one, and which
associates keep reappearing across multiple cases rather than a single one-off.

Never demographic. Caste, religion and gender are excluded from every model in
this system on the same rule (CLAUDE.md §6: "storing is not scoring") — this
module inherits that rule by construction, since it never reads those columns at
all. Every finding traces to the specific FIR numbers it was read from and is
built entirely from a resolved person's OWN case history — nothing here is a fact
any single record states; each line is read ACROSS several, which is exactly why
every finding names them rather than asserting the pattern on its own authority.
"""
from __future__ import annotations

import math

from data import ds
from data.generator import refdata as rd

MIN_CASES_FOR_A_PATTERN = 3     # one or two cases is a history, not yet a pattern
MAJORITY_FRACTION = 0.5         # a bucket must cover more than half the cases

_TIME_OF_DAY = [
    (5, "early morning (before 5 AM)"), (12, "morning"), (17, "afternoon"),
    (21, "evening"), (24, "late night"),
]


def _time_bucket(hour: int) -> str:
    """Mirrors copilot.brief._time_bucket's five buckets — kept local rather than
    imported since it's a five-line pure function, not a shared dependency."""
    for ceiling, label in _TIME_OF_DAY:
        if hour < ceiling:
            return label
    return _TIME_OF_DAY[-1][1]


def _mo_clause(narrative: str | None) -> str:
    return (narrative or "").split("district. ", 1)[-1].split(",")[0].strip()


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _fir_list(cases: list[dict]) -> str:
    return ", ".join(f"FIR {c.get('fir_number') or c['fir_id']}" for c in cases)


def _hours_by_case(fir_ids: list[str]) -> dict[str, int]:
    if not fir_ids:
        return {}
    rows = ds.query('SELECT "CaseMasterID", "IncidentFromDate" FROM "CaseMaster" '
                    'WHERE "CaseMasterID" IN :ids', {"ids": [int(i) for i in fir_ids]})
    out = {}
    for r in rows:
        dt = ds.to_dt(r.get("IncidentFromDate"))
        if dt:
            out[str(r["CaseMasterID"])] = dt.hour
    return out


def _stable_associates(person_uid: str, fir_ids: list[str]) -> list[tuple[str, int]]:
    """Co-accused appearing across more than one of this person's own cases — the
    "who does he keep working with" half of a behavioral profile. A one-off
    co-accused on a single case is not an association pattern; someone who shows
    up on three of this person's six cases is."""
    if not fir_ids:
        return []
    rows = ds.query(
        'SELECT "vx_accused_identity"."PersonUID", "vx_person"."CanonicalName", '
        '       "Accused"."CaseMasterID" '
        'FROM "Accused" '
        'JOIN "vx_accused_identity" '
        '  ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID" '
        'JOIN "vx_person" ON "vx_accused_identity"."PersonUID" = "vx_person"."PersonUID" '
        'WHERE "Accused"."CaseMasterID" IN :ids '
        '  AND "vx_accused_identity"."PersonUID" != :self',
        {"ids": [int(i) for i in fir_ids], "self": int(person_uid)})
    by_person: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        key = (str(r["PersonUID"]), r["CanonicalName"] or f"person {r['PersonUID']}")
        by_person.setdefault(key, set()).add(str(r["CaseMasterID"]))
    return sorted(
        ((name, len(cids)) for (_, name), cids in by_person.items() if len(cids) > 1),
        key=lambda t: -t[1])


def build_profile(person_uid: str, cases: list[dict]) -> list[dict]:
    """cases = sql_agent.person_record(person_uid)'s own output. Returns findings,
    each `{"claim": str, "fir_ids": [...]}` — the claim names the FIR numbers it
    rests on inline, and fir_ids is what the caller cites the EvidenceItem to.
    Empty list means nothing here clears the bar for a pattern (too few cases, or
    no field lines up) — a correct, common answer, not a failure."""
    if len(cases) < MIN_CASES_FOR_A_PATTERN:
        return []

    findings: list[dict] = []
    fir_ids = [c["fir_id"] for c in cases]

    # 1. Time-of-day.
    hours = _hours_by_case(fir_ids)
    if len(hours) >= MIN_CASES_FOR_A_PATTERN:
        buckets: dict[str, list[dict]] = {}
        for c in cases:
            h = hours.get(c["fir_id"])
            if h is not None:
                buckets.setdefault(_time_bucket(h), []).append(c)
        label, in_bucket = max(buckets.items(), key=lambda kv: len(kv[1]))
        if len(in_bucket) / len(hours) > MAJORITY_FRACTION:
            findings.append({
                "claim": f"Incidents cluster in the {label} ({len(in_bucket)} of "
                        f"{len(hours)} cases with a recorded time): "
                        f"{_fir_list(in_bucket)}.",
                "fir_ids": [c["fir_id"] for c in in_bucket]})

    # 2. Recurring method.
    mo_groups: dict[str, list[dict]] = {}
    for c in cases:
        mo = _mo_clause(c.get("narrative"))
        if mo:
            mo_groups.setdefault(mo, []).append(c)
    for mo, group in sorted(mo_groups.items(), key=lambda kv: -len(kv[1])):
        if len(group) >= 2:
            findings.append({
                "claim": f"The same method recurs across {len(group)} case(s) "
                        f"(\"{mo}\"): {_fir_list(group)}.",
                "fir_ids": [c["fir_id"] for c in group]})
            break   # the single strongest recurrence, not every MO seen once

    # 3. Geographic range.
    points = [(c["fir_id"], c["lat"], c["lng"]) for c in cases
             if c.get("lat") is not None and c.get("lng") is not None]
    if len(points) >= 2:
        worst = max(
            (_haversine_km(a[1], a[2], b[1], b[2]), a, b)
            for i, a in enumerate(points) for b in points[i + 1:])
        span_km, a, b = worst
        districts = sorted({c["district"] for c in cases if c.get("district")})
        findings.append({
            "claim": (f"Recorded incidents span {len(districts)} district(s) "
                     f"({', '.join(districts)}) and up to {span_km:.0f} km apart."
                     if len(districts) > 1 else
                     f"All recorded incidents fall within a {span_km:.0f} km "
                     f"radius, in {districts[0] if districts else 'one area'}."),
            "fir_ids": fir_ids})

    # 4. Escalation — only reported where the record's own gravity classification
    # actually shows it, never inferred from crime-type labels alone.
    dated = sorted((c for c in cases if c.get("date_filed")), key=lambda c: c["date_filed"])
    if len(dated) >= 2:
        gravities = [rd.gravity_id(c["crime_type"]) if c.get("crime_type") else None
                    for c in dated]
        heinous = rd.GRAVITY["Heinous"]
        first_heinous = next((i for i, g in enumerate(gravities) if g == heinous), None)
        if first_heinous is not None and first_heinous > 0 and \
                any(g != heinous for g in gravities[:first_heinous]):
            findings.append({
                "claim": (f"Offence severity has increased over time: "
                         f"{dated[0]['crime_type']} (FIR "
                         f"{dated[0].get('fir_number') or dated[0]['fir_id']}) "
                         f"preceded {dated[first_heinous]['crime_type']} "
                         f"(FIR {dated[first_heinous].get('fir_number') or dated[first_heinous]['fir_id']})."),
                "fir_ids": [dated[0]["fir_id"], dated[first_heinous]["fir_id"]]})

    # 5. Stable associates.
    associates = _stable_associates(person_uid, fir_ids)
    if associates:
        top = associates[:3]
        findings.append({
            "claim": ("Recorded working with the same associate(s) across "
                     "multiple cases: " +
                     "; ".join(f"{name} (on {n} case(s))" for name, n in top) + "."),
            "fir_ids": fir_ids})

    return findings
