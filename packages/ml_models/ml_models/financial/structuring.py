"""Rule-based structuring detector.

Deliberately the *explainable* first line: a court can audit this line by line.
Structuring = breaking a large sum into many deposits that each sit just under the
reporting threshold, inside a short window. The rule states exactly that, and the
explanation quotes the numbers that triggered it.

Runs alongside the GNN (see gnn.py) — both detectors' flags are returned together,
because the GNN catches coordinated patterns this cannot see, and this catches the
ones a judge will actually accept as evidence.
"""
from sqlalchemy import text

from data.db import get_session

from ..types import TransactionFlag

REPORTING_THRESHOLD = 50_000       # ₹ — mirrors data/generator/financial.py
SUB_THRESHOLD_FLOOR = 0.5          # ignore genuinely small transfers
WINDOW_DAYS = 14
MIN_DEPOSITS = 5                   # a burst, not a coincidence

DETECTOR = "rule_based_structuring"


def detect_structuring(account_id: str) -> list[TransactionFlag]:
    """Incoming sub-threshold deposits clustered in a WINDOW_DAYS window.

    Reads the txn table directly. Under Neo4j this was a TRANSFERRED_TO traversal
    followed by a second query to recover the txn_id behind the edge — the row
    carries its own id, so that second lookup is simply gone.
    """
    with get_session() as s:
        rows = [dict(r) for r in s.execute(text(
            "SELECT txn_id, src_account_id AS src, amount, txn_date AS date "
            "FROM txn WHERE dst_account_id = :aid "
            "  AND amount < :threshold AND amount > :floor "
            "ORDER BY txn_date"
        ), {"aid": account_id, "threshold": REPORTING_THRESHOLD,
            "floor": REPORTING_THRESHOLD * SUB_THRESHOLD_FLOOR}).mappings().all()]
    if len(rows) < MIN_DEPOSITS:
        return []

    for r in rows:                       # DECIMAL -> float, so the arithmetic below works
        r["amount"] = float(r["amount"])
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
                txn_id=rows[j]["txn_id"],
                detector=DETECTOR,
                confidence=min(0.99, 0.5 + 0.05 * len(window)),
                explanation=explanation,
                related_account_ids=accounts + [account_id],
            ))
        break     # one flagged burst per account is enough to open the enquiry
    return flags
