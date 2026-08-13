---
name: "self-verify"
description: "Canonical, key-free verification command table per surface: what to run, in what order, with the prerequisites the Makefile omits and the coverage floors that gate merge."
argument-hint: "Optional surface: backend | frontend | mobile | e2e | all"
compatibility: "Requires the repository toolchain installed"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline verification contract"
user-invocable: true
disable-model-invocation: false
---

# Self-verification

The deterministic, **free** verification chain. Nothing here costs money or
calls a paid provider. For the paid live voice drive see the `verify-live`
skill, which is approval-gated and must never be run unattended.

## Everything, in CI order

```bash
make verify-all
```

That target mirrors the CI job graph. Run it before reporting any change done.
When you need to scope down, use the per-surface tables below — but say which
surfaces you skipped and why.

"Mirrors" is a property that has to be maintained, not a promise. `test-mobile`
omitted the Allure taxonomy validator that CI runs, so a locally-green agent
could still fail CI on `mobile-jest`. When you add a validator to a CI job, add
it to the matching make target in the same change.

## Prerequisites the Makefile does not install

These are the two failures most often misdiagnosed as broken code:

```bash
make install-backend                      # required before make integration-mobile
cd frontend && npx playwright install --with-deps chromium   # required before make test-e2e
```

`make integration-mobile` boots its own disposable backend and needs the
backend package importable. `make test-e2e` needs a real browser.

## Backend

```bash
make lint-backend      # ruff check app tests; black --check app tests; mypy app
make test-backend      # pytest + coverage + allure taxonomy
make ci-backend        # both, in CI order
```

Floors live in `backend/coverage-floor.json` and are enforced by
`scripts/validate_coverage_floor.py`, which also refuses a floor lower than the
base branch's — the floor ratchets upward only. Currently **line ≥ 98.47%**,
**branch ≥ 95.5%**. Below either is a merge blocker, not a warning.

Single test: `cd backend && pytest tests/test_tree_service.py::test_create_tree -v`

Clear the LRU cache between tests; use the `api_client` / service fixtures
from `conftest.py`.

## Frontend

```bash
make lint-frontend
make typecheck-frontend
make test-frontend     # vitest coverage + coverage floor + allure taxonomy
make build-frontend
make ci-frontend       # all four
```

Floors live in `frontend/coverage-floor.json` and ratchet upward only:
statements **98.77%**, branches **97.56%**, functions **98.64%**, lines
**98.84%**. The Vitest thresholds in `vite.config.ts` sit just under them so a
local run fails on the same regression CI would catch.

There is no coverage escape hatch: `validate_ci_artifacts.py
coverage-suppressions` rejects `istanbul ignore file` and every range form in
`frontend/src` and `mobile/src`. A file excluded from the report is not counted
as uncovered, it is not counted at all — four modules once hid 2,385 lines that
way while the floor still read green.

Mutation, when you are changing behaviour rather than adding a test:

```bash
cd frontend && npm run test:mutation                    # observed scope, ~20 min
cd frontend && npx stryker run --mutate 'src/utils/error.ts'   # one module
python3 scripts/mutation_gate.py check-stryker \
  --report frontend/mutation-artifacts/mutation-report.json \
  --enforced frontend/mutation-enforced-scope.txt        # the enforced tier
```

Watch mode while iterating: `cd frontend && npm run test:watch`

## Mobile

```bash
make typecheck-mobile     # tsc --noEmit
make lint-mobile          # eslint, every eslint-config-expo rule enforced
make test-mobile          # jest + the coverage floor + allure taxonomy
make integration-mobile   # real api client vs a disposable local backend
make build-mobile         # expo export --platform ios
make ci-mobile            # all of the above
make mutation-mobile      # report-only, NOT part of ci-mobile (~5 min)
```

Floors, in `mobile/coverage-floor.json` and enforced by
`scripts/validate_coverage_floor.py`: **statements ≥ 94%, branches ≥ 88%,
functions ≥ 95%, lines ≥ 94%**. The floor may only ratchet upward, and CI
checks a branch that edits it against the base branch's copy.

`make mutation-mobile` runs the ADR-0015 deterministic-core campaign
(`src/braindump/{machine,manifest,uploader,waveform}.ts`,
`src/lifecycle/guards.ts`, `src/config/serverUrl.ts`). It is report-only and
does not gate merge; the last recorded score is 99.35% with two documented
non-behavioral survivors.

`make ci-mobile` includes `integration-mobile`. It did not always — a
locally-green agent could still fail CI — so do not substitute an older
recollection of this target.

Set `BRAIN_BUDDY_MOBILE_IT_PORT` when another agent may be running; the
harness otherwise picks `8700 + random(200)` and two agents can collide.

## End-to-end

```bash
make test-e2e
```

This runs `scripts/run_playwright_e2e.sh`, then three validators: result
freshness against `.run-started-at`, Allure taxonomy, and the product-E2E
story matrix.

**Concurrency hazard:** `scripts/run_playwright_e2e.sh` deletes the shared
Playwright allure and report directories on start. A concurrent agent's
in-flight evidence is destroyed with no warning. Set
`BRAIN_BUDDY_E2E_PROJECT` to a distinct value, or serialize.

## Repo-level gates

```bash
make check-specs     # spec artifact minimum + speckit manifest overrides
make validate-ci     # the validator unit tests + workflow contract checks
```

## The Allure taxonomy contract

Every pytest, Vitest, Jest and Playwright **product** test must emit non-empty
`epic`, `feature`, `story`, a human-readable title, and at least one named
step. Use the central helpers and override only for narrower labels:

- `backend/tests/allure_taxonomy.py`
- `frontend/src/test/allureTaxonomy.ts`
- `frontend/tests/allure.fixtures.ts`
- `mobile/src/test/allureTaxonomy.ts`

Mobile is the one runner whose step cannot come from a hook: in `allure-jest` a
step follows the executing scope, and during `beforeEach` that scope is the
fixture rather than the test. So the mobile helper binds labels in `beforeEach`
and wraps each test body in a step.

Name tests so acceptance can trace them: include the **feature-qualified**
requirement id in the test name or Allure story — `006-FR-001`, or
`006_FR_001` inside a Python function name:

```python
def test_006_FR_001_signs_the_user_in(): ...
```
```ts
allure.story("006-SC-002 sign-in completes under two seconds");
```

The `NNN-` prefix is load-bearing. Every feature restarts numbering at
`FR-001`, so a bare id would let another feature's tests satisfy this feature's
gate. `scripts/check_requirement_coverage.py` accepts only the qualified form
and fails when a requirement has no test naming it.

## Ports and isolation for parallel agents

A git worktree does **not** isolate these. Set each explicitly:

| collision | variable / flag |
|---|---|
| file store + `tasks.sqlite3` | `BRAIN_BUDDY_DATA_DIR` |
| backend port (8000) | uvicorn `--port` |
| frontend port (5173) | vite `--port` |
| mobile integration port | `BRAIN_BUDDY_MOBILE_IT_PORT` |
| Playwright artifact dirs | `BRAIN_BUDDY_E2E_PROJECT` |

## Reporting

Never report green on a gate you did not run. Say `not run` and why. A skipped
surface reported as passing is worse than a red one, because it is believed.
