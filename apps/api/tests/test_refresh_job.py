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
    return called


def test_a_blocked_stratus_publish_does_not_cancel_the_aml_sweep(steps, caplog):
    """The exact live failure: the cache publish is the SECOND step, and the detector
    sweep is the fourth. Under one try/except, steps 3 and 4 never ran."""
    jobs._refresh_running = True
    jobs._run_refresh()

    assert steps == ["gds", "stratus_graph", "vector_index", "aml", "series_scan"], (
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
                                  "series_scan"}
    assert body["steps"]["stratus_graph"].startswith("failed: RuntimeError")
    assert body["steps"]["aml"] == "aml-done"
    assert jobs._refresh_running is False
