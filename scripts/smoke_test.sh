#!/usr/bin/env bash
set -euo pipefail

# Minimal smoke test for the compose stack.
# Signs up a throwaway user via a freshly-minted invite, exercises the
# tree endpoints, then deletes the tree, and exercises the task-tracker
# endpoints (tasks, projects, tags). Uses a cookie jar to carry the
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
  local idempotency_key=${4:-}
  local url="${API_BASE_URL%/}${API_PREFIX}${path}"
  local headers=(-H "Content-Type: application/json")

  if [[ -n "${idempotency_key}" ]]; then
    headers+=(-H "Idempotency-Key: ${idempotency_key}")
  fi

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
# NOTE: must be a real-looking domain; email-validator >= 2.0 rejects
# special-use TLDs such as .test.
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

echo "[smoke] Listing inbox tasks (should be empty on first run)..."
request GET "/tasks?state=inbox" | pretty_print

echo "[smoke] Creating temporary task..."
task_response=$(request POST "/tasks" '{"title":"Smoke Test Task"}' \
  "smoke-create-task-$(date +%s)")
echo "${task_response}" | pretty_print

task_id=$(
  TASK_RESPONSE="${task_response}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["TASK_RESPONSE"])
print(payload["id"])
PY
)

task_revision=$(
  TASK_RESPONSE="${task_response}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["TASK_RESPONSE"])
print(payload["revision"])
PY
)

echo "[smoke] Fetching task ${task_id}..."
request GET "/tasks/${task_id}" | pretty_print

echo "[smoke] Completing task ${task_id}..."
transition_payload=$(printf '{"action":"complete","expected_revision":%s}' \
  "${task_revision}")
request POST "/tasks/${task_id}/transitions" "${transition_payload}" \
  "smoke-complete-task-$(date +%s)" | pretty_print

echo "[smoke] Listing projects..."
request GET "/projects" | pretty_print

echo "[smoke] Listing tags..."
request GET "/tags" | pretty_print

echo "[smoke] Logging out..."
request POST "/auth/logout"

echo "[smoke] Backend smoke test complete."
