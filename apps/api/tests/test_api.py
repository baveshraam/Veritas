"""API checks. Auth logic runs without a database; endpoint tests skip without one."""
import os

import pytest

os.environ.setdefault("VERITAS_DEV_MODE", "1")


def _db_up() -> bool:
    try:
        from data.db import get_session
        from sqlalchemy import text
        with get_session() as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_up(), reason="requires the Postgres dev stack")


# --- auth (no DB) ------------------------------------------------------------

def test_token_roundtrip_carries_officer_and_role():
    import jwt as pyjwt
    from api.auth.jwt_auth import ALGORITHM, _secret, issue_token

    tok = issue_token("11111111-1111-1111-1111-111111111111", "DSP")
    claims = pyjwt.decode(tok, _secret(), algorithms=[ALGORITHM])
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["role"] == "DSP"
    assert "exp" in claims


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
    assert sha256(payload) == h                      # stable
    assert sha256({**payload, "answer": "other"}) != h


# --- endpoints (need the stack) ----------------------------------------------

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


@needs_db
def test_chat_requires_a_token(client):
    r = client.post("/chat", json={"session_id": "s", "query": "hi"})
    assert r.status_code == 401


@needs_db
def test_health_reports_dependencies(client):
    body = client.get("/health").json()
    assert body["api"] == "ok"
    # /health must say WHY the LLM is off, not just that it is: "deterministic" alone
    # can't distinguish an unset key from a 429'd quota, and those need different fixes.
    assert body["llm"].startswith(("gemini", "deterministic"))
    assert "postgres" in body and "neo4j" in body


@needs_db
def test_io_cannot_read_another_stations_fir(client):
    from data.db import get_session
    from sqlalchemy import text

    with get_session() as s:
        io = s.execute(text(
            "SELECT badge_no, ps_code FROM officer WHERE role='IO' LIMIT 1")).first()
        own = s.execute(text("SELECT fir_id FROM fir WHERE ps_code=:p LIMIT 1"),
                        {"p": io.ps_code}).scalar()
        other = s.execute(text("SELECT fir_id FROM fir WHERE ps_code<>:p LIMIT 1"),
                          {"p": io.ps_code}).scalar()

    tok = client.post("/auth/token", json={"badge_no": io.badge_no}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"/fir/{own}", headers=h).status_code == 200
    assert client.get(f"/fir/{other}", headers=h).status_code == 403


@needs_db
def test_victim_identity_is_masked_below_dsp(client):
    from data.db import get_session
    from sqlalchemy import text

    with get_session() as s:
        pid = s.execute(text(
            "SELECT person_id FROM person WHERE criminal_history LIMIT 1")).scalar()
        io = s.execute(text("SELECT badge_no FROM officer WHERE role='IO' LIMIT 1")).scalar()
        dsp = s.execute(text("SELECT badge_no FROM officer WHERE role='DSP' LIMIT 1")).scalar()

    def get_as(badge):
        tok = client.post("/auth/token", json={"badge_no": badge}).json()["access_token"]
        return client.get(f"/person/{pid}",
                          headers={"Authorization": f"Bearer {tok}"}).json()

    as_io, as_dsp = get_as(io), get_as(dsp)
    assert as_io["name_en"] is None and as_io["aadhaar_hash"] is None
    assert as_dsp["name_en"] is not None
    assert as_io["criminal_history"] == as_dsp["criminal_history"]   # operational field kept
