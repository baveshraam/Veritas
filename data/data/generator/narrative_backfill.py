"""Backfill `CaseMaster.BriefFacts` in place, using the fixed narrative generator.

BUG-023's fix (widened `_MO_VARIANTS`, per-case time-of-day and offender-count
slot-filling — see `build._narrative`) only changes what a *newly generated* case's
narrative looks like. It does nothing for a dataset already loaded — and the record
layer for an already-seeded environment (case ids, accused rows, identities, the
financial layer, the graph) is otherwise valid and expensive to reproduce exactly.

So this does not regenerate the dataset. It recomputes ONE column, from fields the
row already has, for every existing case — no case is added, removed, or renumbered,
and no accused/identity/financial/graph row is touched. Deterministic per case
(seeded on CaseMasterID), so re-running it twice produces the same text.

The vector index (`fir_narrative`) is derived from `BriefFacts` and must be rebuilt
after this runs — `apps/api`'s `/jobs/refresh` already does that, so this is meant to
be followed by a call to it, not to duplicate its reindexing itself.
"""
from __future__ import annotations

import random
from collections import Counter

from .. import ds
from .build import _narrative


def _case_rows() -> list[dict]:
    return ds.query(
        'SELECT "CaseMaster"."CaseMasterID", "CrimeSubHead"."CrimeHeadName" AS "crime_type", '
        '       "District"."DistrictName" AS "district", '
        '       "CaseMaster"."CrimeRegisteredDate" AS "filed", '
        '       "CaseMaster"."IncidentFromDate" AS "occ_from" '
        'FROM "CaseMaster" '
        'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
        'JOIN "District" ON "Unit"."DistrictID" = "District"."DistrictID" '
        'LEFT JOIN "CrimeSubHead" '
        '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID"')


def _accused_counts() -> Counter:
    rows = ds.query('SELECT "CaseMasterID" FROM "Accused"')
    return Counter(r["CaseMasterID"] for r in rows)


def backfill_narratives(batch_size: int = 500) -> int:
    """Recompute BriefFacts for every case. Returns the number of rows updated."""
    cases = _case_rows()
    counts = _accused_counts()

    updates = []
    for r in cases:
        crime_type = r.get("crime_type")
        if not crime_type:
            continue                  # nothing to build a narrative from; leave as-is
        filed = ds.to_dt(r["filed"])
        occ_from = ds.to_dt(r["occ_from"]) or filed
        if not filed:
            continue
        n_accused = counts.get(r["CaseMasterID"], 0)
        # Seeded on the case id, not a shared Random: independent of iteration order
        # or batch boundaries, so re-running this later for a subset of cases still
        # reproduces the same text for the cases it touches.
        rng = random.Random(r["CaseMasterID"])
        text = _narrative(rng, crime_type, r["district"], filed, occ_from, n_accused)
        updates.append({"CaseMasterID": r["CaseMasterID"], "BriefFacts": text})

    total = 0
    for i in range(0, len(updates), batch_size):
        total += ds.update("CaseMaster", "CaseMasterID", updates[i:i + batch_size])
    return total
