"""Backfill `CaseMaster.BriefFacts` in place, using the current narrative generator.

`build._narrative` only changes what a *newly generated* case looks like. It does
nothing for a dataset already loaded — and the record layer of an already-seeded
environment (case ids, accused rows, identities, the financial layer, the graph) is
otherwise valid and expensive to reproduce exactly.

So this does not regenerate the dataset. It recomputes ONE column, from fields the
rows already have, for every existing case — no case is added, removed or renumbered,
and no accused/identity/financial/graph row is touched. Deterministic per case (seeded
on CaseMasterID), so re-running it twice produces the same text.

Every input below is read back out of the record layer rather than re-drawn, which is
what makes this a re-render rather than a second, divergent generation:

  station     Unit.UnitName, via the case's own PoliceStationID
  locality    geo.locality() over the case's own latitude/longitude — the same
              function, over the same coordinates, that placed the incident
  sections    ActSectionAssociation for this case, in the recorded SectionOrderID order
  status      CaseMaster.CaseStatusID
  signature   the resolved PersonUID of accused A1 — so an offender's habitual MO
              carries across their cases here exactly as it does at generation time
              (a different id space than the generator's private TruePerson.uid, but
              the only property `_signature_choice` needs is that it be stable per
              person, and PersonUID is)

The vector index (`fir_narrative`) is derived from `BriefFacts` and must be rebuilt
after this runs — `apps/api`'s `/jobs/refresh` already does that, so this is meant to
be followed by a call to it, not to duplicate its reindexing itself.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

from .. import ds
from ..districts import all_districts
from .build import _narrative
from .geo import locality as locality_name


def _case_rows() -> list[dict]:
    return ds.query(
        'SELECT "CaseMaster"."CaseMasterID", "CrimeSubHead"."CrimeHeadName" AS "crime_type", '
        '       "District"."DistrictName" AS "district", "Unit"."UnitName" AS "station", '
        '       "CaseMaster"."CrimeRegisteredDate" AS "filed", '
        '       "CaseMaster"."IncidentFromDate" AS "occ_from", '
        '       "CaseMaster"."CaseStatusID", '
        '       "CaseMaster"."latitude", "CaseMaster"."longitude" '
        'FROM "CaseMaster" '
        'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
        'JOIN "District" ON "Unit"."DistrictID" = "District"."DistrictID" '
        'LEFT JOIN "CrimeSubHead" '
        '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID"')


def _accused_counts() -> Counter:
    rows = ds.query('SELECT "CaseMasterID" FROM "Accused"')
    return Counter(r["CaseMasterID"] for r in rows)


def _sections_by_case() -> dict:
    """CaseMasterID -> the section codes on it, in the order they were recorded.

    A separate query rather than a fifth JOIN on `_case_rows`: ZCQL caps a statement at
    four, that one already spends three, and a section list is one-to-many anyway — it
    would multiply the case rows rather than widen them.
    """
    out: dict = defaultdict(list)
    for r in ds.query('SELECT "CaseMasterID", "SectionID", "SectionOrderID" '
                      'FROM "ActSectionAssociation"'):
        out[r["CaseMasterID"]].append((r["SectionOrderID"] or 0, r["SectionID"]))
    return {cid: tuple(s for _, s in sorted(v)) for cid, v in out.items()}


def _lead_person_by_case() -> dict:
    """CaseMasterID -> the resolved PersonUID of accused A1, where one resolved.

    A1 is the ER's own ordering label for the accused on a case, so "the lead" needs no
    invention here; and an unresolved accused simply yields no signature, which
    `_signature_choice` already treats as "this case has no habit to express".
    """
    lead_acc = {r["CaseMasterID"]: r["AccusedMasterID"]
                for r in ds.query('SELECT "CaseMasterID", "AccusedMasterID", "PersonID" '
                                  'FROM "Accused"')
                if str(r.get("PersonID") or "").upper() == "A1"}
    identity = {r["AccusedMasterID"]: r["PersonUID"]
                for r in ds.query('SELECT "AccusedMasterID", "PersonUID" '
                                  'FROM "vx_accused_identity"')}
    return {cid: identity[aid] for cid, aid in lead_acc.items() if aid in identity}


def backfill_narratives(batch_size: int = 500) -> int:
    """Recompute BriefFacts for every case. Returns the number of rows updated."""
    cases = _case_rows()
    counts = _accused_counts()
    sections = _sections_by_case()
    leads = _lead_person_by_case()
    code_for = {d.name: d.code for d in all_districts()}

    updates = []
    for r in cases:
        crime_type = r.get("crime_type")
        if not crime_type:
            continue                  # nothing to build a narrative from; leave as-is
        filed = ds.to_dt(r["filed"])
        occ_from = ds.to_dt(r["occ_from"]) or filed
        if not filed:
            continue
        cid = r["CaseMasterID"]

        code = code_for.get(r["district"])
        where = ""
        if code and r.get("latitude") is not None and r.get("longitude") is not None:
            try:
                where = locality_name(float(r["latitude"]), float(r["longitude"]), code)
            except (TypeError, ValueError):
                where = ""            # a coordinate the record cannot supply names no place

        # Seeded on the case id, not a shared Random: independent of iteration order
        # or batch boundaries, so re-running this later for a subset of cases still
        # reproduces the same text for the cases it touches.
        rng = random.Random(cid)
        text = _narrative(
            rng, crime_type, r["district"], filed, occ_from, counts.get(cid, 0),
            station=r.get("station") or "",
            locality=where,
            sections=sections.get(cid, ()),
            status=int(r.get("CaseStatusID") or 1),
            signature=leads.get(cid))
        updates.append({"CaseMasterID": cid, "BriefFacts": text})

    total = 0
    for i in range(0, len(updates), batch_size):
        total += ds.update("CaseMaster", "CaseMasterID", updates[i:i + batch_size])
    return total
