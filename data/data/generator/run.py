"""Rebuild the whole synthetic dataset. `python -m data.generator.run`.

Order: init schema -> generate in memory -> load records -> build the graph edge
list -> graph algorithms -> entity resolution -> embeddings. Rerunning this is the
only way the dataset refreshes — there is no streaming ingestion.
"""
import argparse
import random

from ..db import init_db
from .build import generate
from .financial import make_financial
from .graph_sync import sync_graph
from .load import load_dataset


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild the Veritas synthetic dataset")
    ap.add_argument("--firs", type=int, default=10000, help="number of FIRs (10-50K typical)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-init", action="store_true", help="skip schema init (assume tables exist)")
    ap.add_argument("--no-graph", action="store_true", help="skip graph edge build + algorithms")
    ap.add_argument("--no-embed", action="store_true", help="skip vector indexing")
    ap.add_argument("--no-er", action="store_true", help="skip batch entity resolution")
    args = ap.parse_args()

    if not args.no_init:
        init_db()

    # Real ground truth (Census 2011) before anything synthetic. It is upserted, not
    # truncated, so it survives dataset rebuilds — and the causal layer is dead
    # without it, so a rebuild that silently skipped it would be worse than one that
    # fails here.
    from ..socioeconomic import load as load_socioeconomic
    print(f"socioeconomic: {load_socioeconomic()} districts (Census 2011)")

    rng = random.Random(args.seed)
    ds = generate(rng, args.firs)
    fin = make_financial(rng, ds)
    load_dataset(ds)
    if not args.no_graph:
        sync_graph(ds, fin)
        from ..gds import run_all as run_gds
        print(f"gds: {run_gds()}")   # pagerank/community/betweenness for HippoRAG + Louvain

        # Batch entity resolution — the ONLY caller of resolve_entities. Runs after
        # the graph exists so SAME_AS edges attach to persons that are really there.
        if not args.no_er:
            from ml_models.entity_resolution import resolve_entities
            matches = resolve_entities([p.person_id for p in ds.persons])
            linked = sum(1 for m in matches if m.decision == "link")
            print(f"entity resolution: {linked} links / {len(matches)} pairs scored "
                  f"({len(ds.true_duplicates)} duplicates injected)")

    if not args.no_embed:
        from ..embeddings.index_job import run_all
        print(f"indexed: {run_all()}")
    print(f"loaded: officers={len(ds.officers)} persons={len(ds.persons)} "
          f"firs={len(ds.firs)} records={len(ds.criminal_records)} "
          f"accounts={len(fin.accounts)} txns={len(fin.transactions)}")


if __name__ == "__main__":
    main()
