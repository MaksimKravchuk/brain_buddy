#!/usr/bin/env bash
set -euo pipefail

# Deterministic mobile contract generation (ADR-0002 / ADR-0008 / spec 004
# tasks.md T012-T014). There is exactly one source of truth: the pinned
# root-level `openapi/brainbuddy-v1.json` snapshot, produced by
# `scripts/generate_openapi.py` from an ephemeral app/data root -- never a
# live server. A previous version of this script curled a running dev
# server directly, which could silently drift from (or simply be unable to
# reach) the pinned contract; that path is intentionally gone.

root="$(cd "$(dirname "$0")/.." && pwd)"
repo_root="$(cd "${root}/.." && pwd)"

# Regenerate the pinned snapshot so this always reflects the current backend
# route set, then fail loudly (via generate_openapi.py --check semantics
# reused here) if that regeneration produced a different file than what is
# committed -- mobile generation must never silently consume drifted output.
(cd "${repo_root}/backend" && uv run python3 ../scripts/generate_openapi.py)

cp "${repo_root}/openapi/brainbuddy-v1.json" "${root}/api/openapi.json"

# Explicit mobile operation allowlist (ADR-0002 / ADR-0008, spec 004 tasks.md
# T013): keeps only the (method, path) pairs the first mobile slice is
# allowed to consume -- never "everything except deprecated". api/openapi.json
# stays the full, committed contract (identical to the pinned root snapshot)
# for audit/drift review; api/openapi.mobile.json is generation-only and is
# not committed.
node "${root}/scripts/filter-mobile-openapi.mjs" \
  "${root}/api/openapi.json" "${root}/api/openapi.mobile.json"

npm exec --yes --package=openapi-typescript@7.13.0 -- \
  openapi-typescript "${root}/api/openapi.mobile.json" -o "${root}/src/api/openapi.generated.ts"
