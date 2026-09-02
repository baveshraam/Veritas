"""GET /sessions, GET /sessions/{id} — chat history pooled by rank+station.

Drives real /chat turns through the HTTP surface (same pattern as
test_acceptance.py) rather than writing to vx_session/vx_conversation_turn
directly, so this also proves the endpoint sees what /chat actually persists.
"""
import json

import pytest

pytestmark = pytest.mark.usefixtures("indexed")


def _auth(client, badge_no: str) -> dict:
    r = client.post("/auth/token", json={"badge_no": badge_no})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _chat(client, headers: dict, query: str, session: str) -> dict:
    r = client.post("/chat", headers=headers, json={"session_id": session, "query": query})
    assert r.status_code == 200, r.text
    final = None
    for line in r.text.replace("\r\n", "\n").split("\n"):
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        evt = json.loads(payload)
        if evt.get("type") == "final":
            final = evt
    assert final is not None, f"no final frame for {query!r}"
    return final


def test_sessions_requires_a_token(client, dataset):
    assert client.get("/sessions").status_code == 401


def test_a_session_appears_after_its_first_turn(client, dataset, officers):
    headers = _auth(client, officers["IO"]["badge_no"])
    _chat(client, headers, "What are the crime trends?", "sess-1")

    r = client.get("/sessions", headers=headers)
    assert r.status_code == 200, r.text
    assert any(s["session_id"] == "sess-1" for s in r.json())


def test_session_detail_returns_the_full_turn(client, dataset, officers):
    headers = _auth(client, officers["IO"]["badge_no"])
    _chat(client, headers, "What are the crime trends?", "sess-2")

    r = client.get("/sessions/sess-2", headers=headers)
    assert r.status_code == 200, r.text
    turns = r.json()
    assert len(turns) == 1
    assert turns[0]["query"] == "What are the crime trends?"
    assert turns[0]["final_answer"]


def test_session_detail_is_scoped_to_rank_and_station(client, dataset, officers):
    io_headers = _auth(client, officers["IO"]["badge_no"])
    _chat(client, io_headers, "What are the crime trends?", "sess-3")

    ig_headers = _auth(client, officers["IG"]["badge_no"])
    r = client.get("/sessions/sess-3", headers=ig_headers)
    assert r.status_code == 403


def test_session_detail_404s_for_an_unknown_session(client, dataset, officers):
    headers = _auth(client, officers["IO"]["badge_no"])
    assert client.get("/sessions/nope", headers=headers).status_code == 404
