#!/usr/bin/env bash
set -euo pipefail

# Minimal smoke test for the compose stack.
# Signs up a throwaway user via a freshly-minted invite, exercises the
# tree endpoints, then deletes the tree. Uses a cookie jar to carry the
# session across requests.

API_BASE_URL="${API_BASE_URL:-http://localhost:${BRAIN_BUDDY_PORT:-8000}}"
API_PREFIX="${API_PREFIX:-${BRAIN_BUDDY_API_PREFIX:-/api}}"
COOKIE_JAR=$(mktemp)
trap 'rm -f "${COOKIE_JAR}"' EXIT

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

  if [[ -n "${body}" ]]; then
    curl -fsS -X "${method}" "${headers[@]}" \
      -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" \
      -d "${body}" "${url}"
  else
    curl -fsS -X "${method}" "${headers[@]}" \
      -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" \
      "${url}"
  fi
}

echo "[smoke] Checking backend health..."
curl -fsS "${API_BASE_URL}/health" | pretty_print

echo "[smoke] Minting invite code via CLI..."
INVITE_CODE=$(docker compose exec -T backend python -m app.cli create-invite | tr -d '\r\n')
if [[ -z "${INVITE_CODE}" ]]; then
  echo "[smoke] Failed to mint invite" >&2
  exit 1
fi

echo "[smoke] Signing up smoke-test user..."
EMAIL="smoke+$(date +%s)@example.com"
PASSWORD="smoke-test-password-12chars"
signup_payload=$(printf '{"email":"%s","password":"%s","invite_code":"%s"}' \
  "${EMAIL}" "${PASSWORD}" "${INVITE_CODE}")
request POST "/auth/signup" "${signup_payload}" | pretty_print

echo "[smoke] Listing trees (should be empty on first run)..."
request GET "/trees" | pretty_print

echo "[smoke] Creating temporary tree..."
tree_response=$(request POST "/trees" '{"name":"Smoke Test Tree"}')
echo "${tree_response}" | pretty_print

tree_id=$(
  TREE_RESPONSE="${tree_response}" python3 - <<'PY'
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

echo "[smoke] Logging out..."
request POST "/auth/logout"

echo "[smoke] Backend smoke test complete."
