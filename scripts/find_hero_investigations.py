#!/usr/bin/env python
"""Identify a handful of "hero" investigations already present in the existing
10k-case dataset — people/cases rich enough (priors + a real co-offending network +
a financial trail) to demonstrate the full investigation loop end to end.

Explicitly NOT a data generator: reads the existing seeded dataset, ranks what's
already there, and reports the FIR numbers/person names an officer could actually
type into the console. Regenerating the dataset to manufacture rich cases would be
exactly the casual regeneration this project's own rules exclude (CLAUDE.md).
"""
import sys

sys.path.insert(0, "data")
sys.path.insert(0, "packages/rag_agent")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    from data import ds

    # Richness = prior case count (a real record, not a network artifact) + number
    # of distinct co-accused (a real network to walk) + whether they own an
    # account with at least one transaction (a real money trail to trace).
    rows = ds.query(
        'SELECT "PersonUID", "CanonicalName", "PageRank", "CommunityID", '
        '"IsHabitualOffender" FROM "vx_person" '
        'WHERE "IsHabitualOffender" = 1 ORDER BY "PageRank" DESC LIMIT 40'
    )
    if not rows:
        print("No habitual-offender rows found — is VERITAS_SQLITE pointed at the "
             "seeded mirror (data/.veritas/ds.sqlite3)?")
        return

    candidates = []
    for r in rows:
        pid = r["PersonUID"]
        case_count = ds.one(
            'SELECT COUNT(*) as n FROM "vx_accused_identity" WHERE "PersonUID" = :pid',
            {"pid": pid})["n"]
        assoc_count = ds.one(
            'SELECT COUNT(DISTINCT "SrcId") as n FROM "vx_graph_edge" '
            'WHERE "EdgeType" = \'CO_ACCUSED_WITH\' AND "DstId" = :node',
            {"node": f"person:{pid}"})["n"]
        txn_count = ds.one(
            'SELECT COUNT(*) as n FROM "vx_txn" t '
            'JOIN "vx_account" a ON t."SrcAccountID" = a."AccountID" OR t."DstAccountID" = a."AccountID" '
            'WHERE a."PersonUID" = :pid',
            {"pid": pid})["n"]
        richness = case_count + assoc_count + (2 if txn_count else 0)
        candidates.append((richness, pid, r["CanonicalName"], case_count, assoc_count,
                           txn_count, r["CommunityID"]))

    candidates.sort(key=lambda c: -c[0])
    print(f"{'name':30s} {'person_id':>10s} {'cases':>6s} {'assoc':>6s} {'txns':>6s} {'community':>10s}")
    for richness, pid, name, cases, assoc, txns, community in candidates[:8]:
        print(f"{name[:30]:30s} {pid!s:>10s} {cases:>6d} {assoc:>6d} {txns:>6d} {community!s:>10s}")

        fir = ds.one(
            'SELECT "CaseMasterID" FROM "Accused" a '
            'JOIN "vx_accused_identity" i ON a."AccusedMasterID" = i."AccusedMasterID" '
            'WHERE i."PersonUID" = :pid', {"pid": pid})
        if fir:
            crime_no = ds.one('SELECT "CrimeNo" FROM "CaseMaster" WHERE "CaseMasterID" = :cid',
                              {"cid": fir["CaseMasterID"]})
            if crime_no:
                print(f"    -> \"Tell me about {name}\" / FIR {crime_no['CrimeNo']}")


if __name__ == "__main__":
    main()
