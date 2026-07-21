#!/usr/bin/env bash
set -euo pipefail

# Deterministic, ephemeral contract generation: build the FastAPI app
# in-process against a throwaway test-mode data directory and read
# app.openapi() directly. This never targets a live server, Fly, production,
# or any arbitrary URL, and never requires the backend dev server to be
# running. See backend/scripts/openapi_snapshot.py and
# docs/api-compatibility.md.

root="$(cd "$(dirname "$0")/.." && pwd)"
backend_dir="${root}/../backend"

(
  cd "${backend_dir}"
  if [ -f .venv/bin/activate ]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
  fi
  python -m scripts.openapi_snapshot dump --out "${root}/api/openapi.json"
)

# openapi-typescript is a pinned devDependency (see package.json /
# package-lock.json) so this never reaches the network at generation time —
# `--no-install` fails loudly instead of silently falling back to a registry
# fetch if `npm ci` was skipped.
npx --no-install openapi-typescript "${root}/api/openapi.json" -o "${root}/src/api/openapi.generated.ts"
