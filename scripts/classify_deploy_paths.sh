#!/usr/bin/env bash
# Classify a NUL-separated changed-path listing for the production deploy gate.
# Keep this classifier free of git/network access so the workflow can provide the
# exact tested revision and tests can exercise the same behavior deterministically.
set -euo pipefail

needed=false
seen=false
while IFS= read -r -d '' path; do
  seen=true
  case "${path}" in
    backend/*|frontend/*|fly.*|docker-compose*|Dockerfile*|compose.y*ml|.dockerignore|.env)
      needed=true
      echo "Deploy-relevant change: ${path}" >&2
      ;;
    .github/*|.specify/*|.claude/*|.design-sync/*|docs/*|specs/*|mobile/*|scripts/*|*.md|Makefile|.gitignore|LICENSE|.env.example)
      ;;
    *)
      needed=true
      echo "Unclassified change (deploying to stay safe): ${path}" >&2
      ;;
  esac
done
if [ "${seen}" = "false" ]; then
  echo "Empty change listing; deploying (fail-open)." >&2
  needed=true
fi
if [ "${needed}" = "false" ]; then
  echo "Every changed path is deploy-inert; skipping the production release." >&2
fi
echo "needed=${needed}"
