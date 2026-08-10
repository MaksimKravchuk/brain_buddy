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

Floors, enforced by `scripts/validate_backend_coverage.py`: **line ≥ 95%** and
**branch ≥ 95%**. Below either is a merge blocker, not a warning.

Single test: `cd backend && pytest tests/test_tree_service.py::test_create_tree -v`

Clear the LRU cache between tests; use the `api_client` / service fixtures
from `conftest.py`.

## Frontend

```bash
make lint-frontend
make test-frontend     # vitest coverage + allure taxonomy
make build-frontend
make ci-frontend       # all three
```

Floors: istanbul **95% across all four** metrics — statements, branches,
functions, lines.

Watch mode while iterating: `cd frontend && npm run test:watch`

## Mobile

```bash
make typecheck-mobile     # tsc --noEmit
make lint-mobile          # expo lint
make test-mobile          # jest
make integration-mobile   # real api client vs a disposable local backend
make build-mobile         # expo export --platform ios
make ci-mobile            # all of the above
```

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

Every pytest, Vitest and Playwright **product** test must emit non-empty
`epic`, `feature`, `story`, a human-readable title, and at least one named
step. Use the central helpers and override only for narrower labels:

- `backend/tests/allure_taxonomy.py`
- `frontend/src/test/allureTaxonomy.ts`
- `frontend/tests/allure.fixtures.ts`

Name tests so acceptance can trace them: include the `FR-###` or `SC-###` a
test covers in its name or Allure story. `scripts/check_requirement_coverage.py`
fails when a requirement has no test emitting its id.

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
