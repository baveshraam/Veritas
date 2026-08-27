"""The persistent per-case investigation board — end to end, through the same HTTP
surface an officer's console actually calls. Mirrors test_acceptance.py's discipline:
real dataset, real tokens, nothing mocked, one test per workflow.

Board state is deliberately verified by opening a SECOND session against the API
(a fresh session_id, exactly what "start a new chat session" means from the client's
point of view) rather than only by re-reading the first session's own turns — the
whole point of the feature is that the board outlives one conversation.
"""
import json

import pytest

pytestmark = pytest.mark.usefixtures("indexed")


def _auth(client, badge_no: str) -> dict:
    r = client.post("/auth/token", json={"badge_no": badge_no})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _chat(client, headers: dict, query: str, session: str, active_evidence_id=None) -> dict:
    body = {"session_id": session, "query": query}
    if active_evidence_id:
        body["active_evidence_id"] = active_evidence_id
    r = client.post("/chat", headers=headers, json=body)
    assert r.status_code == 200, r.text

    traces, final, error = [], None, None
    for line in r.text.replace("\r\n", "\n").split("\n"):
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "trace":
            traces.append(evt)
        elif evt.get("type") == "final":
            final = evt
        elif evt.get("type") == "error":
            error = evt

    assert error is None, f"engine failed on {query!r}: {error}"
    assert final is not None, f"no final frame for {query!r}"
    return {"traces": traces, "final": final}


def _fir_with_named_accused(client, h, skip: int = 0):
    """The Nth case (by list order) that has a resolved accused. `skip` gives each
    test its own case — several tests in this module reuse the same `client`/
    `dataset`, and board state is meant to persist, so two tests picking the SAME
    case would see each other's pins/leads/notes and misreport a product bug."""
    found = 0
    for c in client.get("/cases", headers=h).json()["cases"]:
        detail = client.get(f"/fir/{c['fir_id']}", headers=h).json()
        linked = [a for a in detail.get("accused") or [] if a.get("PersonUID")]
        if linked:
            if found == skip:
                return detail, linked[0]
            found += 1
    pytest.fail(f"fewer than {skip + 1} cases in the index have a resolved accused")


# --- the core workflow: pin, note, lead, and the board surviving a new session -----

def test_board_survives_a_new_session_and_a_new_officer_look(client, officers):
    h = _auth(client, officers["DSP"]["badge_no"])
    fir, accused = _fir_with_named_accused(client, h, skip=0)

    # 1. open the case
    opened = _chat(client, h, f"What is the status of FIR {fir['fir_number']}?", "board-1")
    assert opened["final"]["citations"], "must have real evidence in view to pin"

    # 2. pin the evidence just shown ("pin this evidence" — no explicit selection, so
    #    it falls back to the top citation from the previous turn)
    pinned = _chat(client, h, "Pin this evidence to the case board", "board-1")
    assert "pinned" in pinned["final"]["final_answer"].lower()

    # 3. a note, in the officer's own words
    noted = _chat(client, h, "Add a note that this connection needs verification", "board-1")
    assert "note recorded" in noted["final"]["final_answer"].lower()

    # 4. a lead
    lead = _chat(client, h, "Save this as a lead: re-interview the complainant", "board-1")
    assert "saved as a lead" in lead["final"]["final_answer"].lower()

    # 5. GET /board directly — the durable record, not the conversation transcript
    b = client.get(f"/board/{fir['fir_id']}", headers=h).json()
    assert b["total"] == 3
    assert len(b["by_type"]["evidence"]) + len(b["by_type"]["finding"]) == 1
    assert len(b["by_type"]["note"]) == 1
    assert len(b["by_type"]["lead"]) == 1
    assert b["by_type"]["lead"][0]["status"] == "open"

    # 6. leave the session; start a genuinely NEW one (new session_id — the same thing
    #    a fresh browser tab/officer login produces) and re-open the same case
    _chat(client, h, f"What is the status of FIR {fir['fir_number']}?", "board-2-new-session")
    board_view = _chat(client, h, "What is on the board for this case?", "board-2-new-session")
    answer = board_view["final"]["final_answer"].lower()
    assert "3 item" in answer
    assert "pinned evidence" in answer or "finding" in answer
    assert "note" in answer
    assert "lead" in answer


def test_pinning_targets_the_evidence_card_the_console_had_selected(client, officers):
    """When the console sends `active_evidence_id` (the card the officer clicked),
    that exact item is pinned — not merely 'whatever came first' — so a click-driven
    pin and a typed 'pin this' agree on what gets saved."""
    h = _auth(client, officers["DSP"]["badge_no"])
    fir, _ = _fir_with_named_accused(client, h, skip=1)

    opened = _chat(client, h, f"What is the status of FIR {fir['fir_number']}?", "board-3")
    evidence = opened["final"]["evidence_items"]
    assert len(evidence) >= 1
    target = evidence[-1]           # not necessarily the first/default item

    _chat(client, h, "pin this", "board-3", active_evidence_id=target["evidence_id"])
    b = client.get(f"/board/{fir['fir_id']}", headers=h).json()
    pinned = (b["by_type"]["evidence"] + b["by_type"]["finding"])[0]
    assert pinned["ref_id"] == target["source_id"]
    assert pinned["content"] == target["content"]


def test_adding_a_person_to_the_investigation_via_conversation(client, officers):
    h = _auth(client, officers["DSP"]["badge_no"])
    fir, accused = _fir_with_named_accused(client, h, skip=2)
    person = client.get(f"/person/{accused['PersonUID']}", headers=h).json()
    assert person["name_en"]

    _chat(client, h, f"What is the status of FIR {fir['fir_number']}?", "board-4")
    net = _chat(client, h, f"Who are the associates of {person['name_en']}?", "board-4")
    assert net["final"] is not None

    added = _chat(client, h, "Add this person to the investigation", "board-4")
    assert person["name_en"] in added["final"]["final_answer"]

    b = client.get(f"/board/{fir['fir_id']}", headers=h).json()
    assert any(i["ref_id"] == str(person["person_id"]) for i in b["by_type"]["person"])


def test_lead_status_changes_are_explicit_and_auditable(client, officers):
    """The investigator decides — a status change only happens on an explicit
    instruction, and a dismissed lead stays on the board rather than disappearing."""
    h = _auth(client, officers["DSP"]["badge_no"])
    fir, _ = _fir_with_named_accused(client, h, skip=3)

    _chat(client, h, f"What is the status of FIR {fir['fir_number']}?", "board-5")
    _chat(client, h, "Save this as a lead: check the alibi", "board-5")

    dismissed = _chat(client, h, "Dismiss that lead", "board-5")
    assert "dismissed" in dismissed["final"]["final_answer"].lower()

    b = client.get(f"/board/{fir['fir_id']}", headers=h).json()
    leads = b["by_type"]["lead"]
    assert len(leads) == 1, "a dismissed lead must remain on the board, not disappear"
    assert leads[0]["status"] == "dismissed"


def test_a_board_action_with_no_open_case_refuses_instead_of_guessing(client, officers):
    h = _auth(client, officers["IG"]["badge_no"])
    result = _chat(client, h, "Pin this evidence", "board-6-fresh")
    assert result["final"]["citations"] == []
    assert "no case is open" in result["final"]["final_answer"].lower() \
        or "give me an fir number" in result["final"]["final_answer"].lower()


def test_pinning_with_nothing_in_view_gives_a_helpful_refusal_not_a_crash(client, officers):
    h = _auth(client, officers["DSP"]["badge_no"])
    fir, _ = _fir_with_named_accused(client, h, skip=4)
    # Open the case with a query that produces no evidence_items of its own to pin —
    # a capability question in the middle of the same session.
    _chat(client, h, f"What is the status of FIR {fir['fir_number']}?", "board-7")
    _chat(client, h, "what all could you answer", "board-7")   # no evidence this turn
    result = _chat(client, h, "pin this", "board-7")
    # Either it fell back to the FIR_LOOKUP turn's evidence (two turns back is not
    # "previous"), or it refuses helpfully — it must never raise.
    assert result["final"] is not None


# --- RBAC: a board is reachable only from a case the officer may already open ------

def test_an_io_cannot_read_or_write_another_stations_board(client, officers):
    from data import ds

    io = officers["IO"]
    h = _auth(client, io["badge_no"])
    other = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster" '
                      'WHERE "PoliceStationID" != :p', {"p": int(io["ps_code"])})
    assert other

    assert client.get(f"/board/{other}", headers=h).status_code == 403
    assert client.post(f"/board/{other}/items", headers=h,
                       json={"item_type": "note", "content": "sneaking in"}).status_code == 403


def test_a_board_action_via_chat_is_also_refused_cross_station(client, officers):
    """The RBAC rule must hold through the conversational path too, not only the
    direct REST path — an officer must never use the board to reach a case chat
    itself already refuses them."""
    from data import ds

    io = officers["IO"]
    h = _auth(client, io["badge_no"])
    other = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster" '
                      'WHERE "PoliceStationID" != :p', {"p": int(io["ps_code"])})
    assert other

    # An IO cannot even open the other station's case, so active_fir never becomes
    # `other` through legitimate conversation — this simulates a client that tries
    # to force it by asking a board question naming that FIR directly.
    result = _chat(client, h, f"What is the status of FIR {other}?", "board-8")
    assert result["final"]["citations"] == []   # refused; active_fir was never set to `other`


def test_no_token_is_refused(client, officers):
    from data import ds
    cid = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')
    assert client.get(f"/board/{cid}").status_code == 401


# --- auditability -------------------------------------------------------------------

def test_every_board_mutation_appends_to_the_audit_chain(client, officers):
    from data.audit import verify_chain

    h = _auth(client, officers["DSP"]["badge_no"])
    fir, _ = _fir_with_named_accused(client, h, skip=5)

    before = client.get(f"/board/{fir['fir_id']}", headers=h)  # counts as a read too
    r = client.post(f"/board/{fir['fir_id']}/items", headers=h,
                    json={"item_type": "note", "content": "audited note"})
    assert r.status_code == 200, r.text
    item_id = r.json()["item_id"]

    patched = client.patch(f"/board/{fir['fir_id']}/items/{item_id}", headers=h,
                           json={"content": "edited audited note"})
    assert patched.status_code == 200

    deleted = client.delete(f"/board/{fir['fir_id']}/items/{item_id}", headers=h)
    assert deleted.status_code == 200
    assert deleted.json()["item"]["content"] == "edited audited note"

    from data import ds
    assert ds.scalar('SELECT COUNT("AuditID") AS c FROM "vx_audit_log"') > 0
    assert verify_chain() == (True, None)


def test_deleting_a_lead_through_the_rest_api_is_rejected(client, officers):
    h = _auth(client, officers["DSP"]["badge_no"])
    fir, _ = _fir_with_named_accused(client, h, skip=6)

    r = client.post(f"/board/{fir['fir_id']}/items", headers=h,
                    json={"item_type": "lead", "content": "a lead", "status": "open"})
    item_id = r.json()["item_id"]

    d = client.delete(f"/board/{fir['fir_id']}/items/{item_id}", headers=h)
    assert d.status_code == 400
