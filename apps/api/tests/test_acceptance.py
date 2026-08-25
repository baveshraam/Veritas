"""Acceptance tests: the workflows an officer actually performs, end to end.

Phase 1 added these because the repo had unit tests and endpoint tests but nothing that
walked a whole task. A passing unit test is not a working feature — the audit found
`/copilot` bypassing the station rule, answers citing records that did not support them,
and one refusal message covering five different situations, none of which any existing
test could have caught, because each individual piece did what it said.

Every test here goes through the HTTP surface with a real token, against the real
dataset the `dataset` fixture builds. Nothing is mocked. The suite is written to run
repeatedly from a clean state: no test depends on another having run, and none writes
data another reads.
"""
import json

import pytest

pytestmark = pytest.mark.usefixtures("indexed")


# --- helpers ----------------------------------------------------------------------

def _auth(client, badge_no: str) -> dict:
    r = client.post("/auth/token", json={"badge_no": badge_no})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _chat(client, headers: dict, query: str, session: str) -> dict:
    """POST /chat and collapse the SSE stream into {traces, final, error}."""
    r = client.post("/chat", headers=headers,
                    json={"session_id": session, "query": query})
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


def _intent(result: dict) -> str:
    for t in result["traces"]:
        if t["step"] == "Orchestrator":
            return t["detail"].split(";")[0].replace("Intent: ", "").strip()
    return ""


# --- the investigation workflow ---------------------------------------------------

def test_an_officer_can_work_a_case_from_the_index_to_a_cited_answer(client, officers):
    """Login -> case index -> open the FIR -> identify a person -> their prior cases ->
    their relationships -> ask a grounded question -> every citation resolves to an
    evidence item that is actually in the payload.

    This is the walk the console performs. It is one test on purpose: the value is in
    the handoffs between steps, which is exactly what unit tests cannot see."""
    h = _auth(client, officers["DSP"]["badge_no"])

    # 1. the case index the console opens on
    index = client.get("/cases", headers=h)
    assert index.status_code == 200
    cases = index.json()["cases"]
    assert cases, "the case index is empty — nothing downstream is reachable"

    # the index must not repeat a record: an officer cannot tell two identical rows apart
    ids = [c["fir_id"] for c in cases]
    assert len(ids) == len(set(ids))

    # 2. open a case that actually has an accused on it, so the walk can continue
    fir, accused = None, None
    for c in cases:
        detail = client.get(f"/fir/{c['fir_id']}", headers=h)
        assert detail.status_code == 200
        body = detail.json()
        linked = [a for a in body.get("accused") or [] if a.get("PersonUID")]
        if linked:
            fir, accused = body, linked[0]
            break
    assert fir is not None, "no case in the index has a resolved accused"

    assert fir["fir_number"] and fir["case_status"]
    assert fir["ps_code"] == [c for c in cases if c["fir_id"] == fir["fir_id"]][0]["ps_code"]

    # 3. the accused resolves to a person with a cross-case identity
    person = client.get(f"/person/{accused['PersonUID']}", headers=h)
    assert person.status_code == 200
    person = person.json()
    assert person["name_en"], "a DSP must see the identity"

    # 4. their prior cases — and this case must be among them
    assert person["cases"], "a person reached from a case has no cases"
    assert str(fir["fir_id"]) in {c["fir_id"] for c in person["cases"]}

    # 5. their relationships
    net = _chat(client, h, f"Who are the associates of {person['name_en']}?", "acc-1")
    assert _intent(net) == "PERSON_NETWORK"

    # 6. a grounded question about the case, by its FIR number
    ask = _chat(client, h, f"What is the status of FIR {fir['fir_number']}?", "acc-2")
    assert _intent(ask) == "FIR_LOOKUP"
    final = ask["final"]

    # 7. the answer names the FIR that was asked about
    assert fir["fir_number"] in final["final_answer"]

    # 8. and every citation opens onto an evidence item that is present in the payload
    evidence_ids = {e["evidence_id"] for e in final["evidence_items"]}
    assert final["citations"], "a grounded answer with no citations is not grounded"
    for c in final["citations"]:
        assert c["evidence_id"] in evidence_ids, (
            f"citation [{c['index']}] points at {c['evidence_id']!r}, "
            "which is not in the evidence the console was given")
    assert [c["index"] for c in final["citations"]] == \
           list(range(1, len(final["citations"]) + 1)), "citations are not 1..n in order"


def test_an_exact_fir_lookup_cites_that_fir_and_not_its_neighbours(client, officers):
    """BUG-006, at the level the officer sees it. Every cited record must be about the
    FIR that was asked about — a real record from another district is still the wrong
    answer."""
    h = _auth(client, officers["IG"]["badge_no"])
    cases = client.get("/cases", headers=h).json()["cases"]
    target = cases[0]

    result = _chat(client, h, f"What is the status of FIR {target['fir_number']}?", "acc-3")
    final = result["final"]

    assert final["citations"], "the store holds this FIR; refusing it would be wrong"
    for e in final["evidence_items"]:
        assert e["source_id"] == str(target["fir_id"]), (
            f"cited {e['source_type']} {e['evidence_id']} (source {e['source_id']}) "
            f"under a question about FIR {target['fir_id']}")

    # and the trace says the semantic search was deliberately skipped, not merely absent
    steps = {t["step"]: t["detail"] for t in result["traces"]}
    assert "Vector Search Agent" in steps
    assert "Skipped" in steps["Vector Search Agent"]


def test_the_same_case_reads_the_same_way_twice(client, officers):
    """Repeatable from a clean state: the console renders the first N rows, so an
    unstable answer to a repeated question is indistinguishable from a changed record."""
    h = _auth(client, officers["IG"]["badge_no"])
    target = client.get("/cases", headers=h).json()["cases"][0]
    q = f"What is the status of FIR {target['fir_number']}?"

    first = _chat(client, h, q, "acc-4")["final"]
    second = _chat(client, h, q, "acc-5")["final"]

    assert first["final_answer"] == second["final_answer"]
    assert [c["evidence_id"] for c in first["citations"]] == \
           [c["evidence_id"] for c in second["citations"]]


# --- the negative workflow --------------------------------------------------------

def test_a_nonexistent_fir_is_refused_rather_than_answered_from_neighbours(client, officers):
    h = _auth(client, officers["IG"]["badge_no"])
    result = _chat(client, h, "What is the status of FIR 999999999999999999?", "neg-1")
    final = result["final"]

    assert final["citations"] == []
    assert "no record with that number exists" in final["final_answer"].lower()
    # and it must not overclaim: absent from the store within scope, not absent full stop
    assert "within your access scope" in final["final_answer"].lower()


def test_an_unknown_person_is_refused_and_no_one_is_substituted(client, officers):
    """The dangerous failure here is not refusing — it is answering about someone else."""
    h = _auth(client, officers["IG"]["badge_no"])
    result = _chat(client, h, "Tell me about Zzyzx Nonexistentperson", "neg-2")

    assert result["final"]["citations"] == []
    assert "no person of that name" in result["final"]["final_answer"].lower()


def test_a_question_with_no_subject_says_so_instead_of_searching(client, officers):
    """BUG-010. It used to sweep the index, discard the results, and then tell the
    officer to check whether a record exists — when no record was ever named."""
    h = _auth(client, officers["IG"]["badge_no"])
    result = _chat(client, h, "Show me the money trail", "neg-3")
    final = result["final"]

    assert final["citations"] == []
    assert "needs a subject" in final["final_answer"].lower()
    assert "check whether the record exists" not in final["final_answer"].lower()
    assert not any(t["step"] == "Vector Search Agent" for t in result["traces"]), \
        "retrieval ran for a question that named nothing to retrieve"


def test_a_request_to_nominate_a_suspect_is_declined_on_its_merits(client, officers):
    """Not a retrieval failure. The records hold who was accused, arrested and charged;
    they do not designate suspects, and the refusal has to say that."""
    h = _auth(client, officers["IG"]["badge_no"])
    final = _chat(client, h, "who could be the suspect", "neg-4")["final"]

    assert final["citations"] == []
    answer = final["final_answer"].lower()
    assert "do not nominate suspects" in answer
    assert "check whether the record exists" not in answer


def test_a_question_about_the_tool_is_answered_without_citations(client, officers):
    """BUG-009. The one out-of-scope question that gets an answer — and it carries no
    citations, because there is no record behind a description of the system."""
    h = _auth(client, officers["IG"]["badge_no"])
    final = _chat(client, h, "what all could you answer", "neg-5")["final"]

    assert final["citations"] == []
    answer = final["final_answer"].lower()
    assert "i answer questions against the fir records" in answer
    assert "do not name suspects" in answer          # limits, not only features
    assert "could not find this in the available records" not in answer


def test_an_io_is_refused_another_stations_case_by_every_route_that_can_return_it(
        client, officers):
    """BUG-003. The rule belongs to the case, not to the endpoint. This is the negative
    workflow's authorization leg: request data you are not entitled to, four ways."""
    from data import ds

    io = officers["IO"]
    h = _auth(client, io["badge_no"])
    other = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster" '
                      'WHERE "PoliceStationID" != :p', {"p": int(io["ps_code"])})
    assert other

    assert client.get(f"/fir/{other}", headers=h).status_code == 403
    assert client.get(f"/copilot/{other}", headers=h).status_code == 403

    # the index never offers it in the first place
    listed = {c["fir_id"] for c in client.get("/cases", headers=h).json()["cases"]}
    assert str(other) not in listed

    # and no token at all is refused outright
    assert client.get(f"/fir/{other}").status_code == 401


def test_what_an_officer_can_list_is_what_they_can_open(client, officers):
    """A console that lists a case the detail view then refuses is worse than one that
    lists nothing: it teaches the officer that refusals are arbitrary."""
    h = _auth(client, officers["IO"]["badge_no"])
    for c in client.get("/cases", headers=h).json()["cases"][:10]:
        assert client.get(f"/fir/{c['fir_id']}", headers=h).status_code == 200
