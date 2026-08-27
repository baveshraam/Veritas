#!/usr/bin/env python
"""Checkable proof that a deploy changed LIVE behavior, not just that a pipeline
ran green — the acceptance standard this repo's own changelog has repeatedly
found violated (a healthy /health with stale behavior underneath).

Non-zero exit on ANY failed check. Run by hand post-deploy:

    python scripts/verify_live_deployment.py \
        --base-url https://veritas-api-50043864344.development.catalystappsail.in

What it checks, in order:
  1. /health responds and reports the expected fields present (not just 200).
  2. The primary behavioral probe: the exact two-turn sequence that failed on the
     pre-fix baseline (CRIME_SEARCH -> "Only these?" -> Intent: UNKNOWN -> refusal,
     captured in docs/superpowers/specs/2026-08-27-compositional-semantic-layer-
     design.md §1) now succeeds. This is the one check that actually distinguishes
     "the new code is live" from "the old code redeployed identically" — a green
     GitHub Action or a successful image upload proves neither.
  3. A short battery of further unseen conversational probes via
     scripts/adversarial_eval.py's own scenario list, run with --target live.
"""
import argparse
import json
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def check_health(base_url: str) -> list[str]:
    problems = []
    r = requests.get(f"{base_url}/health", timeout=60)
    if r.status_code != 200:
        return [f"/health returned {r.status_code}, not 200"]
    body = r.json()
    print(f"  /health: {json.dumps(body)}")
    for field in ("llm", "datastore", "firs", "graph_nodes", "graph_edges",
                  "vector_index", "cache"):
        if field not in body:
            problems.append(f"/health is missing expected field {field!r}")
    return problems


def check_baseline_defect_fixed(base_url: str, badge_no: str) -> list[str]:
    """The exact reproduction from the design spec's §1 baseline capture."""
    import uuid

    tok = requests.post(f"{base_url}/auth/token", json={"badge_no": badge_no}, timeout=30)
    if tok.status_code != 200:
        return [f"/auth/token failed: {tok.status_code} {tok.text[:200]}"]
    headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    sid = str(uuid.uuid4())

    def chat(query: str) -> dict:
        r = requests.post(f"{base_url}/chat", headers=headers,
                          json={"session_id": sid, "query": query}, timeout=90)
        r.raise_for_status()
        final, traces = None, []
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
                traces.append(evt.get("detail", ""))
            elif evt.get("type") == "final":
                final = evt
        return {"final": final, "traces": traces}

    turn1 = chat("How many theft cases are there in Bengaluru Urban?")
    turn2 = chat("Only these?")

    problems = []
    if turn2["final"] is None:
        return ["turn 2 ('Only these?') produced no final frame at all"]
    if any("Intent: UNKNOWN" in t for t in turn2["traces"]):
        problems.append(
            "REGRESSION NOT FIXED: 'Only these?' still classifies as UNKNOWN "
            f"(traces: {turn2['traces']})")
    if turn2["final"].get("refused"):
        problems.append(
            f"'Only these?' still refuses: {turn2['final'].get('final_answer', '')[:200]}")
    if not any("RESULT_SET_FOLLOWUP" in t for t in turn2["traces"]):
        problems.append(
            f"'Only these?' did not route through RESULT_SET_FOLLOWUP (traces: {turn2['traces']})")
    print(f"  turn 1 answer: {turn1['final']['final_answer'][:150] if turn1['final'] else '(none)'}")
    print(f"  turn 2 answer: {turn2['final'].get('final_answer', '')[:150]}")
    return problems


def check_adversarial_battery(base_url: str, badge_no: str) -> list[str]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "adversarial_eval", "scripts/adversarial_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    failures, results = mod.run_live(mod.SCENARIOS, base_url, badge_no)
    mod._report(results, sum(r.latency_s for r in results), "live")
    if failures:
        return [f"{failures}/{len(mod.SCENARIOS)} adversarial scenarios failed live"]
    return []


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", required=True)
    p.add_argument("--badge-no", default="KGID000386")
    p.add_argument("--skip-battery", action="store_true",
                   help="Skip the full adversarial battery, run only the two fast checks.")
    args = p.parse_args()

    all_problems = []

    print("1. /health")
    all_problems += [f"[health] {p_}" for p_ in check_health(args.base_url)]

    print("2. baseline defect (CRIME_SEARCH -> 'Only these?')")
    all_problems += [f"[baseline] {p_}" for p_ in
                     check_baseline_defect_fixed(args.base_url, args.badge_no)]

    if not args.skip_battery:
        print("3. adversarial conversational battery (live)")
        all_problems += [f"[battery] {p_}" for p_ in
                         check_adversarial_battery(args.base_url, args.badge_no)]

    print()
    if all_problems:
        print(f"DEPLOYMENT VERIFICATION FAILED ({len(all_problems)} problem(s)):")
        for p_ in all_problems:
            print(f"  - {p_}")
        return 1
    print("DEPLOYMENT VERIFICATION PASSED — live behavior matches the new code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
