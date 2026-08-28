"""The API, exercised against a real dataset.

These used to skip unless a Postgres stack was running, which meant the RBAC rules — the
part a government panel will actually poke at — were the least-tested code in the repo. The
Data Store client runs the same ZCQL against SQLite, so every one of them now runs on every
commit, with no stack at all.
"""
import os

import pytest

os.environ.setdefault("VERITAS_DEV_MODE", "1")


# --- auth, no database -------------------------------------------------------------
def test_token_roundtrip_carries_officer_and_role():
    import jwt as pyjwt
    from api.auth.jwt_auth import ALGORITHM, _secret, issue_token

    tok = issue_token("42", "DSP")
    claims = pyjwt.decode(tok, _secret(), algorithms=[ALGORITHM])
    assert claims["sub"] == "42" and claims["role"] == "DSP" and "exp" in claims


def test_a_forged_token_is_rejected():
    import jwt as pyjwt
    from api.auth.jwt_auth import ALGORITHM, _secret

    forged = pyjwt.encode({"sub": "x", "role": "IG"}, "not-the-secret", algorithm=ALGORITHM)
    with pytest.raises(pyjwt.InvalidTokenError):
        pyjwt.decode(forged, _secret(), algorithms=[ALGORITHM])


def test_refuses_a_default_secret_outside_dev_mode(monkeypatch):
    """A fallback signing secret is a backdoor — the app must not start with one."""
    from api.auth import jwt_auth

    monkeypatch.delenv("VERITAS_JWT_SECRET", raising=False)
    monkeypatch.delenv("VERITAS_DEV_MODE", raising=False)
    with pytest.raises(RuntimeError, match="VERITAS_JWT_SECRET"):
        jwt_auth._secret()


def test_audit_hashes_content_rather_than_storing_it():
    from api.audit import sha256

    payload = {"query": "Does Ramesh have priors?", "answer": "sensitive"}
    h = sha256(payload)
    assert len(h) == 64 and "Ramesh" not in h
    assert sha256(payload) == h                                  # stable
    assert sha256({**payload, "answer": "other"}) != h           # and content-bound


# --- endpoints ---------------------------------------------------------------------
# `client` and `officers` are in tests/conftest.py — the acceptance suite drives the
# same app through the same tokens, and two copies is two things to keep in step.


def _auth(client, badge_no: str) -> dict:
    r = client.post("/auth/token", json={"badge_no": badge_no})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_chat_requires_a_token(client, dataset):
    assert client.post("/chat", json={"session_id": "s", "query": "hi"}).status_code == 401


def test_an_unknown_badge_gets_no_token(client, dataset):
    assert client.post("/auth/token", json={"badge_no": "KGID999999"}).status_code == 401


def test_health_reports_what_is_actually_up(client, dataset):
    body = client.get("/health").json()
    assert body["api"] == "ok"
    assert body["datastore"] in ("sqlite", "catalyst")
    assert body["firs"] > 0
    # /health must say WHY the LLM is off, not just that it is: "deterministic" alone cannot
    # distinguish an unconfigured endpoint from an exhausted one, and those need different
    # fixes.
    assert body["llm"].startswith(("quickml", "deterministic"))
    assert "graph" in body
    # BUG-017: the changelog claimed model weights left the image for File Store, but
    # the only live evidence was Kannada response latency, which cannot actually tell
    # a File-Store-backed load apart from a still-baked-in one. /health must report the
    # real, observable state so this claim stays checkable instead of inferred.
    assert "model_weights" in body
    assert body["nllb_backend"] in (
        "not yet loaded",
        "ctranslate2 (VERITAS_NLLB_CT2_DIR present — local/baked directory)",
        "transformers (HF cache — File Store or baked, see model_weights)",
    )


def test_an_io_sees_only_their_own_stations_cases(client, officers):
    """The single most important rule in packages/policy."""
    from data import ds

    io = officers["IO"]
    own = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster" '
                    'WHERE "PoliceStationID" = :p', {"p": int(io["ps_code"])})
    other = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster" '
                      'WHERE "PoliceStationID" != :p', {"p": int(io["ps_code"])})
    assert own and other

    h = _auth(client, io["badge_no"])
    assert client.get(f"/fir/{own}", headers=h).status_code == 200
    # 403, not a filtered-empty 200: an IO is entitled to know the case exists and is simply
    # not theirs. Pretending it does not exist would be a lie told by an evidence system.
    assert client.get(f"/fir/{other}", headers=h).status_code == 403


def test_a_dsp_sees_across_stations(client, officers):
    from data import ds

    io_ps = int(officers["IO"]["ps_code"])
    other = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster" '
                      'WHERE "PoliceStationID" != :p', {"p": io_ps})
    h = _auth(client, officers["DSP"]["badge_no"])
    assert client.get(f"/fir/{other}", headers=h).status_code == 200


def test_the_case_list_is_scoped_the_same_way_the_chat_is(client, officers):
    """What you can list is exactly what you can ask about. A console that lists cases the
    chat then refuses to discuss is worse than one that lists nothing."""
    io_h = _auth(client, officers["IO"]["badge_no"])
    dsp_h = _auth(client, officers["DSP"]["badge_no"])

    io_body = client.get("/cases", headers=io_h).json()
    dsp_body = client.get("/cases", headers=dsp_h).json()

    assert io_body["total"] < dsp_body["total"]
    io_ps = officers["IO"]["ps_code"]
    assert all(c["ps_code"] == io_ps for c in io_body["cases"])


def test_person_identity_is_masked_below_dsp(client, officers, habitual):
    pid = habitual["PersonUID"]

    def get_as(role):
        h = _auth(client, officers[role]["badge_no"])
        return client.get(f"/person/{pid}", headers=h).json()

    as_io, as_dsp = get_as("IO"), get_as("DSP")
    assert as_io["name_en"] is None
    assert as_dsp["name_en"] == habitual["CanonicalName"]
    # The operational fields survive the mask — an IO still needs to know he is habitual.
    assert as_io["criminal_history"] == as_dsp["criminal_history"]


def test_a_person_carries_their_whole_history(client, officers, habitual):
    """The question the raw ER cannot answer. Every case here came through
    vx_accused_identity — without it, this list would have exactly one entry."""
    h = _auth(client, officers["DSP"]["badge_no"])
    body = client.get(f"/person/{habitual['PersonUID']}", headers=h).json()
    assert len(body["cases"]) > 1
    assert all(c["fir_number"] for c in body["cases"])


def test_the_copilot_briefs_a_real_case(client, officers, indexed):
    from data import ds

    case_id = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')
    h = _auth(client, officers["DSP"]["badge_no"])
    r = client.get(f"/copilot/{case_id}", headers=h)
    assert r.status_code == 200, r.text

    brief = r.json()
    assert brief["timeline"], "a case with no timeline"
    assert brief["draft_summary"]
    assert isinstance(brief["similar_cases"], list)


def test_the_case_timeline_is_reachable_and_chronological(client, officers, indexed):
    from data import ds

    case_id = ds.scalar('SELECT "Accused"."CaseMasterID" AS c FROM "Accused" '
                        'JOIN "vx_accused_identity" '
                        '  ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID"')
    h = _auth(client, officers["DSP"]["badge_no"])
    r = client.get(f"/timeline/case/{case_id}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    dates = [e["date"] for e in body["events"]]
    assert dates == sorted(dates)
    assert any(e["entity_type"] == "person" for e in body["entities"])


def test_the_case_timeline_obeys_the_same_station_rule_as_the_fir_endpoint(client, officers, indexed):
    """The exact BUG-003 discipline the copilot test above documents, re-applied to
    the timeline's own REST surface — a second reachable endpoint over a case an
    officer could not otherwise open would be the same rule enforced by one caller
    and not its neighbour."""
    from data import ds

    io = officers["IO"]
    other = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster" '
                      'WHERE "PoliceStationID" != :p', {"p": int(io["ps_code"])})
    assert other

    h = _auth(client, io["badge_no"])
    assert client.get(f"/timeline/case/{other}", headers=h).status_code == 403


def test_the_case_timeline_404s_on_a_missing_case(client, officers, dataset):
    h = _auth(client, officers["DSP"]["badge_no"])
    assert client.get("/timeline/case/999999999", headers=h).status_code == 404


def test_the_person_timeline_spans_their_cases(client, officers, habitual):
    h = _auth(client, officers["IG"]["badge_no"])
    r = client.get(f"/timeline/person/{habitual['PersonUID']}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["events"]
    assert any(e["entity_type"] == "case" for e in body["entities"])


def test_the_person_timeline_masks_names_below_dsp(client, officers, habitual):
    from policy import MASKED_NAME

    r = client.get(f"/timeline/person/{habitual['PersonUID']}",
                   headers=_auth(client, officers["SHO"]["badge_no"]))
    assert r.status_code == 200
    assert r.json()["name"] == MASKED_NAME


def test_every_request_appends_to_the_audit_chain(client, officers, dataset):
    from data.audit import verify_chain

    h = _auth(client, officers["DSP"]["badge_no"])
    from data import ds
    case_id = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')
    client.get(f"/fir/{case_id}", headers=h)

    assert ds.scalar('SELECT COUNT("AuditID") AS c FROM "vx_audit_log"') > 0
    assert verify_chain() == (True, None)


# --- Phase 1 regressions: one rule, every endpoint ---------------------------------
def test_the_copilot_obeys_the_same_station_rule_as_the_fir_endpoint(client, officers, indexed):
    """BUG-003. /copilot took its fir_id from the URL but read the case with a hardcoded
    ("SHO", "") scope, so an IO refused a case by /fir could read its whole brief —
    narrative, accused, associates, leads — one path over. A rule enforced by one endpoint
    and not its neighbour is not a rule."""
    from data import ds

    io = officers["IO"]
    other = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster" '
                      'WHERE "PoliceStationID" != :p', {"p": int(io["ps_code"])})
    assert other

    h = _auth(client, io["badge_no"])
    assert client.get(f"/fir/{other}", headers=h).status_code == 403
    assert client.get(f"/copilot/{other}", headers=h).status_code == 403


def test_an_accused_name_is_masked_on_every_endpoint_that_carries_it(client, officers, indexed):
    """BUG-004. /person nulled name_en below DSP while /fir printed the same person's
    AccusedName in full, and the Copilot built prose around it. Masking that one endpoint
    can be walked around is decoration."""
    from data import ds
    from policy import MASKED_NAME

    case_id = ds.scalar('SELECT "CaseMasterID" AS c FROM "Accused"')

    dsp = client.get(f"/fir/{case_id}", headers=_auth(client, officers["DSP"]["badge_no"]))
    assert dsp.status_code == 200
    dsp_names = [a["AccusedName"] for a in dsp.json()["accused"]]
    assert dsp_names and all(n and n != MASKED_NAME for n in dsp_names)

    # SHO is cross-station by policy but ranks below DSP, so it sees the case and not
    # the identity.
    sho = client.get(f"/fir/{case_id}", headers=_auth(client, officers["SHO"]["badge_no"]))
    assert sho.status_code == 200
    assert all(a["AccusedName"] == MASKED_NAME for a in sho.json()["accused"])

    # And the Copilot's prose must not put back what the record endpoint took out.
    brief = client.get(f"/copilot/{case_id}",
                       headers=_auth(client, officers["SHO"]["badge_no"]))
    if brief.status_code == 200:                      # SHO is in scope for every station
        blob = " ".join(brief.json()["leads"]) + " " + \
               " ".join(e["event"] for e in brief.json()["timeline"])
        for n in dsp_names:
            assert n not in blob, f"copilot leaked {n!r} to an SHO"


def test_alerts_refuses_an_unauthenticated_client(client, dataset):
    """BUG-005. The route originally called ws.accept() and began streaming district
    anomaly data to anyone who connected. It is no longer a WebSocket at all — live
    checks against the deployed AppSail gateway (curl with explicit Connection: Upgrade
    / Sec-WebSocket-* headers, and a real websocket-client) both got Starlette's own 404
    while an ordinary REST route on the identical domain correctly returned 401,
    consistent with AppSail's gateway not proxying WebSocket upgrades to a custom-runtime
    app at all. /alerts is now GET + SSE, the transport already proven live for /chat,
    authenticated the same way every other data-bearing route is: a missing or bad
    bearer token is rejected before any alert is ever produced."""
    assert client.get("/alerts").status_code == 401
    assert client.get("/alerts", headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401


def test_alerts_streams_for_an_authenticated_officer(client, dataset, officers, monkeypatch):
    """Exercises the route function and its SSE generator directly rather than through
    TestClient's HTTP transport: an infinite generator (the poll loop only ends on
    client disconnect) makes `client.stream(...)`'s __enter__ block indefinitely under
    Starlette's sync TestClient — confirmed with a minimal FastAPI+EventSourceResponse
    reproduction outside this project entirely, so it is a transport-layer property of
    testing infinite SSE streams synchronously, not a defect in this route. Auth
    enforcement is already covered end-to-end via real HTTP in the test above; this
    covers what that transport can't: that an authenticated call actually produces a
    live alert."""
    import asyncio

    from api.routers import alerts as alerts_router
    from ml_models.serving import AnomalyAlert

    fake_alert = AnomalyAlert(
        alert_id="a1", district_code="KA01", metric="case_count",
        observed=42.0, expected=10.0, severity="high",
        detected_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    monkeypatch.setattr(alerts_router, "_districts", lambda: ["KA01"])
    monkeypatch.setattr(alerts_router, "check_anomalies", lambda dc: [fake_alert])

    class _FakeRequest:
        async def is_disconnected(self):
            return False

    from api.auth.jwt_auth import officer_from_token
    token = _auth(client, officers["DSP"]["badge_no"])["Authorization"].split(" ", 1)[1]
    off = officer_from_token(token)

    async def run():
        resp = await alerts_router.alerts(_FakeRequest(), off)
        assert resp.media_type == "text/event-stream"
        item = await asyncio.wait_for(resp.body_iterator.__anext__(), timeout=10)
        assert item["event"] == "alert"
        assert "KA01" in item["data"]

    asyncio.run(run())


# --- BUG-024: /jobs/refresh must not block the request on a multi-minute job -------
#
# Measured live: at the dataset's real size, POST /jobs/refresh consistently 500'd
# around 15-16s. Timed the GDS algorithms alone at production scale locally (179s for
# pivot-sampled betweenness at the full graph's reported size; 8.23s at the more
# accurate co-offending-projection scale the code actually runs on) -- inconclusive on
# which step dominates, but conclusive that none of this belongs inside a synchronous
# HTTP handler. Cron only needs the trigger call to succeed.

def test_refresh_returns_immediately_instead_of_blocking_on_the_recompute(
        client, officers, monkeypatch):
    import time

    from api.routers import jobs as jobs_router

    started = {"gds": False, "graph": False, "reindex": False}
    release = threading_event = __import__("threading").Event()

    def slow_gds():
        threading_event.wait(timeout=2)   # stands in for a multi-minute computation
        started["gds"] = True
        return {"nodes": 1}

    monkeypatch.setattr("data.gds.run_all", slow_gds)
    monkeypatch.setattr("data.graph.publish_graph", lambda: started.__setitem__("graph", True) or True)
    monkeypatch.setattr("data.embeddings.index_job.run_all",
                        lambda: started.__setitem__("reindex", True) or {"docs": 1})
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_refresh_running", False)

    t0 = time.monotonic()
    r = client.post("/jobs/refresh", headers={"X-Veritas-Job-Token": "test-token"})
    elapsed = time.monotonic() - t0

    assert r.status_code == 200
    assert r.json() == {"status": "started"}
    assert elapsed < 1.0, f"the request blocked for {elapsed:.2f}s waiting on the job"
    assert started == {"gds": False, "graph": False, "reindex": False}, \
        "the response returned before the job had even started, which is correct -- " \
        "but the job itself must still run: released below"

    release.set()
    for _ in range(50):
        if all(started.values()):
            break
        time.sleep(0.05)
    assert started == {"gds": True, "graph": True, "reindex": True}, \
        "the background thread never completed the job"


def test_refresh_refuses_to_overlap_a_run_already_in_flight(client, officers, monkeypatch):
    import threading

    from api.routers import jobs as jobs_router

    gate = threading.Event()
    monkeypatch.setattr("data.gds.run_all", lambda: gate.wait(timeout=2) and {})
    monkeypatch.setattr("data.graph.publish_graph", lambda: True)
    monkeypatch.setattr("data.embeddings.index_job.run_all", lambda: {})
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_refresh_running", False)

    try:
        first = client.post("/jobs/refresh", headers={"X-Veritas-Job-Token": "test-token"})
        second = client.post("/jobs/refresh", headers={"X-Veritas-Job-Token": "test-token"})
        assert first.json() == {"status": "started"}
        assert second.json() == {"status": "already_running"}
    finally:
        gate.set()


def test_refresh_still_requires_the_job_token(client, officers, monkeypatch):
    from api.routers import jobs as jobs_router
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_refresh_running", False)

    assert client.post("/jobs/refresh").status_code == 401
    assert client.post("/jobs/refresh",
                       headers={"X-Veritas-Job-Token": "wrong"}).status_code == 401


# --- BUG-025 follow-up: /jobs/audit-verify must not block Cron on a cold container -
#
# Live evidence: after BUG-025's URL/token fix landed, veritas_refresh's Cron entry
# recorded a real unattended success (success_count 0 -> 1), but veritas_audit_verify
# kept failing every scheduled fire (failure_count kept climbing past the 20 already
# logged). The difference: audit_verify's old body called verify_chain() -> ds.query()
# synchronously, which is exactly the call that pays the ~23s mirror-hydration cost on
# a cold container (BUG-001) -- inside a request Cron gives up on well before that.
# /jobs/refresh never touches the data layer before responding, which is why it alone
# survived a cold fire.

def test_audit_verify_returns_immediately_instead_of_blocking_on_the_recompute(
        client, officers, monkeypatch):
    import time

    from api.routers import jobs as jobs_router

    started = {"verify": False}
    gate = __import__("threading").Event()

    def slow_verify_chain():
        gate.wait(timeout=2)   # stands in for the cold-container mirror hydration cost
        started["verify"] = True
        return True, None

    monkeypatch.setattr("data.audit.verify_chain", slow_verify_chain)
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_audit_running", False)

    t0 = time.monotonic()
    r = client.get("/jobs/audit-verify", headers={"X-Veritas-Job-Token": "test-token"})
    elapsed = time.monotonic() - t0

    assert r.status_code == 200
    assert r.json() == {"status": "started"}
    assert elapsed < 1.0, f"the request blocked for {elapsed:.2f}s waiting on the job"
    assert started == {"verify": False}, \
        "the response returned before the job had even started, which is correct -- " \
        "but the job itself must still run: released below"

    gate.set()
    for _ in range(50):
        if started["verify"]:
            break
        time.sleep(0.05)
    assert started == {"verify": True}, "the background thread never completed the job"


def test_audit_verify_sync_param_still_answers_inline(client, officers, monkeypatch):
    from api.routers import jobs as jobs_router

    monkeypatch.setattr("data.audit.verify_chain", lambda: (True, None))
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_audit_running", False)

    r = client.get("/jobs/audit-verify?sync=true",
                   headers={"X-Veritas-Job-Token": "test-token"})
    assert r.status_code == 200
    assert r.json() == {"intact": True, "first_bad_audit_id": None}


def test_audit_verify_sync_param_reports_a_broken_chain_inline(client, officers, monkeypatch):
    from api.routers import jobs as jobs_router

    monkeypatch.setattr("data.audit.verify_chain", lambda: (False, 7))
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_audit_running", False)

    r = client.get("/jobs/audit-verify?sync=true",
                   headers={"X-Veritas-Job-Token": "test-token"})
    assert r.status_code == 200
    assert r.json() == {"intact": False, "first_bad_audit_id": 7}


def test_audit_verify_refuses_to_overlap_a_run_already_in_flight(client, officers, monkeypatch):
    import threading

    from api.routers import jobs as jobs_router

    gate = threading.Event()
    monkeypatch.setattr("data.audit.verify_chain", lambda: gate.wait(timeout=2) and (True, None))
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_audit_running", False)

    try:
        first = client.get("/jobs/audit-verify", headers={"X-Veritas-Job-Token": "test-token"})
        second = client.get("/jobs/audit-verify", headers={"X-Veritas-Job-Token": "test-token"})
        assert first.json() == {"status": "started"}
        assert second.json() == {"status": "already_running"}
    finally:
        gate.set()


def test_audit_verify_still_requires_the_job_token(client, officers, monkeypatch):
    from api.routers import jobs as jobs_router
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_audit_running", False)

    assert client.get("/jobs/audit-verify").status_code == 401
    assert client.get("/jobs/audit-verify",
                      headers={"X-Veritas-Job-Token": "wrong"}).status_code == 401


# --- BUG-023 live fix: /jobs/regenerate_narratives --------------------------------
#
# The Data Store SDK only authenticates from real per-request Catalyst headers, so
# the narrative backfill (an ordinary in-place UPDATE, not a data regeneration —
# see data.generator.narrative_backfill) cannot be driven from a developer's own
# machine. It runs the same way /jobs/refresh does: triggered by a request, finishing
# on a background thread after the response returns.

def test_regenerate_narratives_returns_immediately_and_then_runs(client, officers, monkeypatch):
    import time

    from api.routers import jobs as jobs_router

    started = {"backfill": False, "reindex": False}
    gate = __import__("threading").Event()

    def slow_backfill():
        gate.wait(timeout=2)
        started["backfill"] = True
        return 1

    monkeypatch.setattr("data.generator.narrative_backfill.backfill_narratives", slow_backfill)
    monkeypatch.setattr("data.embeddings.index_job.run_all",
                        lambda: started.__setitem__("reindex", True) or {"docs": 1})
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_narrative_running", False)

    t0 = time.monotonic()
    r = client.post("/jobs/regenerate_narratives", headers={"X-Veritas-Job-Token": "test-token"})
    elapsed = time.monotonic() - t0

    assert r.status_code == 200
    assert r.json() == {"status": "started"}
    assert elapsed < 1.0, f"the request blocked for {elapsed:.2f}s waiting on the job"

    gate.set()
    for _ in range(50):
        if all(started.values()):
            break
        time.sleep(0.05)
    assert started == {"backfill": True, "reindex": True}, \
        "the background thread never completed the job"


def test_regenerate_narratives_refuses_to_overlap_a_run_already_in_flight(
        client, officers, monkeypatch):
    import threading

    from api.routers import jobs as jobs_router

    gate = threading.Event()
    monkeypatch.setattr("data.generator.narrative_backfill.backfill_narratives",
                        lambda: gate.wait(timeout=2) and 0)
    monkeypatch.setattr("data.embeddings.index_job.run_all", lambda: {})
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_narrative_running", False)

    try:
        first = client.post("/jobs/regenerate_narratives",
                            headers={"X-Veritas-Job-Token": "test-token"})
        second = client.post("/jobs/regenerate_narratives",
                             headers={"X-Veritas-Job-Token": "test-token"})
        assert first.json() == {"status": "started"}
        assert second.json() == {"status": "already_running"}
    finally:
        gate.set()


def test_regenerate_narratives_still_requires_the_job_token(client, officers, monkeypatch):
    from api.routers import jobs as jobs_router
    monkeypatch.setenv("VERITAS_JOB_TOKEN", "test-token")
    monkeypatch.setattr(jobs_router, "_narrative_running", False)

    assert client.post("/jobs/regenerate_narratives").status_code == 401
    assert client.post("/jobs/regenerate_narratives",
                       headers={"X-Veritas-Job-Token": "wrong"}).status_code == 401


# --- North Star Phase 6: PDF export must say WHY it degraded, not just that it did -
#
# BUG-018. The previous bare `except Exception: return None` on both the SmartBrowz
# and local-Chrome paths made every failure indistinguishable from every other one —
# exactly the diagnostic gap BUG-012 named for QuickML. The console was never lying
# (an HTML fallback with an honest header is a real, printable document, not a fake
# PDF), but nobody could tell WHY a PDF didn't render without re-reading the code.

def test_export_reports_why_no_pdf_rendered(client, officers, dataset, monkeypatch):
    from data import write_conversation_turn

    h = _auth(client, officers["IG"]["badge_no"])
    write_conversation_turn("export-test-1", 0, "test query", "en", "test answer",
                            [], [], {}, [])

    from api.routers import export as export_router
    monkeypatch.setattr(export_router, "_smartbrowz_pdf",
                        lambda page: (None, "SomeError: smartbrowz unreachable"))
    monkeypatch.setattr(export_router, "_local_pdf",
                        lambda page: (None, "FileNotFoundError: no browser"))

    r = client.post("/export/pdf", json={"session_id": "export-test-1"}, headers=h)
    assert r.status_code == 200
    assert r.headers["x-veritas-pdf"] == "unavailable"
    assert "smartbrowz unreachable" in r.headers["x-veritas-pdf-smartbrowz-reason"]
    assert "no browser" in r.headers["x-veritas-pdf-local-reason"]
    assert r.headers["content-type"].startswith("text/html")


def test_export_returns_a_real_pdf_when_a_renderer_is_available(client, officers, dataset,
                                                                 monkeypatch):
    from data import write_conversation_turn

    h = _auth(client, officers["IG"]["badge_no"])
    write_conversation_turn("export-test-2", 0, "test query", "en", "test answer",
                            [], [], {}, [])

    from api.routers import export as export_router
    monkeypatch.setattr(export_router, "_smartbrowz_pdf",
                        lambda page: (b"%PDF-1.4 fake but real bytes", "ok"))
    called_local = []
    monkeypatch.setattr(export_router, "_local_pdf",
                        lambda page: (called_local.append(1), (None, "should not run"))[1])

    r = client.post("/export/pdf", json={"session_id": "export-test-2"}, headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-1.4 fake but real bytes"
    assert called_local == [], "local renderer ran even though SmartBrowz already succeeded"


def test_export_requires_a_real_conversation(client, officers, dataset):
    h = _auth(client, officers["IG"]["badge_no"])
    r = client.post("/export/pdf", json={"session_id": "no-such-session-at-all"}, headers=h)
    assert r.status_code == 404


def test_signing_in_before_the_records_are_loaded_says_so_instead_of_500ing(client, monkeypatch):
    """Sign-in is the first thing anyone does, and on a cold container the first thing
    to touch the data layer — so it pays the one-off mirror hydration. Observed live: a
    bare 500 from /auth/token seconds after a redeploy, succeeding on retry once warm.

    "500" on a sign-in screen is indistinguishable from a broken deployment. 503 is the
    truthful status and the one the console's gate already treats as "warming up".
    """
    from data import ds

    def _cold(*a, **k):
        raise RuntimeError("mirror is still hydrating")

    monkeypatch.setattr(ds, "one", _cold)
    monkeypatch.setattr(ds, "query", _cold)

    r = client.post("/auth/token", json={"badge_no": "KGID000387"})
    assert r.status_code == 503, r.text
    assert "retry" in r.json()["detail"].lower()
    assert "RuntimeError" in r.json()["detail"], (
        "a genuine data-layer fault must stay diagnosable, not be hidden as a warm-up")

    assert client.get("/auth/officers").status_code == 503


def test_an_unknown_badge_is_still_401_not_a_warm_up_message(client):
    """The 503 wrapper must not swallow a real authentication decision."""
    r = client.post("/auth/token", json={"badge_no": "KGID999999"})
    assert r.status_code == 401
