"""Rule-based structuring detector.

Deliberately the *explainable* first line: a court can audit this line by line.
Structuring = breaking a large sum into many deposits that each sit just under the
reporting threshold, inside a short window. The rule states exactly that, and the
explanation quotes the numbers that triggered it.

Runs alongside the GNN (see gnn.py) — both detectors' flags are returned together,
because the GNN catches coordinated patterns this cannot see, and this catches the
ones a judge will actually accept as evidence.
"""
from data import ds

from ..types import TransactionFlag

REPORTING_THRESHOLD = 50_000       # ₹ — mirrors data/generator/financial.py
SUB_THRESHOLD_FLOOR = 0.5          # ignore genuinely small transfers
WINDOW_DAYS = 14
MIN_DEPOSITS = 5                   # a burst, not a coincidence

DETECTOR = "rule_based_structuring"


def detect_structuring(account_id: int) -> list[TransactionFlag]:
    """Incoming sub-threshold deposits clustered in a WINDOW_DAYS window.

    Reads vx_txn directly. Under Neo4j this was a TRANSFERRED_TO traversal followed by a
    second query to recover the txn_id behind the edge — the row carries its own id, so
    that second lookup is simply gone.
    """
    rows = ds.query(
        'SELECT "TxnID", "SrcAccountID", "Amount", "TxnDate" FROM "vx_txn" '
        'WHERE "DstAccountID" = :aid AND "Amount" < :threshold AND "Amount" > :floor '
        'ORDER BY "TxnDate"',
        {"aid": int(account_id), "threshold": REPORTING_THRESHOLD,
         "floor": REPORTING_THRESHOLD * SUB_THRESHOLD_FLOOR},
    )
    if len(rows) < MIN_DEPOSITS:
        return []

    rows = [{"txn_id": r["TxnID"], "src": r["SrcAccountID"],
             "amount": float(r["Amount"]), "date": ds.to_dt(r["TxnDate"])} for r in rows]
    dates = [r["date"] for r in rows]
    flags: list[TransactionFlag] = []

    # sliding window over the ordered deposits
    for i in range(len(rows)):
        window = [j for j in range(i, len(rows))
                  if (dates[j] - dates[i]).days <= WINDOW_DAYS]
        if len(window) < MIN_DEPOSITS:
            continue
        total = sum(rows[j]["amount"] for j in window)
        accounts = sorted({rows[j]["src"] for j in window})
        span = (dates[window[-1]] - dates[window[0]]).days
        explanation = (
            f"{len(window)} deposits totalling ₹{total:,.0f} arrived in {span} day(s) "
            f"from {len(accounts)} account(s), each below the ₹{REPORTING_THRESHOLD:,} "
            f"reporting threshold (largest ₹{max(rows[j]['amount'] for j in window):,.0f}). "
            f"Consistent with structuring to avoid a reportable transaction."
        )
        for j in window:
            flags.append(TransactionFlag(
                txn_id=str(rows[j]["txn_id"]),
                detector=DETECTOR,
                confidence=min(0.99, 0.5 + 0.05 * len(window)),
                explanation=explanation,
                related_account_ids=[str(a) for a in accounts] + [str(account_id)],
            ))
        break     # one flagged burst per account is enough to open the enquiry
    return flags
