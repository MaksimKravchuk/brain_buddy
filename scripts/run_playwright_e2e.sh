#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="${BRAIN_BUDDY_E2E_PROJECT:-brainbuddy-e2e-${GITHUB_RUN_ID:-local}-$(date +%s)-$$}"
BACKEND_PORT="${BRAIN_BUDDY_E2E_BACKEND_PORT:-$(python3 - <<'PY'
import socket
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
PY
)}"
FRONTEND_PORT="${BRAIN_BUDDY_E2E_FRONTEND_PORT:-$(python3 - <<'PY'
import socket
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
PY
)}"

# Compose starts exactly these tags (see compose.yaml). Defaulting them per
# project keeps concurrent local runs from racing on a shared tag; CI overrides
# them with the tags it prebuilt from the cached layers of main.
export BRAIN_BUDDY_BACKEND_IMAGE="${BRAIN_BUDDY_BACKEND_IMAGE:-brain-buddy-backend:${PROJECT_NAME}}"
export BRAIN_BUDDY_FRONTEND_IMAGE="${BRAIN_BUDDY_FRONTEND_IMAGE:-brain-buddy-frontend:${PROJECT_NAME}}"

# Building here is the default so a bare run from a clean checkout still works.
# CI sets 0 because it already built both images with a shared layer cache;
# --no-build then fails closed when a tag is missing rather than quietly
# building an unpinned replacement and testing something nobody pinned.
if [[ "${BRAIN_BUDDY_E2E_BUILD_IMAGES:-1}" == "1" ]]; then
  COMPOSE_BUILD_MODE="--build"
else
  COMPOSE_BUILD_MODE="--no-build"
fi

BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"
COMPOSE_LOG_DIR="${ROOT_DIR}/frontend/test-results/compose"
PLAYWRIGHT_ALLURE_DIR="${ROOT_DIR}/frontend/allure-results/playwright"
PLAYWRIGHT_REPORT_DIR="${ROOT_DIR}/frontend/playwright-report"

rm -rf "${PLAYWRIGHT_ALLURE_DIR}" "${PLAYWRIGHT_REPORT_DIR}"
mkdir -p "${COMPOSE_LOG_DIR}" "${PLAYWRIGHT_ALLURE_DIR}" "${PLAYWRIGHT_REPORT_DIR}"
touch "${PLAYWRIGHT_ALLURE_DIR}/.run-started-at"

cleanup() {
  local status=$?
  echo "[e2e] Capturing Compose logs for ${PROJECT_NAME}..."
  COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose logs --no-color > "${COMPOSE_LOG_DIR}/docker-compose.log" 2>&1 || true
  echo "[e2e] Tearing down Compose project ${PROJECT_NAME}..."
  COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  exit "${status}"
}
trap cleanup EXIT

cd "${ROOT_DIR}"

echo "[e2e] Starting isolated Compose project ${PROJECT_NAME}"
echo "[e2e] Backend: ${BACKEND_URL} (${BRAIN_BUDDY_BACKEND_IMAGE})"
echo "[e2e] Frontend: ${FRONTEND_URL} (${BRAIN_BUDDY_FRONTEND_IMAGE})"
echo "[e2e] Image mode: ${COMPOSE_BUILD_MODE}"

COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
BRAIN_BUDDY_ENV=test \
BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST=1 \
BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS=1 \
BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER=openai \
BRAIN_BUDDY_FEATURE_FLAGS=voice_brain_dump=on \
BRAIN_BUDDY_PORT="${BACKEND_PORT}" \
FRONTEND_PORT="${FRONTEND_PORT}" \
VITE_API_BASE_URL=/api \
docker compose up -d "${COMPOSE_BUILD_MODE}"

for attempt in {1..60}; do
  if curl -fsS "${BACKEND_URL}/health" >/dev/null; then
    echo "[e2e] Backend health is ready."
    break
  fi
  if [[ "${attempt}" == "60" ]]; then
    echo "[e2e] Backend did not become healthy." >&2
    exit 1
  fi
  sleep 2
done

for attempt in {1..60}; do
  if curl -fsS "${FRONTEND_URL}/login" >/dev/null; then
    echo "[e2e] Frontend nginx is ready."
    break
  fi
  if [[ "${attempt}" == "60" ]]; then
    echo "[e2e] Frontend did not become reachable." >&2
    exit 1
  fi
  sleep 2
done

echo "[e2e] Running short Compose API smoke."
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
API_BASE_URL="${BACKEND_URL}" \
BRAIN_BUDDY_PORT="${BACKEND_PORT}" \
./scripts/smoke_test.sh

echo "[e2e] Running Playwright Chromium acceptance journeys."
cd "${ROOT_DIR}/frontend"
BRAIN_BUDDY_E2E_COMPOSE_PROJECT="${PROJECT_NAME}" \
BRAIN_BUDDY_E2E_BACKEND_URL="${BACKEND_URL}" \
PLAYWRIGHT_BASE_URL="${FRONTEND_URL}" \
npx playwright test --config playwright.config.ts "$@"
