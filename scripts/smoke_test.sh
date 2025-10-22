#!/usr/bin/env bash
set -euo pipefail

# Minimal smoke test that hits the compose stack endpoints.

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api}"
API_KEY="${BRAIN_BUDDY_API_KEY:-}"
API_KEY_HEADER="${BRAIN_BUDDY_API_KEY_HEADER:-X-API-Key}"

if command -v jq >/dev/null 2>&1; then
  HAS_JQ=1
else
  HAS_JQ=0
fi

function pretty_print() {
  if [[ "${HAS_JQ}" -eq 1 ]]; then
    jq .
  else
    cat
  fi
}

function request() {
  local method=$1
  local path=$2
  local body=${3:-}
  local url="${API_BASE_URL%/}${API_PREFIX}${path}"
  local headers=(-H "Content-Type: application/json")

  if [[ -n "${API_KEY}" ]]; then
    headers+=(-H "${API_KEY_HEADER}: ${API_KEY}")
  fi

  if [[ -n "${body}" ]]; then
    curl -fsS -X "${method}" "${headers[@]}" -d "${body}" "${url}"
  else
    curl -fsS -X "${method}" "${headers[@]}" "${url}"
  fi
}

echo "[smoke] Checking backend health..."
curl -fsS "${API_BASE_URL}/health" | pretty_print

echo "[smoke] Listing trees (should be empty on first run)..."
request GET "/trees" | pretty_print

echo "[smoke] Creating temporary tree..."
create_payload='{"title":"Smoke Test Tree","description":"Created by smoke_test.sh"}'
tree_response=$(request POST "/trees" "${create_payload}")
echo "${tree_response}" | pretty_print

tree_id=$(
  TREE_RESPONSE="${tree_response}" python - <<'PY'
import json
import os

payload = json.loads(os.environ["TREE_RESPONSE"])
print(payload["id"])
PY
)

echo "[smoke] Deleting temporary tree ${tree_id}..."
request DELETE "/trees/${tree_id}"

echo "[smoke] Confirming tree list is empty..."
request GET "/trees" | pretty_print

echo "[smoke] Backend smoke test complete."
