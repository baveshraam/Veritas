"""Financial-crime layer: accounts, transactions, and injected laundering patterns.

Generates a transaction graph with *labeled* ground truth so the AML models have
something real to learn/validate against:
  - normal transfers (the background),
  - structuring: many sub-threshold deposits into one account in a short window,
  - layering: dirty money fanned through a chain of intermediary accounts
    (creates the acct->acct*1..4 trails the money-flow traversal walks).

Runs *after* entity resolution, on `vx_person` — an account belongs to a human, and the
ER has no human, only per-case Accused rows. Opening one account per Accused row would
scatter a single launderer's money across a dozen identities and make the whole layer
meaningless.

`FlaggedSuspicious` is a *detector output*, set later by packages/ml_models — the
generator never pre-flags, or the AML models would be scoring their own answer key. The
injected pattern is returned separately, as labels, and never written to the record layer.
"""
import random
from datetime import date, datetime, timedelta

REPORTING_THRESHOLD = 50000          # ₹ — sub-threshold structuring sits just below this
BANKS = ("SBI", "Canara", "KVG Bank", "Union Bank", "HDFC", "Axis")
CHANNELS = ("NEFT", "IMPS", "UPI", "CASH", "RTGS")


def make_financial(
    rng: random.Random,
    people: list[dict],
    case_ids: list[int],
) -> tuple[list[dict], list[dict], dict[int, str]]:
    """-> (vx_account rows, vx_txn rows, {TxnID: injected_pattern}).

    `people` are vx_person rows; `case_ids` are CaseMasterIDs a txn may be linked to.
    The third return value is the AML ground truth. It is the caller's job to keep it out
    of the database.
    """
    holders = [p for p in people
               if rng.random() < (0.30 if p.get("IsHabitualOffender") else 0.10)]
    accounts = [{
        "AccountID": i,
        "PersonUID": p["PersonUID"],
        "Bank": rng.choice(BANKS),
        "AccountType": rng.choice(("Savings", "Current")),
        "OpenedDate": _rand_open_date(rng),
    } for i, p in enumerate(holders, start=1)]

    if len(accounts) < 4:
        return accounts, [], {}

    txns: list[dict] = []
    labels: dict[int, str] = {}
    nxt = iter(range(1, 10_000_000))

    def add(src: dict, dst: dict, amount: float, when: datetime,
            pattern: str | None = None, case: int | None = None) -> None:
        tid = next(nxt)
        txns.append({
            "TxnID": tid,
            "SrcAccountID": src["AccountID"], "DstAccountID": dst["AccountID"],
            "Amount": round(amount, 2), "TxnDate": when,
            "Channel": rng.choice(CHANNELS),
            "FlaggedSuspicious": False,          # detector output. Never the generator's.
            "CaseMasterID": case,
        })
        if pattern:
            labels[tid] = pattern

    # Background: everyday transfers between random accounts.
    for _ in range(len(accounts) * 3):
        src, dst = rng.sample(accounts, 2)
        add(src, dst, rng.uniform(500, 80000), _rand_txn_dt(rng),
            case=rng.choice(case_ids) if case_ids and rng.random() < 0.05 else None)

    _inject_structuring(rng, accounts, case_ids, add)
    _inject_layering(rng, accounts, case_ids, add)
    return accounts, txns, labels


def _inject_structuring(rng, accounts, case_ids, add) -> None:
    """~1 structuring ring per 40 accounts: 8-15 sub-threshold deposits into one account
    inside a 10-day window. The pattern the rule-based detector is built to catch."""
    for _ in range(max(1, len(accounts) // 40)):
        target = rng.choice(accounts)
        sources = [a for a in accounts if a["AccountID"] != target["AccountID"]]
        start = _rand_txn_dt(rng)
        for _ in range(rng.randint(8, 15)):
            when = start + timedelta(days=rng.randint(0, 10), hours=rng.randint(0, 23))
            add(rng.choice(sources), target,
                rng.uniform(REPORTING_THRESHOLD * 0.8, REPORTING_THRESHOLD - 1), when,
                pattern="structuring",
                case=rng.choice(case_ids) if case_ids and rng.random() < 0.3 else None)


def _inject_layering(rng, accounts, case_ids, add) -> None:
    """~1 layering chain per 50 accounts: a large sum hops through 3-4 intermediaries,
    each hop shedding a little — the multi-hop money trail the demo traverses. The
    rule-based detector structurally cannot see this; the GNN is what it is for."""
    for _ in range(max(1, len(accounts) // 50)):
        chain = rng.sample(accounts, min(5, len(accounts)))
        amount = rng.uniform(300000, 1500000)
        when = _rand_txn_dt(rng)
        case = rng.choice(case_ids) if case_ids else None
        for src, dst in zip(chain, chain[1:]):
            when += timedelta(hours=rng.randint(1, 48))
            amount *= rng.uniform(0.85, 0.97)
            add(src, dst, amount, when, pattern="layering", case=case)


def _rand_open_date(rng) -> date:
    return date(2015, 1, 1) + timedelta(days=rng.randint(0, 3600))


def _rand_txn_dt(rng) -> datetime:
    base = datetime(2026, 7, 1) - timedelta(days=rng.randint(1, 1095))
    return base + timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0, 59))


if __name__ == "__main__":
    rng = random.Random(5)
    fake = [{"PersonUID": i, "IsHabitualOffender": i % 3 == 0} for i in range(1, 600)]
    accounts, txns, labels = make_financial(rng, fake, list(range(1, 400)))
    counts: dict[str, int] = {}
    for p in labels.values():
        counts[p] = counts.get(p, 0) + 1
    assert accounts and txns, "financial layer produced nothing"
    assert not any(t["FlaggedSuspicious"] for t in txns), "generator must never pre-flag"
    assert set(labels) <= {t["TxnID"] for t in txns}, "label points at no such txn"
    print(f"accounts={len(accounts)} txns={len(txns)} injected={counts}")
