# frontend/CLAUDE.md

Coverage floors live in `frontend/coverage-floor.json` and may only ratchet
upward. There is no per-file escape hatch: `scripts/validate_ci_artifacts.py
coverage-suppressions` rejects `istanbul ignore file` and every range form in
`frontend/src`, because an excluded file is reported as neither covered nor
uncovered — it silently leaves the measurement.

- **Frontend tests:** Vitest + Testing Library in `src/**/__tests__/`; Playwright e2e in `frontend/tests/`.
