"""Fire questions at the LIVE /chat SSE and report what actually comes back.

Not a test: a driving harness. `python scripts/probe_questions.py "q1" "q2" ...`
or `--file questions.txt`. Prints one line per question — refused/failed/ok,
evidence count, visualization kind — then the answer's first 200 chars.
"""
import json, sys, urllib.request, os

API = os.getenv("VERITAS_API", "https://veritas-api-50043864344.development.catalystappsail.in")


def token(badge="KGID000301"):
    r = urllib.request.urlopen(urllib.request.Request(
        f"{API}/auth/token", data=json.dumps({"badge_no": badge}).encode(),
        headers={"content-type": "application/json"}), timeout=60)
    return json.load(r)["access_token"]


def ask(tok, session, q, evidence_id=None, timeout=180):
    body = {"session_id": session, "query": q, "language": "en"}
    if evidence_id:
        body["active_evidence_id"] = evidence_id
    req = urllib.request.Request(f"{API}/chat", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json",
                                          "authorization": f"Bearer {tok}"})
    final, trace = None, []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "trace":
                trace.append(ev)
            elif ev.get("type") == "final":
                final = ev
            elif ev.get("type") == "error":
                final = {"final_answer": "ENGINE ERROR: " + str(ev.get("detail")),
                         "refused": False, "failed": True,
                         "evidence_items": [], "visualization": {"kind": "none"}}
    return final, trace


def main(argv):
    qs = []
    if argv and argv[0] == "--file":
        qs = [l.strip() for l in open(argv[1], encoding="utf-8") if l.strip() and not l.startswith("#")]
        argv = argv[2:]
    qs += [a for a in argv if not a.startswith("--")]
    fresh = "--fresh" in sys.argv          # a new session per question
    tok = token()
    import uuid
    session = str(uuid.uuid4())
    for q in qs:
        sid = str(uuid.uuid4()) if fresh else session
        try:
            final, trace = ask(tok, sid, q)
        except Exception as e:                                # noqa: BLE001
            print(f"[EXC ] {q}\n       {type(e).__name__}: {e}\n")
            continue
        if not final:
            print(f"[NONE] {q}\n")
            continue
        op = next((t.get("detail", "") for t in trace if t.get("step", "").lower().startswith("intent")), "")
        state = ("FAILED" if final.get("failed")
                 else "REFUSED" if final.get("refused") else "ok")
        print(f"[{state:7}] {q}")
        print(f"           op={op[:90]!r} ev={len(final.get('evidence_items') or [])} "
              f"viz={(final.get('visualization') or {}).get('kind')}")
        print(f"           {(final.get('final_answer') or '')[:260]}".replace("\n", " "))
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
