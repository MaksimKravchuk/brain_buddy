#!/usr/bin/env bash
set -euo pipefail

# Submit the current HEAD as a verified-trunk landing candidate.
#
# Validates a clean working tree, a current origin/main base, and exactly one
# candidate commit, runs fast local checks, then pushes the exact candidate
# SHA to a unique trunk-candidate/<sha> ref. Full CI runs on that ref; the
# default-branch release workflow (deploy-fly-production.yml) consumes the
# completed run and its land job fast-forwards main only after every
# required job succeeds. Candidate-controlled CI itself can never promote.
#
# This script never pushes to main and never force-pushes anything.
# SUBMIT_TRUNK_SKIP_CHECKS=1 skips the fast local checks (offline contract
# tests and emergencies only — CI remains the authoritative gate). The
# Ship/Show/Ask path classification below is NOT skippable: ASK-class
# changes require a reviewed PR or an explicitly authorized manual
# high-risk landing (ADR-0008), never automatic trunk promotion.

# Resolved before any cd so the classifier is taken from this script's own
# checkout, not from whatever repository the candidate lives in.
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

log() { echo "[submit-to-trunk] $1"; }
fail() {
  echo "[submit-to-trunk] FAIL: $1" >&2
  exit 1
}

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "not inside a git repository"

repo_root=$(git rev-parse --show-toplevel)
cd "${repo_root}"

if [[ -n "$(git status --porcelain)" ]]; then
  fail "working tree is not clean; commit or stash everything first"
fi

log "fetching origin/main..."
git fetch --quiet origin main

head_sha=$(git rev-parse HEAD)
main_sha=$(git rev-parse origin/main)

if [[ "${head_sha}" == "${main_sha}" ]]; then
  fail "HEAD equals origin/main; there is no candidate commit to submit"
fi

parents=$(git rev-list --parents -n 1 "${head_sha}" | wc -w)
if [[ "${parents}" -ne 2 ]]; then
  fail "candidate must be a single non-merge commit (squash the series first)"
fi

parent_sha=$(git rev-parse "${head_sha}^")
if [[ "${parent_sha}" != "${main_sha}" ]]; then
  fail "candidate must contain exactly one commit whose parent is the current \
origin/main (${main_sha}); rebase/squash onto origin/main and retry"
fi

# Mechanical Ship/Show/Ask enforcement (ADR-0008), never skippable.
command -v python3 >/dev/null 2>&1 || fail "python3 is required to classify candidate risk"
classifier="${script_dir}/classify_path_risk.py"
[[ -f "${classifier}" ]] || fail "missing risk classifier ${classifier}"
log "classifying changed paths (Ship/Show/Ask)..."
# NUL-separated with --no-renames: git never quotes -z output, so non-ASCII
# paths classify on their real names, and a rename away from an ASK path
# still surfaces as its deletion. The same form runs in the trusted landing
# gate of the default-branch release workflow.
if ! git diff --no-renames --name-only -z "${main_sha}" "${head_sha}" \
  | python3 "${classifier}" --null; then
  fail "candidate touches ASK-class paths; ASK changes require a reviewed PR or \
an explicitly authorized manual high-risk landing (ADR-0008)"
fi

if [[ "${SUBMIT_TRUNK_SKIP_CHECKS:-0}" == "1" ]]; then
  log "WARNING: fast local checks skipped (SUBMIT_TRUNK_SKIP_CHECKS=1); CI is still authoritative"
else
  log "running fast local checks..."
  if [[ -f scripts/check_spec_kit_specs.py ]]; then
    python3 scripts/check_spec_kit_specs.py
  fi
  if [[ -d backend ]] && command -v ruff >/dev/null 2>&1; then
    (cd backend && ruff check app tests)
  fi
  if command -v actionlint >/dev/null 2>&1; then
    actionlint
  fi
fi

candidate_branch="trunk-candidate/${head_sha}"
log "pushing candidate ${candidate_branch}..."
git push origin "${head_sha}:refs/heads/${candidate_branch}"

log "candidate submitted: ${candidate_branch} (${head_sha})"

origin_url=$(git remote get-url origin)
repo_slug=$(printf '%s\n' "${origin_url}" \
  | sed -E 's#^git@github\.com:##; s#^https://github\.com/##; s#\.git$##')
if [[ "${repo_slug}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  encoded_branch="trunk-candidate%2F${head_sha}"
  log "watch CI: https://github.com/${repo_slug}/actions?query=branch%3A${encoded_branch}"
else
  log "origin is not a github.com remote; check your CI dashboard for ${candidate_branch}"
fi
