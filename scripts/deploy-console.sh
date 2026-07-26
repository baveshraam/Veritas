#!/usr/bin/env bash
# Build the console and deploy it to Catalyst Web Client Hosting.
#
# The export has to land in client/ WITHOUT clobbering client-package.json — that file
# is Catalyst's manifest, not part of the Next build, and losing it fails the deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/apps/web"
npm run build

cd "$ROOT"
MANIFEST="$(cat client/client-package.json)"
rm -rf client/_next client/index.html client/index.txt client/404.html
cp -r apps/web/out/. client/
printf '%s' "$MANIFEST" > client/client-package.json

# Guard the two build-time bugs that shipped a blank console before: assets must be
# /app-prefixed, and the API URL must be the deployed one, not localhost.
grep -q 'src="/app/_next/' client/index.html \
  || { echo "FAIL: assets are not /app-prefixed — check assetPrefix in next.config.mjs"; exit 1; }
! grep -rq "localhost:8000" client/_next/static/chunks/ \
  || { echo "FAIL: localhost API URL baked into the bundle"; exit 1; }

catalyst deploy --only client
