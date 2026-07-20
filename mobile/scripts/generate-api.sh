#!/usr/bin/env bash
set -euo pipefail

api_origin="${1:-${EXPO_PUBLIC_API_ORIGIN:-http://127.0.0.1:8000/api}}"
api_origin="${api_origin%/}"
root="$(cd "$(dirname "$0")/.." && pwd)"

curl --fail --silent --show-error "${api_origin}/openapi.json" -o "${root}/api/openapi.json"
npm exec --yes --package=openapi-typescript@7.13.0 -- \
  openapi-typescript "${root}/api/openapi.json" -o "${root}/src/api/openapi.generated.ts"
