#!/usr/bin/env python
"""Rotate the two Veritas-owned shared secrets on the deployed AppSail app.

Which secrets, and why only these two:

  VERITAS_JWT_SECRET  signs the fallback officer token (Catalyst Authentication is
                      tried first; this is the path that works without a browser
                      session). Rotating invalidates tokens already issued, which is
                      the point — anyone holding one loses it.
  VERITAS_JOB_TOKEN   the shared secret the two Catalyst Cron jobs present on
                      /jobs/refresh and /jobs/audit-verify. It lives in TWO places, so
                      this rotates both together: the app's environment AND each cron
                      entry's request header. Changing one without the other is how
                      those jobs silently failed 20 times before (CLAUDE.md v12).

Deliberately NOT rotated here: QUICKML_CLIENT_ID / QUICKML_CLIENT_SECRET /
QUICKML_REFRESH_TOKEN. A Zoho self-client's secret can only be regenerated in the API
Console UI by a human, and the refresh token is derived from it — there is no Admin API
route, so a script that claimed to rotate them would be lying.

No secret value is printed, at any verbosity. The old values are not read back and the
new ones are generated, written and discarded. Run:

    CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python scripts/rotate_secrets.py
    CATALYST_ACCESS_TOKEN=... python scripts/rotate_secrets.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request

PROJECT_ID = "52852000000013048"
APPSAIL_RESOURCE_ID = "52852000000204688"          # NOT the public hostname number
API_BASE = "https://api.catalyst.zoho.in/baas/v1"

ROTATE = ("VERITAS_JWT_SECRET", "VERITAS_JOB_TOKEN")
CRON_HEADER = "X-Veritas-Job-Token"


def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API_BASE}/project/{PROJECT_ID}{path}", data=data, method=method,
        headers={
            "Authorization": f"Zoho-oauthtoken {token}",
            "ENVIRONMENT": "Development",          # 'DEVELOPMENT'/'development' are rejected
            "Content-Type": "application/json",
        })
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change; write nothing")
    args = ap.parse_args()

    token = os.getenv("CATALYST_ACCESS_TOKEN", "").strip()
    if not token:
        print("CATALYST_ACCESS_TOKEN is not set "
              "(CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js))", file=sys.stderr)
        return 2

    # 1. Read the CURRENT environment map and write it back whole with only the two
    #    values replaced. The configuration endpoint replaces the map it is given, so
    #    sending a partial one would silently delete every other variable — including
    #    the File Store model ids the container needs at cold start.
    deployments = _request("GET", f"/appsail/{APPSAIL_RESOURCE_ID}/deployment?limit=1",
                           token).get("data") or []
    if not deployments:
        print("no deployment found — configuration cannot be read", file=sys.stderr)
        return 1
    config = (deployments[0].get("additional_details") or {}).get("config") or {}
    env = dict((config.get("environment") or {}).get("variables") or {})
    if not env:
        print("the deployed app reports no environment variables — refusing to write",
              file=sys.stderr)
        return 1

    missing = [k for k in ROTATE if k not in env]
    print(f"environment variables on the app: {len(env)}")
    print(f"rotating: {', '.join(k for k in ROTATE if k in env) or '(none)'}")
    if missing:
        print(f"not present, will be created: {', '.join(missing)}")

    new_values = {k: secrets.token_hex(32) for k in ROTATE}
    env.update(new_values)
    # Force the container to restart so it actually picks the new values up; an
    # environment change alone leaves the running process on the old ones.
    env["VERITAS_RESTART_NONCE"] = str(secrets.randbelow(10**9))

    if args.dry_run:
        print(f"dry run: would write {len(env)} variables "
              f"({len(ROTATE)} rotated) and update {CRON_HEADER} on both cron jobs")
        return 0

    _request("POST", f"/appsail/{APPSAIL_RESOURCE_ID}/configuration", token,
             {"environment": {"variables": env}})
    print(f"appsail configuration updated ({len(env)} variables preserved)")

    # 2. The cron jobs present the job token as a request header. They are the ONLY
    #    other holder of it, and updating the app without them is exactly the failure
    #    mode that left both jobs at success_count 0 for weeks.
    updated = 0
    for job in _request("GET", "/cron", token).get("data") or []:
        meta = job.get("job_meta") or {}
        headers = meta.get("request_headers") or meta.get("headers") or {}
        if CRON_HEADER not in headers:
            continue
        headers[CRON_HEADER] = new_values["VERITAS_JOB_TOKEN"]
        if "request_headers" in meta:
            meta["request_headers"] = headers
        else:
            meta["headers"] = headers
        job["job_meta"] = meta
        _request("PUT", f"/cron/{job['id']}", token, job)
        print(f"cron '{job.get('cron_name')}' header updated")
        updated += 1

    if updated == 0:
        print("WARNING: no cron job carried the job-token header — check them by hand",
              file=sys.stderr)
        return 1

    print("\nrotated. Verify before trusting it:")
    print("  1. /health returns 200 (the container restarted on the new values)")
    print("  2. both cron jobs' next fire increments success_count, not failure_count")
    print("  3. sign-in still issues a working token")
    return 0


if __name__ == "__main__":
    sys.exit(main())
