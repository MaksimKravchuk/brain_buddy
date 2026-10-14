#!/bin/sh
# Automated rehearsal of the Apple pilot on the iOS Simulator (spec 026, evidence "S4 iOS Simulator
# UI"). XCUITest against a LOCAL backend only: never point it at a deployed server. The results are
# rehearsal evidence, not reference-device evidence.
#
#   BB_BACKEND_PYTHON=/path/to/venv/bin/python sh scripts/rehearsal/run_ios_ui.sh ["iPhone 17"]
#
# Needs: Xcode 26, XcodeGen, the Rust bridge for the simulator (arm64 is enough):
#   BB_APPLE_TARGETS=aarch64-apple-ios-sim sh ios/scripts/build-rust-bridge.sh apple
# and an interpreter with the backend's dependencies and `bb_core` (python 3.14).
#
# Environment: BB_REHEARSAL_PORT (default 18700; the proxy listens there, the server on +1 and the
# control endpoint on +2), BB_REHEARSAL_OUT (default .rehearsal-build/out: results.tsv, screens/,
# the backend's data and log), BB_REHEARSAL_DERIVED (DerivedData, default .rehearsal-build/dd).
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SIM="${1:-iPhone 17}"
PORT="${BB_REHEARSAL_PORT:-18700}"
OUT="${BB_REHEARSAL_OUT:-$ROOT/.rehearsal-build/out}"
DERIVED="${BB_REHEARSAL_DERIVED:-$ROOT/.rehearsal-build/dd}"
PYTHON="${BB_BACKEND_PYTHON:?set BB_BACKEND_PYTHON to an interpreter with the backend dependencies and bb_core}"
BUNDLE_ID="${BB_BUNDLE_ID_PREFIX:-brainbuddy}.ios"

rm -rf "$OUT"
mkdir -p "$OUT/data" "$OUT/screens"

# A fresh server on every run: the accounts and flags are created by the script.
(cd "$ROOT/backend" && exec "$PYTHON" "$ROOT/scripts/rehearsal/ui_backend.py" "$OUT/data" "$PORT") \
  >"$OUT/backend.log" 2>&1 &
BACKEND=$!
trap 'kill "$BACKEND" 2>/dev/null || true' EXIT INT TERM
i=0
until curl -s "http://localhost:$((PORT + 2))/state" >/dev/null 2>&1; do
  i=$((i + 1))
  [ "$i" -lt 60 ] || { echo "backend did not start; see $OUT/backend.log" >&2; exit 1; }
  kill -0 "$BACKEND" 2>/dev/null || { echo "backend exited; see $OUT/backend.log" >&2; exit 1; }
  sleep 1
done

(cd "$ROOT/ios" && xcodegen generate >/dev/null)
xcrun simctl boot "$SIM" 2>/dev/null || true

export TEST_RUNNER_BB_REHEARSAL_API="http://localhost:$PORT/api"
export TEST_RUNNER_BB_REHEARSAL_DIRECT="http://localhost:$((PORT + 1))/api"
export TEST_RUNNER_BB_REHEARSAL_CONTROL="http://localhost:$((PORT + 2))"
export TEST_RUNNER_BB_REHEARSAL_SCREENS="$OUT/screens"
export TEST_RUNNER_BB_REHEARSAL_RESULTS="$OUT/results.tsv"

run() {
  # Ad-hoc signing: a simulator build needs no team, but the App Group entitlement must be embedded.
  xcodebuild test -project "$ROOT/ios/BrainBuddy.xcodeproj" -scheme BrainBuddyRehearsal \
    -destination "platform=iOS Simulator,name=$SIM" -derivedDataPath "$DERIVED" \
    CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY=- ARCHS=arm64 ONLY_ACTIVE_ARCH=YES "$@" \
    >>"$OUT/xcodebuild.log" 2>&1
}

status=0
# Phase 1, fresh install: the pilot switch before any account (the one-way move).
xcrun simctl uninstall "$SIM" "$BUNDLE_ID" 2>/dev/null || true
if [ -z "${BB_REHEARSAL_PHASE2:-}" ]; then
  run -only-testing:BrainBuddyUITests/PilotFirstRehearsalTests || status=1
fi
# Phase 2, fresh install again: legacy sign-in, then the switch, sync status, conflicts and review.
xcrun simctl uninstall "$SIM" "$BUNDLE_ID" 2>/dev/null || true
# BB_REHEARSAL_PHASE2 narrows phase 2 while debugging a test: a list of -only-testing: arguments.
# shellcheck disable=SC2086
run ${BB_REHEARSAL_PHASE2:--only-testing:BrainBuddyUITests/PilotRehearsalTests -only-testing:BrainBuddyUITests/ReviewRehearsalTests -only-testing:BrainBuddyUITests/SessionRehearsalTests} || status=1

echo "results: $OUT/results.tsv   screenshots: $OUT/screens   xcodebuild log: $OUT/xcodebuild.log"
exit "$status"
