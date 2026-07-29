#!/usr/bin/env bash
set -euo pipefail

# Authenticated production smoke check.
#
# Logs into the deployed stack through the frontend's /api proxy as the
# dedicated internal smoke user, verifies /auth/me (including that the
# server-owned SMOKE_REQUIRED_FLAG — delivery_canary by default — is
# effectively TRUE for this internal user, proving the internal rollout
# cohort is wired end-to-end), creates and deletes a uniquely named temporary
# tree, verifies the cleanup, and logs out.
#
# Credentials come only from BRAIN_BUDDY_SMOKE_EMAIL / BRAIN_BUDDY_SMOKE_PASSWORD
# (private process-env names, mapped in CI from the BRAIN_BUDDY_ADMIN_* GitHub
# secrets). This script never prints credentials, cookies, or response bodies;
# it fails closed on any missing configuration or unexpected response. If a
# check fails after the temporary tree was created, an EXIT trap best-effort
# deletes it without masking the original failure.

SMOKE_BASE_URL="${SMOKE_BASE_URL:-https://brain-buddy-frontend.fly.dev}"
SMOKE_API_PREFIX="${SMOKE_API_PREFIX:-/api}"
SMOKE_RETRY_ATTEMPTS="${SMOKE_RETRY_ATTEMPTS:-3}"
SMOKE_RETRY_DELAY_SECONDS="${SMOKE_RETRY_DELAY_SECONDS:-5}"
SMOKE_REQUIRED_FLAG="${SMOKE_REQUIRED_FLAG:-delivery_canary}"

log() { echo "[production-smoke] $1"; }
fail() {
  echo "[production-smoke] FAIL: $1" >&2
  exit 1
}

[[ -n "${BRAIN_BUDDY_SMOKE_EMAIL:-}" ]] || fail "BRAIN_BUDDY_SMOKE_EMAIL is not set"
[[ -n "${BRAIN_BUDDY_SMOKE_PASSWORD:-}" ]] || fail "BRAIN_BUDDY_SMOKE_PASSWORD is not set"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

umask 077
WORK_DIR=$(mktemp -d)
COOKIE_JAR="${WORK_DIR}/cookies"
BODY_FILE="${WORK_DIR}/body"
PAYLOAD_FILE="${WORK_DIR}/payload"
TREE_ID=""
TREE_CLEANED=0

# Best-effort cleanup on ANY exit: if the temporary tree was created but not
# yet deleted, try one DELETE so an interrupted smoke does not strand data in
# production. The original exit code is always preserved (cleanup never masks
# the real failure) and nothing here prints credentials, cookies, or bodies.
cleanup() {
  local exit_code=$?
  if [[ -n "${TREE_ID}" && "${TREE_CLEANED}" != "1" ]]; then
    local status=""
    status=$(request DELETE "/trees/${TREE_ID}" 2>/dev/null) || true
    if [[ "${status}" == "200" || "${status}" == "204" ]]; then
      log "cleanup: best-effort deletion of the temporary tree succeeded"
    else
      log "cleanup: best-effort tree deletion returned HTTP ${status:-000}; manual cleanup may be needed"
    fi
  fi
  rm -rf "${WORK_DIR}"
  exit "${exit_code}"
}
trap cleanup EXIT

# request METHOD PATH [PAYLOAD_FILE] -> prints the HTTP status; body lands in
# BODY_FILE only (never on stdout/stderr). Connection failures print 000.
request() {
  local method=$1 path=$2 payload=${3:-}
  local url="${SMOKE_BASE_URL%/}${SMOKE_API_PREFIX}${path}"
  local args=(
    --silent --show-error --output "${BODY_FILE}" --write-out '%{http_code}'
    -X "${method}" -H 'Content-Type: application/json'
    -b "${COOKIE_JAR}" -c "${COOKIE_JAR}"
  )
  if [[ -n "${payload}" ]]; then
    args+=(--data-binary "@${payload}")
  fi
  curl "${args[@]}" "${url}" 2>/dev/null || true
}

# Credentials travel via the environment into a 0600 temp payload file so they
# never appear in argv or logs.
python3 - >"${PAYLOAD_FILE}" <<'PY'
import json
import os

print(
    json.dumps(
        {
            "email": os.environ["BRAIN_BUDDY_SMOKE_EMAIL"],
            "password": os.environ["BRAIN_BUDDY_SMOKE_PASSWORD"],
        }
    )
)
PY

log "logging in as the smoke user..."
attempt=1
status="000"
while (( attempt <= SMOKE_RETRY_ATTEMPTS )); do
  status=$(request POST "/auth/login" "${PAYLOAD_FILE}")
  if [[ "${status}" == "200" || "${status}" == "401" || "${status}" == "422" ]]; then
    break
  fi
  attempt=$((attempt + 1))
  if (( attempt <= SMOKE_RETRY_ATTEMPTS )); then
    log "login attempt returned HTTP ${status}; retrying..."
    sleep "${SMOKE_RETRY_DELAY_SECONDS}"
  fi
done
rm -f "${PAYLOAD_FILE}"
[[ "${status}" == "200" ]] || fail "login returned HTTP ${status}"
log "login OK"

log "verifying /auth/me and feature-flag payload..."
status=$(request GET "/auth/me")
[[ "${status}" == "200" ]] || fail "/auth/me returned HTTP ${status}"
SMOKE_REQUIRED_FLAG="${SMOKE_REQUIRED_FLAG}" python3 - "${BODY_FILE}" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    body = json.load(handle)

expected = os.environ["BRAIN_BUDDY_SMOKE_EMAIL"].strip().lower()
if str(body.get("email", "")).lower() != expected:
    sys.exit("/auth/me returned a different account than the smoke user")

flags = body.get("feature_flags")
if not isinstance(flags, dict):
    sys.exit("/auth/me payload is missing the feature_flags object")
if any(not isinstance(value, bool) for value in flags.values()):
    sys.exit("feature_flags must contain only effective booleans")

required = os.environ["SMOKE_REQUIRED_FLAG"]
if flags.get(required) is not True:
    sys.exit(
        f"feature flag {required!r} is not effectively TRUE for the smoke "
        "user; the internal rollout cohort is not wired end-to-end"
    )
PY
log "/auth/me OK (${SMOKE_REQUIRED_FLAG} effectively true for the smoke user)"

TREE_NAME="smoke-trunk-$(date +%s)-$$-${RANDOM}"
log "creating temporary tree..."
TREE_NAME="${TREE_NAME}" python3 - >"${PAYLOAD_FILE}" <<'PY'
import json
import os

print(json.dumps({"name": os.environ["TREE_NAME"]}))
PY
status=$(request POST "/trees" "${PAYLOAD_FILE}")
rm -f "${PAYLOAD_FILE}"
[[ "${status}" == "200" || "${status}" == "201" ]] \
  || fail "tree creation returned HTTP ${status}"
TREE_ID=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["id"])' \
  "${BODY_FILE}")
[[ -n "${TREE_ID}" ]] || fail "tree creation response did not include an id"
log "temporary tree created"

status=$(request GET "/trees/${TREE_ID}")
[[ "${status}" == "200" ]] || fail "created tree is not readable (HTTP ${status})"

log "deleting temporary tree..."
status=$(request DELETE "/trees/${TREE_ID}")
[[ "${status}" == "200" || "${status}" == "204" ]] \
  || fail "tree deletion returned HTTP ${status}"

status=$(request GET "/trees/${TREE_ID}")
[[ "${status}" == "404" ]] \
  || fail "cleanup verification failed: deleted tree still answered HTTP ${status}"
# Cleanup is proven only by the 404 read-back above. Marking earlier would
# stop the EXIT trap from retrying the DELETE when an accepted deletion did
# not actually remove the tree.
TREE_CLEANED=1
log "temporary tree deleted and cleanup verified"

log "logging out..."
status=$(request POST "/auth/logout")
[[ "${status}" == "200" || "${status}" == "204" ]] \
  || fail "logout returned HTTP ${status}"

status=$(request GET "/auth/me")
[[ "${status}" == "401" ]] \
  || fail "session still active after logout (HTTP ${status})"

log "production smoke passed"
