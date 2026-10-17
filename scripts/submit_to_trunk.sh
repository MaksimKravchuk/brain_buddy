#!/usr/bin/env bash
set -euo pipefail

# RETIRED by ADR-0035 (docs/decisions/0035-merge-queue-pr-landing.md).
#
# This script used to push one candidate commit to a trunk-candidate/<sha>
# ref, and the release workflow's land job fast-forwarded main with a deploy
# key (ADR-0008). The main ruleset no longer lets that key update main, so a
# candidate could pass CI and still never land. Every change, SHIP, SHOW or
# ASK, now lands as a pull request through the merge queue behind Full CI and
# Docker Images; ASK additionally needs recorded owner approval on the PR.
#
# The file is kept so existing references fail loudly instead of silently.
# It runs no git command and pushes nothing.

cat >&2 <<'EOF'
[submit-to-trunk] FAIL: PR-less trunk-candidate landing is retired (ADR-0035).
[submit-to-trunk] Nothing was pushed. Land every change (SHIP, SHOW or ASK) as a
[submit-to-trunk] pull request against main through the merge queue instead:
[submit-to-trunk]   1. push your branch and open a PR against main;
[submit-to-trunk]   2. wait for Full CI and Docker Images on the PR head and resolve
[submit-to-trunk]      every review thread (ASK also needs recorded owner approval
[submit-to-trunk]      on the PR for the exact head SHA);
[submit-to-trunk]   3. add the PR to the merge queue.
[submit-to-trunk] See docs/decisions/0035-merge-queue-pr-landing.md and
[submit-to-trunk] docs/autonomous-delivery-runbook.md (Merge-queue landing).
EOF
exit 1
