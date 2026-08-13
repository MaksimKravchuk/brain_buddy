#!/usr/bin/env bash
# Prove the aggregate Allure quality gate can still fail.
#
# Runs the real installed CLI with the real allurerc.mjs over two committed
# fixtures that differ in exactly one `status` field:
#
#   passing/  status "passed"  -> the gate must exit 0
#   failing/  status "failed"  -> the gate must exit non-zero
#
# Because the fixtures are otherwise identical, a wrong verdict can only mean
# the gate stopped reacting to a failed result. See docs/allure-quality-gate.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ALLURE="frontend/node_modules/.bin/allure"
FIXTURES="scripts/fixtures/allure-quality-gate"

if [ ! -x "$ALLURE" ]; then
  echo "self-test: the Allure CLI is missing at $ALLURE; run 'cd frontend && npm ci'." >&2
  exit 1
fi

status=0
"$ALLURE" quality-gate "$FIXTURES/passing" --config allurerc.mjs || status=$?
if [ "$status" -ne 0 ]; then
  echo "self-test: THE GATE IS BROKEN - a wholly passing aggregate returned $status," >&2
  echo "self-test: so every verdict this run publishes is untrustworthy." >&2
  exit 1
fi

status=0
"$ALLURE" quality-gate "$FIXTURES/failing" --config allurerc.mjs || status=$?
if [ "$status" -eq 0 ]; then
  echo "self-test: THE GATE IS BROKEN - a failed result no longer fails the gate." >&2
  echo "self-test: do not treat any green run as evidence until this is fixed." >&2
  exit 1
fi

echo "self-test: passed - the gate passes a clean aggregate and fails a dirty one"
