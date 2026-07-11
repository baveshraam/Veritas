"""Financial-crime layer: accounts, transactions, and injected laundering patterns.

Generates a transaction graph with *labeled* ground truth so the AML models have
something real to learn/validate against:
  - normal transfers (the background),
  - structuring: many sub-threshold deposits into one account in a short window,
  - layering: dirty money fanned through a chain of intermediary accounts
    (creates the TRANSFERRED_TO*1..4 trails the money-flow traversal walks).

`injected_pattern` is the training label (structuring/layering/None). It is
distinct from `flagged_suspicious`, which is a *detector output* set later by
packages/ml_models via data.flag_transaction — the generator never pre-flags.
"""
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .build import Dataset, Person, _uid

REPORTING_THRESHOLD = 50000          # ₹ — sub-threshold structuring sits just below this
BANKS = ("SBI", "Canara", "KVG Bank", "Union Bank", "HDFC", "Axis")
CHANNELS = ("NEFT", "IMPS", "UPI", "CASH", "RTGS")


@dataclass
class Account:
    account_id: str
    bank: str
    account_type: str
    opened_date: date
    owner_person_id: str


@dataclass
class Transaction:
    txn_id: str
    amount: float
    date: datetime
    channel: str
    src_account_id: str
    dst_account_id: str
    injected_pattern: str | None       # ground-truth label; None = normal
    linked_fir_id: str | None


@dataclass
class FinancialData:
    accounts: list[Account] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)


def _txn(rng, src, dst, amount, when, pattern=None, fir_id=None) -> Transaction:
    return Transaction(_uid(rng), round(amount, 2), when,
                       rng.choice(CHANNELS), src.account_id, dst.account_id,
                       pattern, fir_id)


def make_financial(rng: random.Random, ds: Dataset) -> FinancialData:
    """Accounts for a subset of persons (gang members over-represented), a normal
    transfer background, plus injected structuring and layering rings."""
    holders = _account_holders(rng, ds.persons)
    accounts = [Account(_uid(rng), rng.choice(BANKS),
                        rng.choice(("Savings", "Current")),
                        _rand_open_date(rng), p.person_id) for p in holders]
    fin = FinancialData(accounts=accounts)
    if len(accounts) < 4:
        return fin

    fir_ids = [f.fir_id for f in ds.firs]

    # background: everyday transfers between random accounts
    for _ in range(len(accounts) * 3):
        src, dst = _two(rng, accounts)
        fin.transactions.append(_txn(
            rng, src, dst, rng.uniform(500, 80000), _rand_txn_dt(rng),
            fir_id=rng.choice(fir_ids) if rng.random() < 0.05 else None))

    _inject_structuring(rng, accounts, fin, fir_ids)
    _inject_layering(rng, accounts, fin, fir_ids)
    return fin


def _account_holders(rng: random.Random, persons: list[Person]) -> list[Person]:
    holders = []
    for p in persons:
        prob = 0.6 if p.gang_affiliation else (0.25 if p.criminal_history else 0.12)
        if rng.random() < prob:
            holders.append(p)
    return holders


def _inject_structuring(rng, accounts, fin: FinancialData, fir_ids) -> None:
    """~1 structuring ring per 40 accounts: 8-15 sub-threshold deposits into one
    account inside a 10-day window."""
    for _ in range(max(1, len(accounts) // 40)):
        target = rng.choice(accounts)
        sources = [a for a in accounts if a.account_id != target.account_id]
        start = _rand_txn_dt(rng)
        for _ in range(rng.randint(8, 15)):
            src = rng.choice(sources)
            when = start + timedelta(days=rng.randint(0, 10), hours=rng.randint(0, 23))
            amount = rng.uniform(REPORTING_THRESHOLD * 0.8, REPORTING_THRESHOLD - 1)
            fin.transactions.append(_txn(rng, src, target, amount, when,
                                         pattern="structuring",
                                         fir_id=rng.choice(fir_ids) if rng.random() < 0.3 else None))


def _inject_layering(rng, accounts, fin: FinancialData, fir_ids) -> None:
    """~1 layering chain per 50 accounts: a large sum hops through 3-4 intermediaries,
    each hop shedding a little — the TRANSFERRED_TO*1..4 trail the demo traverses."""
    for _ in range(max(1, len(accounts) // 50)):
        chain = rng.sample(accounts, min(5, len(accounts)))
        amount = rng.uniform(300000, 1500000)
        when = _rand_txn_dt(rng)
        fir = rng.choice(fir_ids) if fir_ids else None
        for src, dst in zip(chain, chain[1:]):
            when = when + timedelta(hours=rng.randint(1, 48))
            amount *= rng.uniform(0.85, 0.97)
            fin.transactions.append(_txn(rng, src, dst, amount, when,
                                         pattern="layering", fir_id=fir))


def _two(rng, accounts):
    a, b = rng.sample(accounts, 2)
    return a, b


def _rand_open_date(rng) -> date:
    return date(2015, 1, 1) + timedelta(days=rng.randint(0, 3600))


def _rand_txn_dt(rng) -> datetime:
    base = datetime(2026, 7, 1) - timedelta(days=rng.randint(1, 1095))
    return base + timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0, 59))


if __name__ == "__main__":
    from .build import generate
    rng = random.Random(5)
    ds = generate(rng, 400)
    fin = make_financial(rng, ds)
    patterns = {}
    for t in fin.transactions:
        patterns[t.injected_pattern] = patterns.get(t.injected_pattern, 0) + 1
    print(f"accounts={len(fin.accounts)} txns={len(fin.transactions)} patterns={patterns}")
