#!/usr/bin/env bash
# Fly cutover / rollback / erase between the Python and Rust backends (027 R10).
#
# Usage: fly_cutover.sh cutover|rollback|erase
#
# Writer authority moves one way at a time: the running side is stopped and
# VERIFIED stopped (`flyctl machines list`) before the other side starts.
# Evidence lines carry identifiers and timestamps only, never secrets or data.
#
# Environment (all optional unless noted):
#   FLYCTL            flyctl binary (default: flyctl)
#   OLD_APP           default brain-buddy-backend
#   NEW_APP           default brain-buddy-api
#   FRONTEND_APP      default brain-buddy-frontend
#   NEW_CONFIG        default fly.api.toml
#   FRONTEND_CONFIG   default fly.frontend.toml
#   FORK_VOLUMES      extra "app:volume-id" forks/copies to destroy (space separated)
#   OFFPLATFORM_COPIES  operator-named off-platform copies (comma separated)
#   OFFPLATFORM_CONFIRMED  must be 1 when copies are listed (operator removed them)
#   SMOKE_CMD         command run as the production smoke (required for cutover)
#   ERASE_OLD         1 = erase after a successful cutover smoke
#   EVIDENCE_FILE     append evidence lines here (default: stdout only)
#   VERIFY_ATTEMPTS / VERIFY_SLEEP   stop-verification polling (default 10 / 3)
set -euo pipefail

FLYCTL="${FLYCTL:-flyctl}"
OLD_APP="${OLD_APP:-brain-buddy-backend}"
NEW_APP="${NEW_APP:-brain-buddy-api}"
FRONTEND_APP="${FRONTEND_APP:-brain-buddy-frontend}"
NEW_CONFIG="${NEW_CONFIG:-fly.api.toml}"
FRONTEND_CONFIG="${FRONTEND_CONFIG:-fly.frontend.toml}"
FORK_VOLUMES="${FORK_VOLUMES:-}"
OFFPLATFORM_COPIES="${OFFPLATFORM_COPIES:-}"
OFFPLATFORM_CONFIRMED="${OFFPLATFORM_CONFIRMED:-0}"
ERASE_OLD="${ERASE_OLD:-0}"
VERIFY_ATTEMPTS="${VERIFY_ATTEMPTS:-10}"
VERIFY_SLEEP="${VERIFY_SLEEP:-3}"

evidence() {
  local line
  line="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  echo "EVIDENCE $line"
  if [ -n "${EVIDENCE_FILE:-}" ]; then echo "$line" >>"$EVIDENCE_FILE"; fi
}

die() {
  echo "fly_cutover: $*" >&2
  exit 1
}

# Count machines in a running-ish state for an app.
running_count() {
  "$FLYCTL" machines list -a "$1" --json | python3 -c '
import json, sys
live = {"started", "starting", "replacing", "created"}
print(sum(1 for m in json.load(sys.stdin) if str(m.get("state", "")).lower() in live))
'
}

verify_stopped() {
  local app="$1" n i
  for ((i = 0; i < VERIFY_ATTEMPTS; i++)); do
    n="$(running_count "$app")"
    if [ "$n" = "0" ]; then
      evidence "verified-stopped app=$app"
      return 0
    fi
    sleep "$VERIFY_SLEEP"
  done
  die "$app still has running machines; refusing to start the other side"
}

verify_running() {
  local app="$1" n i
  for ((i = 0; i < VERIFY_ATTEMPTS; i++)); do
    n="$(running_count "$app")"
    if [ "$n" != "0" ]; then
      evidence "verified-running app=$app machines=$n"
      return 0
    fi
    sleep "$VERIFY_SLEEP"
  done
  die "$app has no running machines after start"
}

stop_app() {
  evidence "stop app=$1"
  "$FLYCTL" scale count 0 -a "$1" --yes
  verify_stopped "$1"
}

point_frontend() {
  local origin="https://$1.fly.dev"
  evidence "frontend-origin app=$FRONTEND_APP origin=$origin"
  "$FLYCTL" deploy -c "$FRONTEND_CONFIG" -a "$FRONTEND_APP" \
    --env "BACKEND_ORIGIN=$origin" --yes
}

do_rollback() {
  evidence "rollback-begin"
  stop_app "$NEW_APP"
  point_frontend "$OLD_APP"
  evidence "start app=$OLD_APP"
  "$FLYCTL" scale count 1 -a "$OLD_APP" --yes
  verify_running "$OLD_APP"
  evidence "rollback-done"
}

do_erase() {
  local ids="" id snap spec item
  if [ -n "$OFFPLATFORM_COPIES" ] && [ "$OFFPLATFORM_CONFIRMED" != "1" ]; then
    die "off-platform copies listed ($OFFPLATFORM_COPIES); remove them and set OFFPLATFORM_CONFIRMED=1"
  fi
  evidence "erase-begin"
  # The old app must not be writable while its data is destroyed.
  stop_app "$OLD_APP"

  # Every volume of the old app: the data volume and any in-app fork.
  local vols
  vols="$("$FLYCTL" volumes list -a "$OLD_APP" --json | python3 -c '
import json, sys
for v in json.load(sys.stdin):
    print(v.get("id", ""))
')"
  for id in $vols; do
    for snap in $("$FLYCTL" volumes snapshots list "$id" -a "$OLD_APP" --json | python3 -c '
import json, sys
for s in json.load(sys.stdin):
    print(s.get("id", ""))
'); do
      evidence "snapshot-destroyed-with-volume volume=$id snapshot=$snap"
    done
    evidence "destroy-volume app=$OLD_APP volume=$id"
    "$FLYCTL" volumes destroy "$id" -a "$OLD_APP" --yes
    ids="$ids $id"
  done

  for spec in $FORK_VOLUMES; do
    evidence "destroy-fork app=${spec%%:*} volume=${spec#*:}"
    "$FLYCTL" volumes destroy "${spec#*:}" -a "${spec%%:*}" --yes
  done

  evidence "destroy-app app=$OLD_APP"
  "$FLYCTL" apps destroy "$OLD_APP" --yes

  local leftover
  leftover="$("$FLYCTL" apps list --json | python3 -c '
import json, sys
app = sys.argv[1]
print(sum(1 for a in json.load(sys.stdin) if a.get("Name", a.get("name")) == app))
' "$OLD_APP")"
  [ "$leftover" = "0" ] || die "$OLD_APP still listed after destroy"

  if [ -n "$OFFPLATFORM_COPIES" ]; then
    local -a items
    IFS=',' read -ra items <<<"$OFFPLATFORM_COPIES"
    for item in "${items[@]}"; do evidence "offplatform-copy-confirmed-removed name=$item"; done
  fi
  evidence "final-listing app=$OLD_APP remaining=0 destroyed-volumes=${ids:-none}"
  evidence "erase-done"
}

do_cutover() {
  [ -n "${SMOKE_CMD:-}" ] || die "SMOKE_CMD is required for cutover"
  evidence "cutover-begin"
  stop_app "$OLD_APP"
  evidence "deploy app=$NEW_APP"
  "$FLYCTL" deploy -c "$NEW_CONFIG" -a "$NEW_APP" --yes
  "$FLYCTL" scale count serve=1 worker=1 -a "$NEW_APP" --yes
  verify_running "$NEW_APP"
  point_frontend "$NEW_APP"
  evidence "smoke-begin"
  if bash -c "$SMOKE_CMD"; then
    evidence "smoke-passed"
  else
    evidence "smoke-failed"
    do_rollback
    die "smoke failed; rolled back to $OLD_APP; set target = \"python\" in a follow-up commit"
  fi
  if [ "$ERASE_OLD" = "1" ]; then do_erase; fi
  evidence "cutover-done"
}

case "${1:-}" in
  cutover) do_cutover ;;
  rollback) do_rollback ;;
  erase) do_erase ;;
  *) die "usage: $0 cutover|rollback|erase" ;;
esac
