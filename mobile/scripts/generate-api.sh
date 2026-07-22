#!/usr/bin/env bash
set -euo pipefail

# Deterministic, ephemeral contract generation: build the FastAPI app
# in-process against a throwaway test-mode data directory and read
# app.openapi() directly. This never targets a live server, Fly, production,
# or any arbitrary URL, and never requires the backend dev server to be
# running. See backend/scripts/openapi_snapshot.py and
# docs/api-compatibility.md.
#
# For byte/semantically reproducible output, run `uv sync --locked --extra
# dev` in backend/ first; this activates the resulting backend/.venv
# automatically if present, matching the locked FastAPI/Pydantic versions the
# committed snapshot was generated against instead of whatever an unlocked
# `pip install` happens to resolve.

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

# The committed snapshot (api/openapi.json) stays the full backend contract —
# it is the drift-check source of truth (see openapi_snapshot.py) and may
# legitimately keep describing deprecated web-compatibility aliases and
# unrelated web surface during their bounded overlap window. Generation must
# not hand that full snapshot to openapi-typescript: ADR-0008 and
# specs/004-expo-mobile-first-slice/contracts/mobile-api.md require an
# explicit mobile operation allowlist, so the client never receives typed
# signatures for operations it must not call.
filtered_openapi="$(mktemp -t brainbuddy-mobile-openapi-filtered-XXXXXX.json)"
trap 'rm -f "${filtered_openapi}"' EXIT
node "${root}/scripts/filterOpenApiAllowlist.js" "${root}/api/openapi.json" "${filtered_openapi}"

# openapi-typescript is a pinned devDependency (see package.json /
# package-lock.json) so this never reaches the network at generation time —
# `--no-install` fails loudly instead of silently falling back to a registry
# fetch if `npm ci` was skipped.
npx --no-install openapi-typescript "${filtered_openapi}" -o "${root}/src/api/generated/openapi.generated.ts"
