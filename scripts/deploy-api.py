#!/usr/bin/env python
"""Deploy the current commit's API to AppSail, end to end.

Runs the full relay pipeline this project has used by hand every pass, in one
command: mint a token, request a signed upload URL, write it to
`.github/relay-upload.url` and push (which triggers `relay-deploy.yml` — the
GitHub runner builds `Dockerfile.overlay` against this commit's source and
uploads the tar), then wait for that build, then finalize with the AppSail
`upsert` call, then poll until the new deployment reports success.

The `upsert` call's real shape was never written down anywhere in this repo —
every prior pass reconstructed it from scratch by trial and error against the
live API. It is NOT what the JSON-body examples in past changelog entries
imply. The actual contract, read directly out of the installed Catalyst CLI's
own source (`node_modules/zcatalyst-cli/lib/endpoints/lib/appsail.js`,
`customAppSailCallback`): a multipart/form-data PUT (not JSON), fields
`name`, `memory`, `platform=custom_runtime`, `configuration` (a JSON STRING,
not a nested object), and `local_object_key` — not `image` or `object_key`,
both of which return an opaque "Invalid input value for image" no matter what
shape is tried. `name` for get-signature and upsert is a QUERY parameter for
get-signature and a form FIELD for upsert; get-signature/upsert take no
resource-id path segment (only `/configuration` does).

Run:
    CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python scripts/deploy-api.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

import requests

PROJECT_ID = "52852000000013048"
APPSAIL_RESOURCE_ID = "52852000000204688"          # NOT the public hostname number
API_BASE = "https://api.catalyst.zoho.in/baas/v1"
RELAY_URL_FILE = ".github/relay-upload.url"


def _get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}/project/{PROJECT_ID}{path}",
        headers={"Authorization": f"Zoho-oauthtoken {token}", "ENVIRONMENT": "Development"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    token = os.getenv("CATALYST_ACCESS_TOKEN", "").strip()
    if not token:
        print("CATALYST_ACCESS_TOKEN not set "
              "(CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js))", file=sys.stderr)
        return 2

    print("requesting a fresh signed upload URL...")
    sig = _get("/appsail/get-signature?name=veritas-api", token)["data"]
    with open(RELAY_URL_FILE, "w", newline="\n") as f:
        f.write(sig["signed_url"])
    object_key = sig["object_key"]

    print("pushing to trigger relay-deploy.yml (builds Dockerfile.overlay + uploads)...")
    _run("git", "add", RELAY_URL_FILE)
    _run("git", "commit", "-m", "deploy: relay a fresh signed upload URL")
    _run("git", "push")

    branch = _run("git", "branch", "--show-current")
    time.sleep(5)
    run_id = _run("gh", "run", "list", "--workflow=relay-deploy.yml", "--branch", branch,
                  "--limit", "1", "--json", "databaseId", "-q", ".[0].databaseId")
    print(f"watching run {run_id}...")
    watch = subprocess.run(["gh", "run", "watch", run_id, "--exit-status"])
    if watch.returncode != 0:
        print("relay-deploy.yml failed — the image never uploaded. Check `gh run view "
              f"{run_id} --log-failed` before retrying.", file=sys.stderr)
        return 1

    print("finalizing with the AppSail upsert call...")
    fields = {
        "name": (None, "veritas-api"),
        "memory": (None, "2048"),
        "platform": (None, "custom_runtime"),
        "configuration": (None, json.dumps({"port": 8000})),
        "local_object_key": (None, object_key),
    }
    r = requests.put(
        f"{API_BASE}/project/{PROJECT_ID}/appsail/upsert",
        headers={"Authorization": f"Zoho-oauthtoken {token}", "ENVIRONMENT": "Development"},
        files=fields, timeout=180)
    if r.status_code != 200:
        print(f"upsert returned {r.status_code}: {r.text[:300]}", file=sys.stderr)
        return 1
    # Never print the response body — it echoes the full environment, secrets included.

    print("polling deployment status...")
    for i in range(20):
        d = (_get(f"/appsail/{APPSAIL_RESOURCE_ID}/deployment?limit=1", token).get("data")
            or [{}])[0]
        status = d.get("deployment_status")
        print(f"  [{i}] deployment_id={d.get('deployment_id')} status={status}")
        if status == "success":
            print("deployed. Verify live before trusting it — /health and a real /chat turn.")
            return 0
        if status in ("failed", "failure"):
            print("deployment failed on the platform side.", file=sys.stderr)
            return 1
        time.sleep(15)
    print("gave up polling after 5 minutes — check the console.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
