"""`/jobs/refresh` rebuilds several INDEPENDENT derived layers. One failing must not
cancel the rest.

This is a real live failure, not a hypothetical. The four steps were in one try/except,
so the first raise silently skipped everything after it — and `publish_graph()` writes
to Stratus, whose bucket creation is scope-blocked on this org (CLAUDE.md §2,
OAUTH_SCOPE_MISMATCH, console-only). A blocked CACHE publish was therefore able to
cancel the AML detector sweep, which is a RECORD-layer rebuild. The Financial Watchlist
stayed empty through a refresh that reported itself both started and complete, and an
empty watchlist is indistinguishable from a genuine all-clear.

The lock release is tested for the same reason: a step that raises on the way out of a
`finally` that never runs leaves `_refresh_running` stuck True, and every later trigger
answers "already_running" forever with nothing actually running.
"""
import os

import pytest

os.environ.setdefault("VERITAS_JOB_TOKEN", "test-job-token")

from api.routers import jobs


@pytest.fixture
def steps(monkeypatch):
    """Replace the four real rebuilds with recorders, one of which explodes."""
    called: list[str] = []

    def ok(name):
        def _run():
            called.append(name)
            return f"{name}-done"
        return _run

    def boom():
        called.append("stratus_graph")
        raise RuntimeError("OAUTH_SCOPE_MISMATCH")

    monkeypatch.setattr("data.gds.run_all", ok("gds"), raising=False)
    monkeypatch.setattr("data.graph.publish_graph", boom, raising=False)
    monkeypatch.setattr("data.embeddings.index_job.run_all", ok("vector_index"),
                        raising=False)
    monkeypatch.setattr(jobs, "_rerun_detectors", ok("aml"))
    monkeypatch.setattr(jobs, "_scan_series", ok("series_scan"))
    monkeypatch.setattr(jobs, "_run_fairness", ok("fairness"))
    monkeypatch.setattr(jobs, "_run_advisory", ok("advisory"))
    return called


def test_a_blocked_stratus_publish_does_not_cancel_the_aml_sweep(steps, caplog):
    """The exact live failure: the cache publish is the SECOND step, and the detector
    sweep is the fourth. Under one try/except, steps 3 and 4 never ran."""
    jobs._refresh_running = True
    jobs._run_refresh()

    assert steps == ["gds", "stratus_graph", "vector_index", "aml", "series_scan",
                     "fairness", "advisory"], (
        "every step must be attempted — a failing cache publish cancelled the two "
        "record-layer rebuilds after it")


def test_a_failed_step_is_named_rather_than_swallowed(steps, caplog):
    """A refresh that reports itself complete while a step silently died is the failure
    mode that hid this for a whole deployment. The log has to say which one."""
    import logging

    jobs._refresh_running = True
    with caplog.at_level(logging.INFO):
        jobs._run_refresh()

    text = caplog.text
    assert "stratus_graph" in text, "the failing step must name itself in the log"
    assert "RuntimeError" in text or "OAUTH_SCOPE_MISMATCH" in text


def test_the_lock_is_released_even_when_a_step_raises(steps):
    """Otherwise every later trigger answers 'already_running' forever, with nothing
    actually running — which is indistinguishable from a refresh that is merely slow."""
    jobs._refresh_running = True
    jobs._run_refresh()
    assert jobs._refresh_running is False


def test_the_detector_sweep_clears_stale_flags_before_it_rewrites(monkeypatch):
    """A flag is derived, and a stale one points an investigator at a transaction the
    CURRENT model does not consider suspicious. `clear_flags()` must run first, not as
    a tidy-up afterwards."""
    order: list[str] = []

    monkeypatch.setattr("data.transactions.clear_flags",
                        lambda: order.append("clear"), raising=False)
    monkeypatch.setattr("data.ds.query",
                        lambda *a, **k: [{"AccountID": 1}, {"AccountID": 2}],
                        raising=False)
    monkeypatch.setattr("ml_models.serving.flag_transactions",
                        lambda a: (order.append(f"flag:{a}"), [object()])[1],
                        raising=False)

    out = jobs._rerun_detectors()
    assert order[0] == "clear", "stale flags must be cleared before the sweep, not after"
    assert out == {"accounts": 2, "flagged": 2, "failed": 0}


def test_one_bad_account_does_not_cost_the_whole_sweep(monkeypatch):
    """698 accounts, and one unparseable row must not leave the other 697 unscored —
    a silent partial run is worse than a reported one, so failures are counted."""
    monkeypatch.setattr("data.transactions.clear_flags", lambda: None, raising=False)
    monkeypatch.setattr("data.ds.query",
                        lambda *a, **k: [{"AccountID": i} for i in range(5)],
                        raising=False)

    def flaky(acct):
        if acct == "2":
            raise ValueError("bad row")
        return [object()]

    monkeypatch.setattr("ml_models.serving.flag_transactions", flaky, raising=False)

    out = jobs._rerun_detectors()
    assert out == {"accounts": 5, "flagged": 4, "failed": 1}


def test_fairness_step_caches_a_flagged_report_for_health_to_read(monkeypatch):
    """STRATEGIC_RESET Part 9, Item 1: the audit existed as a script nobody scheduled.
    `/health` must be able to tell a flagged model apart from a clean one without
    re-running the audit, so this is what /jobs/refresh now caches for it to read."""
    from data import cache

    class _Report:
        def __init__(self, flagged):
            self._flagged = flagged

        def model_dump(self, mode="json"):
            return {"disparate_impact_flagged": self._flagged}

    def fake_audit(model_name):
        return _Report(flagged=(model_name == "predict_recidivism"))

    monkeypatch.setattr("ml_models.serving.run_fairness_audit", fake_audit)
    cache.evict(jobs.FAIRNESS_CACHE_KEY)

    out = jobs._run_fairness()
    assert out == {"flagged": True}, "either model flagging must flag the whole audit"

    cached = cache.get(jobs.FAIRNESS_CACHE_KEY)
    assert cached["flagged"] is True
    assert cached["reports"]["score_risk"]["disparate_impact_flagged"] is False
    assert cached["reports"]["predict_recidivism"]["disparate_impact_flagged"] is True


def test_advisory_step_reads_the_series_and_fairness_caches_it_runs_after(monkeypatch):
    """STRATEGIC_RESET Part 9, Item 2: the advisory is only useful if it can attach
    what the two steps before it just computed — prove it actually reads them rather
    than silently defaulting to 'no series, not flagged' every cycle."""
    from data import cache

    class _District:
        code = "KA05"

    monkeypatch.setattr("data.districts.all_districts", lambda: [_District()])
    cache.put(jobs.SERIES_CACHE_KEY, [{"districts": ["Kolar"]}])
    cache.put(jobs.FAIRNESS_CACHE_KEY, {"flagged": True})

    captured = {}

    def fake_advisory_for(code, series_candidates=None, fairness_flagged=False):
        captured["code"] = code
        captured["series_candidates"] = series_candidates
        captured["fairness_flagged"] = fairness_flagged
        return {"district_code": code, "headline": "test"}

    monkeypatch.setattr("rag_agent.agents.prediction_agent.advisory_for", fake_advisory_for)

    out = jobs._run_advisory()
    assert out == {"advisories": 1}
    assert captured == {"code": "KA05", "series_candidates": [{"districts": ["Kolar"]}],
                        "fairness_flagged": True}
    assert cache.get(jobs.ADVISORY_CACHE_KEY) == [{"district_code": "KA05", "headline": "test"}]


def test_last_outcome_is_cached_for_health_to_read_when_sync_cant_be_trusted(steps):
    """AppSail exposes no runtime logs, and sync=true can now outrun AppSail's own
    request execution ceiling with fairness+advisory added to the step list — the
    cached outcome is the only way left to see which step actually failed."""
    from data import cache

    jobs._refresh_running = True
    jobs._run_refresh()

    cached = cache.get(jobs.LAST_REFRESH_CACHE_KEY)
    assert cached["gds"] == "gds-done"
    assert "at" in cached


def test_progress_is_visible_before_the_job_finishes(monkeypatch):
    """Live verification (2026-09-05): the async job ran for minutes with `/health`'s
    `last_refresh` staying null the whole time, and AppSail exposes no runtime logs to
    tell "still working" apart from "stuck" or "the container recycled mid-run". Each
    step must publish its own start, not just the job's own final outcome."""
    from data import cache

    seen_during_gds = {}

    def slow_gds():
        seen_during_gds.update(cache.get(jobs.LAST_REFRESH_CACHE_KEY) or {})
        return "gds-done"

    monkeypatch.setattr("data.gds.run_all", slow_gds, raising=False)
    monkeypatch.setattr("data.graph.publish_graph", lambda: "stratus_graph-done",
                        raising=False)
    monkeypatch.setattr("data.embeddings.index_job.run_all",
                        lambda: "vector_index-done", raising=False)
    monkeypatch.setattr(jobs, "_rerun_detectors", lambda: "aml-done")
    monkeypatch.setattr(jobs, "_scan_series", lambda: "series_scan-done")
    monkeypatch.setattr(jobs, "_run_fairness", lambda: "fairness-done")
    monkeypatch.setattr(jobs, "_run_advisory", lambda: "advisory-done")

    jobs._refresh_running = True
    jobs._run_refresh()

    assert seen_during_gds["status"] == "running"
    assert seen_during_gds["current_step"] == "gds"
    assert "step_started_at" in seen_during_gds

    final = cache.get(jobs.LAST_REFRESH_CACHE_KEY)
    assert final["status"] == "complete"
    assert final["gds"] == "gds-done"


def test_a_failed_step_s_message_is_cached_not_just_its_type(steps):
    """A bare exception TYPE name is not enough to diagnose a live-only failure with
    no server logs to fall back on — the message has to travel too."""
    from data import cache

    jobs._refresh_running = True
    jobs._run_refresh()

    cached = cache.get(jobs.LAST_REFRESH_CACHE_KEY)
    assert cached["stratus_graph"].startswith("failed: RuntimeError")
    assert "OAUTH_SCOPE_MISMATCH" in cached["stratus_graph"]


def test_sync_returns_the_per_step_summary_rather_than_just_started(client, steps):
    """The whole point of the escape hatch: on this platform AppSail exposes
    bundle-creator logs and no RUNTIME logs, so a step that fails inside the background
    thread is invisible from outside and "started" is all the caller ever learns. That
    is how a blocked Stratus publish cancelled the AML sweep for a whole deployment
    without anyone being able to see it."""
    import os

    jobs._refresh_running = False
    r = client.post("/jobs/refresh?sync=true",
                    headers={"X-Veritas-Job-Token": os.environ["VERITAS_JOB_TOKEN"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "complete"
    # Every step is reported, and the one that blew up says so by name instead of
    # vanishing into a log nobody can read.
    assert set(body["steps"]) == {"gds", "stratus_graph", "vector_index", "aml",
                                  "series_scan", "fairness", "advisory"}
    assert body["steps"]["stratus_graph"].startswith("failed: RuntimeError")
    assert body["steps"]["aml"] == "aml-done"
    assert jobs._refresh_running is False
