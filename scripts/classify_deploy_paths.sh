#!/usr/bin/env bash
# Classify a NUL-separated changed-path listing for the production deploy gate.
# Keep this classifier free of git/network access so the workflow can provide the
# exact tested revision and tests can exercise the same behavior deterministically.
#
# Prints backend=, frontend= and needed= (either app) for GITHUB_OUTPUT. The
# rules live in scripts/release_graph.py, the one component -> release graph
# shared with the TestFlight upload: unknown paths and an empty listing deploy
# both apps (fail-open).
set -euo pipefail

exec python3 "$(dirname "$0")/release_graph.py" fly
