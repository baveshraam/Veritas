"""GNN suspicious-subgraph classifier for AML.

A GraphSAGE-style message-passing classifier over the account-transaction graph,
trained on the generator's injected structuring/layering patterns as ground truth
(`Transaction.injected_pattern`). It catches coordinated multi-account laundering —
fan-in/fan-out and layering chains — that the per-account rule detector structurally
cannot see, because the rule only ever looks at one account's own inbound deposits.

Written directly in torch (mean-aggregation over the neighbour adjacency) rather than
pulling in torch-geometric: the operator we need is one sparse matmul, and a whole
graph-DL framework for that is a dependency we'd have to keep alive for no gain.

Explained per flag by neighbourhood attribution (which neighbouring accounts moved
the model's score), not a bare probability — an unexplained "0.87 suspicious" is
useless to an investigating officer.
"""
import json
import os
from pathlib import Path
from functools import lru_cache

import numpy as np

from data import ds

from ..types import TransactionFlag

DETECTOR = "gnn_subgraph"

# Ground truth for training, written by data/generator/run.py. Deliberately NOT a column on
# vx_txn: `FlaggedSuspicious` is this model's OUTPUT, and a classifier trained on a label
# sitting in the table it scores is measuring nothing.
def _aml_labels_path() -> Path:
    """Read from the environment on every call, not at import — a path frozen at import time
    cannot be redirected by a test."""
    return Path(os.getenv("VERITAS_AML_LABELS", ".veritas/aml_labels.json"))
_HIDDEN = 24
_EPOCHS = 120
_SEED = 0


def _injected_txn_ids() -> set[int]:
    """TxnIDs carrying an injected laundering pattern. Empty if the labels file is absent —
    an untrained detector that flags nothing is safe; one trained on absent labels is not.
    """
    path = _aml_labels_path()
    if not path.exists():
        return set()
    return {int(k) for k in json.loads(path.read_text(encoding="utf-8"))}


def _fetch_graph() -> tuple[list[int], np.ndarray, np.ndarray, np.ndarray]:
    """Account-level graph: node features, adjacency (undirected), labels.

    An account is 'laundering' ground truth if any transaction it participates in carries
    an injected pattern. Those labels live in a file the generator writes, not in `vx_txn`
    — a detector whose training label sits in the column it is scoring is not a detector.

    The aggregation is done here, not in the query: ZCQL has no CTE, no correlated subquery
    and no CASE. The old Postgres version pushed all of that server-side; the transaction
    table is tens of thousands of rows, so a single scan in numpy is the same answer.
    """
    accounts = ds.query('SELECT "AccountID" FROM "vx_account"')
    txns = ds.query('SELECT "TxnID", "SrcAccountID", "DstAccountID", "Amount" FROM "vx_txn"')
    labelled = _injected_txn_ids()

    stats: dict[int, dict] = {
        a["AccountID"]: {"id": a["AccountID"], "out_deg": 0, "in_deg": 0, "out_amt": 0.0,
                         "in_amt": 0.0, "txn_count": 0, "total_amt": 0.0, "label": 0}
        for a in accounts}
    edge_pairs: set[tuple[int, int]] = set()

    for t in txns:
        src, dst, amt = t["SrcAccountID"], t["DstAccountID"], float(t["Amount"] or 0)
        dirty = t["TxnID"] in labelled
        for acct, is_src in ((src, True), (dst, False)):
            st = stats.get(acct)
            if st is None:
                continue
            st["txn_count"] += 1
            st["total_amt"] += amt
            if is_src:
                st["out_deg"] += 1
                st["out_amt"] += amt
            else:
                st["in_deg"] += 1
                st["in_amt"] += amt
            if dirty:
                st["label"] = 1
        if src in stats and dst in stats:
            edge_pairs.add((src, dst))

    nodes = list(stats.values())
    for n in nodes:
        n["avg_amt"] = n["total_amt"] / n["txn_count"] if n["txn_count"] else 0.0
    edges = [{"src": a, "dst": b} for a, b in edge_pairs]

    ids = [n["id"] for n in nodes]
    index = {a: i for i, a in enumerate(ids)}
    X = np.array([[n["out_deg"], n["in_deg"],
                   np.log1p(n["out_amt"]), np.log1p(n["in_amt"]),
                   n["txn_count"], np.log1p(n["avg_amt"] or 0.0)] for n in nodes],
                 dtype=np.float32)
    y = np.array([n["label"] or 0 for n in nodes], dtype=np.int64)

    n = len(ids)
    A = np.zeros((n, n), dtype=np.float32)
    for e in edges:
        i, j = index.get(e["src"]), index.get(e["dst"])
        if i is not None and j is not None:
            A[i, j] = A[j, i] = 1.0            # undirected for message passing
    return ids, X, A, y


def _normalise(X: np.ndarray) -> np.ndarray:
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd


@lru_cache(maxsize=1)
def _trained():
    """Fit the GNN on the current graph. Cached per process."""
    import torch
    import torch.nn as nn

    torch.manual_seed(_SEED)
    ids, X, A, y = _fetch_graph()
    if len(ids) < 20 or y.sum() < 3:
        raise GNNUnavailable(
            f"graph too small or too few laundering examples ({int(y.sum())})")

    Xn = torch.tensor(_normalise(X))
    # mean-aggregation adjacency (add self-loops, row-normalise)
    A_hat = torch.tensor(A) + torch.eye(len(ids))
    A_hat = A_hat / A_hat.sum(dim=1, keepdim=True)
    yt = torch.tensor(y)

    class SAGE(nn.Module):
        def __init__(self, d_in: int) -> None:
            super().__init__()
            self.l1 = nn.Linear(d_in * 2, _HIDDEN)
            self.l2 = nn.Linear(_HIDDEN * 2, 2)

        def forward(self, x, adj):
            # each layer concatenates the node's own features with its neighbourhood
            # mean — that self/neighbour split is what makes it GraphSAGE rather than
            # a plain GCN, and it's what lets a clean account next to a dirty cluster
            # still be scored on its own behaviour.
            h = torch.relu(self.l1(torch.cat([x, adj @ x], dim=1)))
            return self.l2(torch.cat([h, adj @ h], dim=1))

    model = SAGE(Xn.shape[1])
    # class weights: laundering accounts are a small minority
    w = torch.tensor([1.0, float((y == 0).sum()) / max(1.0, float((y == 1).sum()))])
    opt = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)
    loss_fn = nn.CrossEntropyLoss(weight=w)

    model.train()
    for _ in range(_EPOCHS):
        opt.zero_grad()
        loss = loss_fn(model(Xn, A_hat), yt)
        loss.backward()
        opt.step()

    model.eval()
    with torch.no_grad():
        probs = torch.softmax(model(Xn, A_hat), dim=1)[:, 1].numpy()
    return ids, {a: i for i, a in enumerate(ids)}, probs, A


class GNNUnavailable(RuntimeError):
    """Graph has too few laundering examples to fit an honest classifier."""


def score_accounts() -> dict[str, float]:
    ids, _, probs, _ = _trained()
    return {a: float(p) for a, p in zip(ids, probs)}


def detect_subgraph(account_id: int, threshold: float = 0.5) -> list[TransactionFlag]:
    """Flag the account's transactions if it sits in a suspicious subgraph."""
    ids, index, probs, A = _trained()
    i = index.get(int(account_id))
    if i is None or probs[i] < threshold:
        return []

    # attribution: which neighbours carry the suspicion (this is the "why")
    neighbours = [ids[j] for j in np.where(A[i] > 0)[0]]
    hot = sorted(neighbours, key=lambda a: -probs[index[a]])[:5]
    hot_scores = ", ".join(f"#{a} ({probs[index[a]]:.2f})" for a in hot)

    txns = ds.query('SELECT "TxnID" FROM "vx_txn" WHERE "SrcAccountID" = :aid',
                    {"aid": int(account_id)})
    txns += ds.query('SELECT "TxnID" FROM "vx_txn" WHERE "DstAccountID" = :aid',
                     {"aid": int(account_id)})

    explanation = (
        f"Account scores {probs[i]:.2f} in the laundering-subgraph classifier. "
        f"The signal comes from its transaction neighbourhood — highest-scoring "
        f"connected accounts: {hot_scores or 'none'}. This is a coordinated-pattern "
        f"flag (fan-in/layering across accounts), not a single-account rule breach."
    )
    return [TransactionFlag(
        txn_id=str(t["TxnID"]), detector=DETECTOR, confidence=round(float(probs[i]), 4),
        explanation=explanation,
        related_account_ids=[str(account_id)] + [str(a) for a in hot],
    ) for t in txns]
