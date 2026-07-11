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
from data.graph import get_driver

from ..types import TransactionFlag

REPORTING_THRESHOLD = 50_000       # ₹ — mirrors data/generator/financial.py
SUB_THRESHOLD_FLOOR = 0.5          # ignore genuinely small transfers
WINDOW_DAYS = 14
MIN_DEPOSITS = 5                   # a burst, not a coincidence

DETECTOR = "rule_based_structuring"


def detect_structuring(account_id: str) -> list[TransactionFlag]:
    """Incoming sub-threshold deposits clustered in a WINDOW_DAYS window."""
    with get_driver().session() as g:
        rows = g.run(
            "MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account {account_id: $aid}) "
            "WHERE t.amount < $threshold AND t.amount > $floor "
            "RETURN src.account_id AS src, t.amount AS amount, t.date AS date "
            "ORDER BY t.date",
            aid=account_id, threshold=REPORTING_THRESHOLD,
            floor=REPORTING_THRESHOLD * SUB_THRESHOLD_FLOOR,
        ).data()
    if len(rows) < MIN_DEPOSITS:
        return []

    dates = [r["date"].to_native() for r in rows]
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
                txn_id=_txn_id_for(account_id, rows[j]),
                detector=DETECTOR,
                confidence=min(0.99, 0.5 + 0.05 * len(window)),
                explanation=explanation,
                related_account_ids=accounts + [account_id],
            ))
        break     # one flagged burst per account is enough to open the enquiry
    return flags


def _txn_id_for(account_id: str, row: dict) -> str:
    """Resolve the Transaction node behind a TRANSFERRED_TO edge, so the flag points
    at a real txn_id (which is what data.flag_transaction writes against)."""
    with get_driver().session() as g:
        rec = g.run(
            "MATCH (src:Account {account_id: $src})-[:INVOLVED_IN]->(t:Transaction)"
            "<-[:INVOLVED_IN]-(dst:Account {account_id: $dst}) "
            "WHERE t.amount = $amount RETURN t.txn_id AS txn_id LIMIT 1",
            src=row["src"], dst=account_id, amount=row["amount"],
        ).single()
    return rec["txn_id"] if rec else ""
