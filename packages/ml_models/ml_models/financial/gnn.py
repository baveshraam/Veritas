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
from functools import lru_cache

import numpy as np

from data.graph import get_driver

from ..types import TransactionFlag

DETECTOR = "gnn_subgraph"
_HIDDEN = 24
_EPOCHS = 120
_SEED = 0


def _fetch_graph() -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Account-level graph: node features, adjacency (undirected), labels.

    An account is 'laundering' ground truth if any transaction it participates in
    carries an injected_pattern.
    """
    with get_driver().session() as g:
        nodes = g.run(
            "MATCH (a:Account) "
            "OPTIONAL MATCH (a)-[out:TRANSFERRED_TO]->() "
            "OPTIONAL MATCH (a)<-[inc:TRANSFERRED_TO]-() "
            "WITH a, count(DISTINCT out) AS out_deg, count(DISTINCT inc) AS in_deg, "
            "     coalesce(sum(DISTINCT out.amount), 0.0) AS out_amt, "
            "     coalesce(sum(DISTINCT inc.amount), 0.0) AS in_amt "
            "OPTIONAL MATCH (a)-[:INVOLVED_IN]->(t:Transaction) "
            "RETURN a.account_id AS id, out_deg, in_deg, out_amt, in_amt, "
            "  count(t) AS txn_count, "
            "  avg(coalesce(t.amount, 0.0)) AS avg_amt, "
            "  max(CASE WHEN t.injected_pattern IS NOT NULL THEN 1 ELSE 0 END) AS label"
        ).data()
        edges = g.run(
            "MATCH (a:Account)-[:TRANSFERRED_TO]->(b:Account) "
            "RETURN DISTINCT a.account_id AS src, b.account_id AS dst"
        ).data()

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


def detect_subgraph(account_id: str, threshold: float = 0.5) -> list[TransactionFlag]:
    """Flag the account's transactions if it sits in a suspicious subgraph."""
    ids, index, probs, A = _trained()
    i = index.get(account_id)
    if i is None or probs[i] < threshold:
        return []

    # attribution: which neighbours carry the suspicion (this is the "why")
    neighbours = [ids[j] for j in np.where(A[i] > 0)[0]]
    hot = sorted(neighbours, key=lambda a: -probs[index[a]])[:5]
    hot_scores = ", ".join(f"{a[:8]}… ({probs[index[a]]:.2f})" for a in hot)

    with get_driver().session() as g:
        txns = g.run(
            "MATCH (a:Account {account_id: $aid})-[:INVOLVED_IN]->(t:Transaction) "
            "RETURN t.txn_id AS txn_id", aid=account_id).data()

    explanation = (
        f"Account scores {probs[i]:.2f} in the laundering-subgraph classifier. "
        f"The signal comes from its transaction neighbourhood — highest-scoring "
        f"connected accounts: {hot_scores or 'none'}. This is a coordinated-pattern "
        f"flag (fan-in/layering across accounts), not a single-account rule breach."
    )
    return [TransactionFlag(
        txn_id=t["txn_id"], detector=DETECTOR, confidence=round(float(probs[i]), 4),
        explanation=explanation,
        related_account_ids=[account_id] + hot,
    ) for t in txns]
