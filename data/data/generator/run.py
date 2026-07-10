"""Rebuild the whole synthetic dataset. `python -m data.generator.run`.

Order: init schema -> generate in memory -> load to Postgres. Neo4j sync,
entity resolution, and embeddings attach here as they land (graph_sync next).
Rerunning this is the only way the dataset refreshes — there is no streaming
ingestion.
"""
import argparse
import random

from ..db import init_db
from ..graph import init_graph
from .build import generate
from .graph_sync import sync_graph
from .load import load_dataset


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild the Veritas synthetic dataset")
    ap.add_argument("--firs", type=int, default=10000, help="number of FIRs (10-50K typical)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-init", action="store_true", help="skip schema init (assume tables exist)")
    ap.add_argument("--no-graph", action="store_true", help="skip Neo4j sync (Postgres only)")
    args = ap.parse_args()

    if not args.no_init:
        init_db()
    ds = generate(random.Random(args.seed), args.firs)
    load_dataset(ds)
    if not args.no_graph:
        init_graph()
        sync_graph(ds)
    print(f"loaded: officers={len(ds.officers)} persons={len(ds.persons)} "
          f"firs={len(ds.firs)} records={len(ds.criminal_records)}")


if __name__ == "__main__":
    main()
