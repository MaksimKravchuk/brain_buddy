#!/usr/bin/env bash
set -euo pipefail

api_origin="${1:-${EXPO_PUBLIC_API_ORIGIN:-http://127.0.0.1:8000/api}}"
api_origin="${api_origin%/}"
root="$(cd "$(dirname "$0")/.." && pwd)"

curl --fail --silent --show-error "${api_origin}/openapi.json" -o "${root}/api/openapi.json"

# Mobile operation allowlist (ADR-0002 / ADR-0008): drop every operation the
# backend marks deprecated (direct proposal PATCH, /finish, /commit) before
# type generation. api/openapi.json stays the full, committed contract for
# audit/drift review; api/openapi.mobile.json is generation-only and is not
# committed.
node "${root}/scripts/filter-mobile-openapi.mjs" \
  "${root}/api/openapi.json" "${root}/api/openapi.mobile.json"

npm exec --yes --package=openapi-typescript@7.13.0 -- \
  openapi-typescript "${root}/api/openapi.mobile.json" -o "${root}/src/api/openapi.generated.ts"
