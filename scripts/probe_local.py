"""Drive the LangGraph engine locally against the sqlite dataset.

`python scripts/probe_local.py --file qs.txt` or with questions as argv.
Same reporting shape as probe_questions.py, no deploy, no network.
"""
import os, sys, uuid, traceback
os.environ.setdefault("VERITAS_DS_BACKEND", "sqlite")

from rag_agent import run_investigation, InvestigationState   # noqa: E402


def one(q, role="SHO", officer_id="301", session=None, focus=None, evidence_id=None):
    kw = {}
    if focus is not None:
        kw["active_entities"] = focus
    st = InvestigationState(
        original_query=q, session_id=session or str(uuid.uuid4()),
        officer_id=officer_id, officer_role=role, language="en",
        active_evidence_id=evidence_id, **kw,
    )
    return run_investigation(st)


def main(argv):
    qs = []
    if argv and argv[0] == "--file":
        qs = [l.strip() for l in open(argv[1], encoding="utf-8")
              if l.strip() and not l.startswith("#")]
        argv = argv[2:]
    qs += [a for a in argv if not a.startswith("--")]
    role = "IG" if "--ig" in sys.argv else "SHO"
    for q in qs:
        try:
            r = one(q, role=role)
        except Exception as e:                                # noqa: BLE001
            print(f"[FAILED ] {q}\n           {type(e).__name__}: {e}")
            if "--tb" in sys.argv:
                traceback.print_exc()
            print()
            continue
        state = "REFUSED" if getattr(r, "answer_is_refusal", False) else "ok"
        ev = getattr(r, "evidence_items", None) or getattr(r, "evidence", []) or []
        viz = getattr(r, "visualization", None)
        kind = getattr(viz, "kind", None) if viz is not None else None
        print(f"[{state:7}] {q}")
        print(f"           op={r.intent} "
              f"ev={len(ev)} viz={kind}")
        print(f"           {(getattr(r, 'final_answer', '') or '')[:300]}".replace("\n", " "))
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
