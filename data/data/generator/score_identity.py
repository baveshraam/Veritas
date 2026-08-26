"""Recompute entity-resolution precision/recall/F1 against the persisted answer key.

    python -m data.generator.score_identity [--answer-key .veritas/identity_answer_key.json]

Out-of-band, like `fairness_run_audit.py` — not wired to any API route. Where
`fellegi_sunter.py`'s own `__main__` self-check can only score a `generate()` call it just
made in-process, this reads `vx_accused_identity` from whatever Data Store backend is
currently bound (sqlite locally, Catalyst inside an AppSail request) and scores it against
`run.py`'s persisted IDENTITY_ANSWER_KEY — so "F1 0.989" can be checked against whatever
dataset is actually live, not only a fresh local run.
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from .. import ds

DEFAULT_ANSWER_KEY = Path(os.getenv("VERITAS_IDENTITY_ANSWER_KEY",
                                     ".veritas/identity_answer_key.json"))


def _pair_count(sizes) -> int:
    return sum(n * (n - 1) // 2 for n in sizes)


def score(answer_key_path: Path = DEFAULT_ANSWER_KEY) -> tuple[float, float, float]:
    """-> (precision, recall, f1), pairwise over co-reference decisions — same metric
    fellegi_sunter.py's self-check uses, computed via cluster-size combinatorics instead
    of an O(n^2) pair enumeration so it stays fast at full dataset size."""
    truth = {int(k): int(v)
              for k, v in json.loads(answer_key_path.read_text(encoding="utf-8")).items()}
    got = {int(r["AccusedMasterID"]): int(r["PersonUID"])
           for r in ds.query('SELECT "AccusedMasterID", "PersonUID" FROM "vx_accused_identity"')}

    common = sorted(set(truth) & set(got))
    missing = set(truth) - set(got)
    if missing:
        print(f"warning: {len(missing)} answer-key row(s) have no vx_accused_identity row "
              f"(dataset regenerated since the key was written?) -- scoring the "
              f"{len(common)} that do")

    true_clusters: dict[int, list[int]] = defaultdict(list)
    got_clusters: dict[int, list[int]] = defaultdict(list)
    both: Counter[tuple[int, int]] = Counter()
    for aid in common:
        true_clusters[truth[aid]].append(aid)
        got_clusters[got[aid]].append(aid)
        both[(truth[aid], got[aid])] += 1

    tp = sum(c * (c - 1) // 2 for c in both.values())
    true_pairs = _pair_count(len(v) for v in true_clusters.values())
    got_pairs = _pair_count(len(v) for v in got_clusters.values())
    fp = got_pairs - tp
    fn = true_pairs - tp

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answer-key", type=Path, default=DEFAULT_ANSWER_KEY)
    args = ap.parse_args()
    precision, recall, f1 = score(args.answer_key)
    print(f"precision={precision:.3f} recall={recall:.3f} f1={f1:.3f}")


if __name__ == "__main__":
    main()
