"""Backfill `ActSectionAssociation` in place, using the current BNS-aware act/section
picker (`refdata.act_and_sections_for`).

Same shape as `narrative_backfill.py` and for the same reason: a live, already-seeded
dataset predates the BNS transition fix, and its record layer (case ids, accused rows,
identities, the financial layer, the graph) is otherwise valid and expensive to
reproduce exactly. So this does not regenerate the dataset — it recomputes ONE child
table, per case, from a fact the case already has (its own `IncidentFromDate`), against
the crime-type prior's own canonical IPC sections. No case is added, removed or
renumbered, and no accused/identity/financial/graph row is touched.

Deterministic: `act_and_sections_for` is a pure function of the crime type and the
offence date, so re-running this twice produces the same rows. Must run BEFORE
`narrative_backfill.backfill_narratives()` on a dataset that needs both — the
narrative's "Offences registered under section X" line reads straight out of
`ActSectionAssociation`, so a narrative backfill run against not-yet-corrected sections
would faithfully re-cite the wrong ones.
"""
from __future__ import annotations

from .. import ds
from ..priors import crime_types
from . import refdata as rd


def backfill_act_sections(batch_size: int = 500) -> int:
    """Recompute ActSectionAssociation for every case. Returns the number of cases
    touched."""
    ipc_sections_of = {p.crime_type: p.ipc_sections for p in crime_types()}

    cases = ds.query(
        'SELECT "CaseMaster"."CaseMasterID", "CaseMaster"."IncidentFromDate", '
        '       "CrimeSubHead"."CrimeHeadName" AS "crime_type" '
        'FROM "CaseMaster" '
        'LEFT JOIN "CrimeSubHead" '
        '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID"')

    updates: list[tuple[int, str, tuple[str, ...]]] = []
    for r in cases:
        crime_type = r.get("crime_type")
        sections = ipc_sections_of.get(crime_type)
        occ = ds.to_dt(r.get("IncidentFromDate"))
        if not sections or not occ:
            continue          # nothing to recompute from; leave as-is
        act, secs = rd.act_and_sections_for(crime_type, occ.date(), sections)
        updates.append((r["CaseMasterID"], act, secs))

    total = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        ids = [cid for cid, _, _ in batch]
        ds.execute('DELETE FROM "ActSectionAssociation" WHERE "CaseMasterID" IN :ids',
                  {"ids": ids})
        rows = [
            {"CaseMasterID": cid, "ActID": act, "SectionID": sec,
             "ActOrderID": 1, "SectionOrderID": order}
            for cid, act, secs in batch
            for order, sec in enumerate(secs, start=1)
        ]
        ds.insert("ActSectionAssociation", rows)
        total += len(batch)
    return total
