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
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


@pytest.fixture
def officers(dataset):
    """One badge number per role, straight out of the Employee table."""
    from data import ds
    from data.generator.refdata import DESIGNATION_TO_ROLE

    out: dict[str, dict] = {}
    for r in ds.query('SELECT "EmployeeID", "DesignationID", "KGID", "UnitID" '
                      'FROM "Employee" ORDER BY "EmployeeID"'):
        role = DESIGNATION_TO_ROLE.get(r["DesignationID"])
        if role and role not in out:
            out[role] = {"badge_no": r["KGID"], "ps_code": str(r["UnitID"])}
    return out


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


def test_every_request_appends_to_the_audit_chain(client, officers, dataset):
    from data.audit import verify_chain

    h = _auth(client, officers["DSP"]["badge_no"])
    from data import ds
    case_id = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')
    client.get(f"/fir/{case_id}", headers=h)

    assert ds.scalar('SELECT COUNT("AuditID") AS c FROM "vx_audit_log"') > 0
    assert verify_chain() == (True, None)
