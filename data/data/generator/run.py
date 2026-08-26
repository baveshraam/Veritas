"""Rebuild the whole synthetic dataset. `python -m data.generator.run`.

    schema -> real Census ground truth -> generate -> load records
           -> RESOLVE IDENTITIES -> financial layer -> graph edges -> graph algorithms
           -> embeddings

The identity step is not optional and cannot move. The organizers' ER has no person: an
`Accused` row belongs to exactly one case, and its `PersonID` is a per-case label ("A1").
Until Fellegi-Sunter reconstructs people out of those rows, two cases naming the same man
are two strangers — so there is no co-offending to find, no account to attribute to a
human, and no network to run PageRank over. Everything downstream of it depends on it.

Rerunning this is the only way the dataset refreshes; there is no streaming ingestion, and
with no real-time source there is nothing for one to ingest.
"""
import argparse
import json
import os
import random
from pathlib import Path

from .. import ds as store
from .build import generate
from .financial import make_financial
from .graph_sync import sync_graph
from .load import load_dataset

# AML ground truth. Deliberately a file, not a column: `vx_txn.FlaggedSuspicious` is a
# *detector output*, and a generator that writes its own answer key into the table the
# models read would make every AML metric meaningless.
AML_LABELS = Path(".veritas/aml_labels.json")

# Identity ground truth: AccusedMasterID -> TruePerson.uid. Same reasoning as AML_LABELS
# — a file, not a column, and never loaded back into the record layer. Before this, the
# claimed entity-resolution F1 was only recomputable in-process against a fresh
# generate() call; this lets it be recomputed against whatever is actually live on
# Catalyst by re-fetching vx_accused_identity and comparing against this file. Env-var
# overridable for the same reason VERITAS_AML_LABELS is (gnn.py) — tests point it at a
# tmp path instead of touching the real .veritas/ directory.
IDENTITY_ANSWER_KEY = Path(os.getenv("VERITAS_IDENTITY_ANSWER_KEY",
                                      ".veritas/identity_answer_key.json"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild the Veritas synthetic dataset")
    ap.add_argument("--cases", type=int, default=10000, help="number of FIRs (10-50K typical)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-graph", action="store_true", help="skip graph edges + algorithms")
    ap.add_argument("--no-embed", action="store_true", help="skip vector indexing")
    ap.add_argument("--csv", action="store_true", help="also dump seed CSVs for ds:import")
    args = ap.parse_args()

    store.init_db()

    # Real ground truth (Census 2011) before anything synthetic. Upserted, not truncated,
    # so it survives a rebuild — the causal layer is dead without it.
    from ..socioeconomic import load as load_socioeconomic
    print(f"socioeconomic: {load_socioeconomic()} districts (Census 2011)")

    rng = random.Random(args.seed)
    ds = generate(rng, args.cases)
    counts = load_dataset(ds)
    print(f"records: {sum(counts.values())} rows across {len(counts)} tables")

    # Answer key, before resolution runs, so it reflects generation truth regardless of
    # what resolve_entities() below does with it.
    IDENTITY_ANSWER_KEY.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_ANSWER_KEY.write_text(json.dumps(ds.accused_truth), encoding="utf-8")

    # Identity, before anything that needs a person.
    from ml_models.entity_resolution import resolve_entities
    matches = resolve_entities()
    people = store.query('SELECT "PersonUID", "IsHabitualOffender" FROM "vx_person"')
    links = sum(1 for m in matches if m.decision == "link")
    print(f"identities: {len(people)} people from {len(ds.accused_truth)} accused rows "
          f"({links} links, answer key -> {IDENTITY_ANSWER_KEY})")

    # Financial layer — accounts belong to people, so it could not have run any earlier.
    case_ids = [c["CaseMasterID"] for c in ds.tables["CaseMaster"]]
    accounts, txns, labels = make_financial(rng, people, case_ids)
    store.insert("vx_account", accounts)
    store.insert("vx_txn", txns)
    AML_LABELS.parent.mkdir(parents=True, exist_ok=True)
    AML_LABELS.write_text(json.dumps(labels), encoding="utf-8")
    print(f"financial: {len(accounts)} accounts, {len(txns)} txns, "
          f"{len(labels)} injected (labels -> {AML_LABELS})")

    if not args.no_graph:
        print(f"graph: {sync_graph()} edges")
        from ..gds import run_all as run_gds
        print(f"gds: {run_gds()}")

    if not args.no_embed:
        from ..embeddings.index_job import run_all
        print(f"embeddings: {run_all()}")

    if args.csv:
        from .load import write_csvs
        print(f"seed CSVs: {len(write_csvs(ds))} files")


if __name__ == "__main__":
    main()
