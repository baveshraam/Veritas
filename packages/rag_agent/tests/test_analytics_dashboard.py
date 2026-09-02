"""The Statistics dashboard's single scan (`sql_agent.dashboard`).

The console's analytical tabs used to fill themselves by firing a canned English
question at the LangGraph orchestrator and reading the answer's evidence items back
out. `dashboard()` is what replaced that for Statistics: one pass over the SAME
policy-scoped rows `count_firs`/`status_breakdown`/`counts_by` read, counted five
different ways.

The thing that can silently go wrong here is the thing that goes wrong every time a
count and the list it captions come from different queries (`_filters`' own docstring
says so): a total that does not equal the sum of any one breakdown means at least one
of them is describing a different set of rows than the officer is being shown. That is
the property these tests pin, alongside the RBAC scope, because a dashboard whose
figures disagree with each other is worse than one that is missing.
"""
from rag_agent.agents.sql_agent import (
    count_firs, counts_by, dashboard, status_breakdown,
)


def test_every_breakdown_sums_to_the_same_total(dataset):
    """Five groupings of one row set. Each partitions it, so each must sum to it."""
    d = dashboard("DSP", "101")
    assert d["total"] > 0, "fixture must have cases"
    for grouping in ("status", "crime_type", "district", "station", "monthly"):
        got = sum(row["cases"] for row in d[grouping])
        # `monthly` is the one that can legitimately fall short: a case with no
        # recorded registration date has no month to fall into, and inventing one
        # would be worse than omitting it.
        if grouping == "monthly":
            assert got <= d["total"]
        else:
            assert got == d["total"], (
                f"{grouping} sums to {got} but the dashboard reports {d['total']} — "
                f"the breakdown and the headline are counting different rows")


def test_the_total_matches_the_query_every_other_caller_uses(dataset):
    """`count_firs` is what the conversational path answers "how many" with. If the
    dashboard's headline disagrees with it, the tab and the chat are describing two
    different case sets on the same screen."""
    d = dashboard("DSP", "101")
    assert d["total"] == count_firs("DSP", "101")


def test_breakdowns_match_the_single_grouping_functions(dataset):
    """Same numbers as `status_breakdown` / `counts_by`, which is the point: this is a
    cheaper way to ask the questions those already answer, not a second source of
    truth that can drift away from them."""
    d = dashboard("DSP", "101")
    assert {r["name"]: r["cases"] for r in d["status"]} == status_breakdown("DSP", "101")
    assert [(r["name"], r["cases"]) for r in d["district"]] \
        == counts_by("DSP", "101", "district")


def test_conviction_rate_excludes_cases_with_no_outcome(dataset):
    """A case still under investigation has not been acquitted; counting it in the
    denominator would report a conviction rate that falls as a station opens cases.
    The denominator is verdicts, and it is returned so the console can print it."""
    d = dashboard("DSP", "101")
    status = {r["name"]: r["cases"] for r in d["status"]}
    c = d["conviction"]
    assert c["decided"] == status.get("Convicted", 0) + status.get("Acquitted", 0)
    assert c["decided"] <= d["total"]
    if c["decided"]:
        assert c["rate"] == c["convicted"] / c["decided"]
    else:
        assert c["rate"] is None, "no verdicts is an absence of outcomes, not a rate of 0"


def test_an_io_sees_only_their_own_station(dataset):
    """The same `_ps_scope` clause every other query in this module applies, inside the
    query rather than after it. A dashboard is exactly the shape that would leak the
    whole state's figures to a station officer if this were enforced post-hoc."""
    io = dashboard("IO", "101")
    assert io["total"] <= dashboard("DSP", "101")["total"]
    assert len(io["station"]) <= 1, "an IO's dashboard must not name another station"


def test_the_monthly_series_is_chronological_not_ranked(dataset):
    """Every other grouping is sorted by volume; this one must not be. A trend line
    drawn through a shuffled x-axis is a chart that shows a pattern nobody recorded."""
    months = [r["name"] for r in dashboard("DSP", "101")["monthly"]]
    assert months == sorted(months)
