"""Persist a generated Dataset to the Catalyst Data Store.

Two paths, same rows:

  load_dataset(ds)   writes through data.ds. On the sqlite backend that is the whole
                     story. On Catalyst it works too, but a 25K-case rebuild is ~1,500
                     REST calls, so it is not how you seed a fresh environment.

  write_csvs(ds)     dumps one CSV per table for `catalyst ds:import`, which is the
                     sanctioned bulk path into Data Store and needs no credentials
                     beyond the CLI login you already have.

Insert order follows the ER's foreign keys: masters, then Unit/Employee, then CaseMaster,
then everything that hangs off a case. Anything else leaves dangling references.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from .. import ds as store
from .build import Dataset

# Parents before children. Not alphabetical, not arbitrary — this is the FK topology.
LOAD_ORDER = [
    "State", "District", "UnitType", "Rank", "Designation", "Court",
    "CaseCategory", "GravityOffence", "CaseStatusMaster",
    "OccupationMaster", "ReligionMaster", "CasteMaster",
    "CrimeHead", "CrimeSubHead", "Act", "Section", "CrimeHeadActSection",
    "Unit", "Employee",
    "CaseMaster",
    "ComplainantDetails", "Victim", "Accused", "ActSectionAssociation",
    "ArrestSurrender", "inv_arrestsurrenderaccused", "ChargesheetDetails",
]

# Wiped on rebuild. The record layer plus everything DERIVED from it: identities resolved
# out of Accused rows, the graph built from those identities, the financial layer keyed to
# them. Leaving derived rows behind after a rebuild leaves them pointing at cases that no
# longer exist — and a citation to a deleted FIR is the one failure a citation-grounded
# system must never have. vx_district_socioeconomic (real Census data) and the
# session/conversation/audit tables are deliberately NOT wiped.
DERIVED = ["vx_person", "vx_accused_identity", "vx_graph_edge", "vx_account", "vx_txn"]


def load_dataset(ds: Dataset, wipe: bool = True) -> dict[str, int]:
    if wipe:
        store.truncate(list(reversed(LOAD_ORDER)) + DERIVED)
    counts = {}
    for table in LOAD_ORDER:
        rows = ds.tables.get(table) or []
        if rows:
            counts[table] = store.insert(table, rows)
    return counts


def _csv_value(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v)


def write_csvs(ds: Dataset, out_dir: str | Path = ".veritas/seed") -> list[Path]:
    """One CSV per table, in FK order, for `catalyst ds:import`."""
    from ..schema import TABLES

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, table in enumerate(LOAD_ORDER):
        rows = ds.tables.get(table) or []
        if not rows:
            continue
        cols = [c.name for c in TABLES[table]]
        # Numbered so the import order is obvious to a human running them by hand.
        path = out / f"{i:02d}_{table}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows([[_csv_value(r.get(c)) for c in cols] for r in rows])
        written.append(path)
    return written


if __name__ == "__main__":
    import random

    from .build import generate

    store.reset_for_tests()                       # in-memory sqlite
    ds = generate(random.Random(7), 200)
    counts = load_dataset(ds)

    # The load is only correct if the data is still queryable *as the ER intends* —
    # i.e. a case joins to its station, its IO, its sections and its accused.
    n = store.scalar('SELECT COUNT("CaseMasterID") AS c FROM "CaseMaster"')
    assert n == 200, n
    row = store.one(
        'SELECT "CaseMaster"."CrimeNo", "Unit"."UnitName", "CrimeSubHead"."CrimeHeadName" '
        'FROM "CaseMaster" '
        'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
        'JOIN "CrimeSubHead" ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID"')
    assert row and len(row["CrimeNo"]) == 18 and row["UnitName"] and row["CrimeHeadName"], row

    # No orphans: every accused row's case exists.
    orphans = store.scalar(
        'SELECT COUNT("AccusedMasterID") AS c FROM "Accused" WHERE "CaseMasterID" NOT IN '
        '(SELECT "CaseMasterID" FROM "CaseMaster")')
    assert orphans == 0, f"{orphans} orphaned accused rows"

    paths = write_csvs(ds, ".veritas/seed-selfcheck")
    print(f"load OK: {sum(counts.values())} rows across {len(counts)} tables; "
          f"{len(paths)} CSVs; sample join -> {row['CrimeNo']} @ {row['UnitName']} "
          f"({row['CrimeHeadName']})")
