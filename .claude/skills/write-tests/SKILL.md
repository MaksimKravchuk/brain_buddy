---
name: write-tests
description: How BrainBuddy tests are written and judged — Allure taxonomy, the backend fixture chain, mutation testing as the real feedback loop, and the Vitest/Jest patterns.
---

# Writing tests in BrainBuddy

## Running them

```bash
make test-backend        # pytest + 95% branch coverage + taxonomy validation
make test-frontend       # vitest --coverage + taxonomy validation
make test-mobile         # cd mobile && npx jest
```

While iterating on the backend, skip the coverage and Allure plugins — the
default `addopts` in `backend/pyproject.toml` make a single-file run slow:

```bash
cd backend && python3 -m pytest -c mutmut_pytest.ini -q tests/test_task_owner_isolation.py
```

`mutmut_pytest.ini` is just `addopts = -ra`, and it is also what the mutation
campaign uses (`pytest_add_cli_args` in `[tool.mutmut]`). Run the full
`make test-backend` before you call the work done — the 95% branch gate and the
taxonomy gate only exist there.

## Allure taxonomy: edit the module map, not the tests

Contract and the frontend/Playwright halves: `docs/test-allure-taxonomy.md`.
Every emitted result needs a non-empty epic/feature/story, a human title, and at
least one named step; `scripts/validate_allure_taxonomy.py` fails CI otherwise.

Backend tests are tagged centrally. `backend/tests/allure_taxonomy.py` holds
`_MODULE_TAXONOMY`, keyed by the test file's stem with `test_` and `.py`
stripped — `tests/test_tree_service.py` → `"tree_service"` — mapping to an
`(epic, feature, story)` triple. The `pytest_runtest_call` hookwrapper in
`backend/tests/conftest.py` applies it, derives the title and step from the
test's docstring first line (falling back to a humanised function name), and
wraps the body in one named step.

**So: a new backend test module means one new entry in `_MODULE_TAXONOMY`, not
`@allure.*` decorators on each test.** Skipping the entry does not fail — an
unmapped stem falls back to `(EPIC_QUALITY, _humanize(stem), ...)`, which is how
files quietly end up filed under "Platform Quality" with a mechanical feature
name. Pick the right epic constant (`EPIC_REALITY_TREE`, `EPIC_TASKS`,
`EPIC_AUTH`, `EPIC_AI`, `EPIC_QUALITY`) and name the subsystem, not the file.

Explicit decorators still win per dimension — the hook only fills what a test
did not set — so use them only for a narrower classification than the module's.

Give each test a one-line docstring. It becomes the Allure title and the step
name, so it is read by people who never open the file.

## The backend fixture chain

`backend/tests/conftest.py` offers two ways in, and they do not mix.

**Direct, no ASGI** — the chain used by everything mutation testing can defend:

```
tmp_path -> data_dir -> container -> tree_service / node_service /
                                     relation_service / version_service /
                                     validation_service
```

`container` sets `BRAIN_BUDDY_DATA_DIR` and `BRAIN_BUDDY_ENV=test` via
`monkeypatch`, calls `get_config.cache_clear()` on both sides, and yields
`build_container(config)`. Depend on `data_dir` directly when you want to build
a service by hand — `tests/test_task_owner_isolation.py` does exactly that:

```python
@pytest.fixture()
def service(data_dir: Path) -> TaskService:
    """One service over one database, so both owners share the storage."""
    return TaskService(TaskRepository(data_dir))
```

**Through HTTP** — a `TestClient` over a freshly built app:

- `api_client` — signed in as `primary@example.com`, own data root.
- `second_api_client` — yields `(client_a, client_b)`, two users signed in
  against **one** app and one data root. This is the fixture for HTTP-level
  cross-owner assertions.
- `anonymous_api_client` — no session, for auth-gate tests (401 paths).

Each mints its own invite through `container.invite_repo` before signing up,
because signup is invite-gated. `BrainBuddyTestClient.put` defaults the
brain-dump audio MIME to the deterministic test type.

**Hermeticity.** `app.core.config` calls `load_dotenv()` at import, so conftest
scrubs every `BRAIN_BUDDY_VOICE_*` variable plus `OPENAI_API_KEY` and
`DEEPGRAM_API_KEY` at module import, before any config is built, and pins
`BRAIN_BUDDY_FEATURE_FLAGS=voice_brain_dump=on`. A developer's `.env` therefore
cannot change a test result — and equally, pytest proves nothing about live
provider wiring (use the `verify` skill for that). Tests that need a specific
provider or a flag OFF set it with function-scoped `monkeypatch`, which applies
after the module-level scrub.

The autouse `_reset_login_rate_limiter` clears both in-memory limiters around
every test; do not rely on limiter state carrying between tests.

## Mutation testing is the feedback loop

Read `docs/decisions/0004-deterministic-core-mutation-policy.md` and
`docs/decisions/0011-mutation-scope-observed-and-enforced-tiers.md` before
changing anything in the campaign's scope.

**Coverage says a line ran. Mutation says breaking it would be noticed.** These
are not the same claim, and this repository has the receipt: the owner-scoped
predicates in `app/modules/tasks/repository.py` sat at 89% line coverage under
mutation-compatible tests while scoring 68.3% under mutation. A hand-applied
mutation that removed the owner filter entirely passed all 62 non-ASGI task
tests. Fully covered, entirely unverified.

**A survivor is an instruction; a percentage is not.** "Branch coverage is
94.6%" tells you that something, somewhere, is untested — it is a search
problem. "Mutant survived: `>=` became `>` at `tree_service.py:412`" tells you
the file, the line, the operator, and therefore the exact input that would
distinguish them: the boundary value. One is a number to argue about; the other
is a test you can write in five minutes. Work them one at a time:

```bash
cd backend
mutmut run                     # honours [tool.mutmut] in pyproject.toml
mutmut results                 # summary
mutmut results --all true      # every survivor, by name
mutmut show <mutant-name>      # the diff that survived
mutmut browse                  # interactive triage
```

The scope tiers, per ADR-0011:

- **Observed** — `only_mutate` in `backend/pyproject.toml`: the ADR-0004 Reality
  Tree modules plus `app/modules/tasks/repository.py` and
  `app/services/auth_service.py`. The nightly `.github/workflows/mutation-quality.yml`
  runs this report-only; it is deliberately not triggered by `push` or
  `pull_request`.
- **Enforced** — the ADR-0004 Reality Tree modules only. A module graduates from
  observed to enforced only after clearing 95% on its own across two consecutive
  successful scheduled runs.

Kill a survivor with a focused test, or document it as non-behavioural. Widening
an exclusion to raise the score is not an available remedy (ADR-0004). The four
`# pragma: no mutate block` markers on constructors in `tree_service.py`,
`version_service.py`, `relation_service.py`, and `repositories/index.py` are the
entire justified exclusion set.

### ASGI fixtures cannot run under mutmut

`api_client`, `second_api_client`, and `anonymous_api_client` cannot execute
under mutmut's stack-statistics instrumentation. Consequence, and it is the
single most important structural fact about testing here:

> **Behaviour worth mutating needs a service- or repository-level test.** An
> assertion that only exists at the HTTP layer defends nothing during a
> campaign, no matter how thorough it is.

This is why `[tool.importlinter]` in `backend/pyproject.toml` forbids
`app.services`, `app.repositories`, `app.modules`, `app.workflows`, and `app.ai`
from importing `fastapi` or `starlette` — the framework independence exists so
domain code stays testable without an ASGI fixture.

When you add a mutation-compatible test module, add it to
`pytest_add_cli_args_test_selection` in `[tool.mutmut]`; a test the campaign does
not select cannot kill anything. `mutate_only_covered_lines = true` is also set,
so an uncovered line produces no mutants at all — a module with weak coverage
reports a flattering score about the wrong subset of itself. That is exactly why
ADR-0011 keeps `app/repositories/session.py` and `app/repositories/user.py` out
of both tiers: 65% and 62% non-ASGI line coverage would make the measurement
meaningless.

### The worked example: two owners, or the predicate is invisible

`backend/tests/test_task_owner_isolation.py` is the shape to copy.
`app/modules/tasks/repository.py` carries 129 owner-scoped predicates. Consider
`_get`:

```python
f"SELECT payload FROM {table} WHERE owner_id = ? AND id = ?"
```

A mutant that drops `owner_id = ? AND` is a cross-tenant read. In
`delete_all_for_owner` the same mutation turns a one-account GDPR purge into a
wipe of every account.

A single-owner test cannot kill either mutant. With one owner's rows in the
database, `WHERE owner_id = ? AND id = ?` and `WHERE id = ?` select the same
row, and `DELETE ... WHERE owner_id = ?` and `DELETE` empty the same table. The
assertion passes identically before and after the mutation, so the test carries
no information about the predicate at all. Coverage still reports the line as
executed — that is precisely the failure mode ADR-0011 describes.

Two owners in **one** database make the difference observable:

```python
def test_get_task_for_owner_hides_another_owners_task(service: TaskService) -> None:
    foreign = _task(service, OWNER_B, title="B private", key="b-task")

    with pytest.raises(NotFoundError):
        service.task_repo.get_for_owner(foreign.id, owner_id=OWNER_A)
```

The foreign row exists, so an unfiltered query returns it and the `pytest.raises`
fails. Same principle for the purge: seed owner B, purge owner A, then assert B's
tasks *and* projects survived. For list endpoints assert the exact id list, not
just membership — `== [mine.id]` fails when a foreign row leaks in, whereas
`mine.id in ids` does not.

Note also `test_idempotency_keys_do_not_collide_across_owners`: both owners use
the *identical* idempotency key. A key that is unique per test cannot detect a
missing owner column in the idempotency lookup.

The generalisation: **construct the state in which the mutated and unmutated code
would disagree.** If no input you supply can tell them apart, the test is
decorative.

## Frontend Vitest

Specs live in `frontend/src/**/__tests__/*.test.ts(x)`; `frontend/vite.config.ts`
sets `environment: "jsdom"`, `globals: true`, and 95% statement/branch/function/
line coverage thresholds (istanbul).

```bash
cd frontend && npm test            # vitest run
cd frontend && npm run test:watch
```

Taxonomy is automatic: `frontend/src/test/allureTaxonomy.ts` runs in `afterEach`,
assigns epic/feature from an ordered source-path rule list, takes the story from
the top `describe`, and only fills dimensions the spec did not set. Adding a spec
under a new directory means adding a `PATH_RULES` entry there. For a narrower
label, call `feature()` / `story()` / `step()` from `allure-js-commons` inside
the test body.

Style, per `frontend/src/utils/__tests__/error.test.ts`: one `describe` per
exported function, `it` names stating the behaviour, and assertions on exact
strings rather than `toContain`. Playwright e2e lives in `frontend/tests/` and
must import `{ expect, test }` from `./allure.fixtures`.

## Mobile Jest

`mobile/jest.config.js` uses the `jest-expo` preset, matches
`**/__tests__/**/*.test.ts(x)`, ignores `mobile/integration/`, and sets
`clearMocks: true` — so do not hand-roll mock resets.

```bash
make typecheck-mobile   # tsc --noEmit, strict
make test-mobile        # unit only
make integration-mobile # real api client vs a disposable local backend
```

Unit tests here are for the wire-protocol logic the client must not get wrong —
chunk hashing, manifest hash, lifecycle guards (see `mobile/AGENTS.md`).
`mobile/src/lifecycle/__tests__/guards.test.ts` is the pattern: `it.each` over
the full state enumeration, asserting whole result objects with `toEqual` rather
than probing one field, so a new state cannot slip through untested. There is no
Allure taxonomy gate on the mobile suite.
