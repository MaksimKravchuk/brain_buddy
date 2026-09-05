# E2E acceptance charter

Status: executable QA design; native tasks and Voice Brain Dump product matrix accepted for CI.
Owner: AI-QA.
Scope: browser E2E acceptance for the current authenticated tree/version product plus vNext contracts that are already normative in ADR-0001 and ADR-0002.

## Purpose

This charter turns the Phase 5 hardening/testing plan into deterministic Playwright journeys that can run against the Compose stack before release. It is intentionally risk-based: browser E2E should prove high-value user journeys, ownership boundaries, and recovery affordances. It should not duplicate every backend API contract or property test.

## Grounded current behavior

The scenarios below are based on the current code and docs:

- Auth is invite-gated email/password with server-side opaque sessions in an HTTP-only `brainbuddy_session` cookie. Signup consumes one invite; login is rate-limited; logout clears the session. See `docs/auth.md` and `backend/app/api/auth.py`.
- All tree routes require `get_current_user`; tree reads/mutations call `TreeService.get_tree_for_owner` or `assert_owner`, returning indistinguishable 404 for missing vs cross-owner tree IDs. See `backend/app/api/routes.py` and `backend/app/services/tree_service.py`.
- The UI routes `/login`, `/signup`, and `/`; `/` is protected by `ProtectedRoute`, hydrates `/api/auth/me`, lists the signed-in user's trees, and shows `TreeWorkspace`. See `frontend/src/App.tsx`, `frontend/src/components/auth/ProtectedRoute.tsx`, and `frontend/src/pages/TreeWorkspace.tsx`.
- Versioning supports create/list/delete/restore and JSON export for live or historic tree state. Browser workflows must cover the version panel UX; API suites own byte-level export payload validation. See `backend/app/api/routes.py`, `backend/app/services/version_service.py`, and `frontend/src/api/hooks.ts`.
- Compose exposes backend on `${BRAIN_BUDDY_PORT:-8000}` and frontend on `${FRONTEND_PORT:-8080}`. Browser session tests over local HTTP must not run in production mode: `secure=environment is AppEnvironment.PRODUCTION` (`backend/app/core/config.py`), so production marks cookies `Secure` and local HTTP browser auth fails by design. The shipped harness uses `BRAIN_BUDDY_ENV=test` (`scripts/run_playwright_e2e.sh`); `development` also works. See `compose.yaml`.
- ADR-0001/0002 require owner-scoped records, explicit confirmation before routing/deletion/CRT promotion, idempotency, redacted events/telemetry, and no model/provider output directly mutating canonical records. Browser E2E should cover user-visible gates; API/contract tests own state-machine exhaustiveness and idempotency matrices.

## Execution target

Run Playwright against a fresh Compose project, not the developer's persistent local stack.

Required harness behavior:

1. Create an isolated Compose project name per run, for example `brainbuddy-e2e-${GITHUB_RUN_ID:-local}-$(date +%s)`.
2. Start with an empty backend data volume.
3. Set:
   - `BRAIN_BUDDY_ENV=test` (anything other than `production`; the shipped
     harness uses `test`)
   - `BRAIN_BUDDY_PORT` and `FRONTEND_PORT` to run-specific free ports
   - `VITE_API_BASE_URL=/api`
4. Wait on `/health` before opening the browser.
5. Mint invites with `docker compose exec -T backend python -m app.cli create-invite`.
6. Create browser users only through the UI when the scenario is about auth UX; use Playwright `request` fixtures only for preconditions and teardown.
7. Tear down with `docker compose down -v --remove-orphans` even after failures.

The harness now exists. Run it with:

```bash
make test-e2e
```

which invokes `scripts/run_playwright_e2e.sh` and then the three validators
(result freshness, Allure taxonomy, product-E2E story matrix). Requires
`cd frontend && npx playwright install --with-deps chromium` once.

To drive Compose by hand for debugging:

```bash
COMPOSE_PROJECT_NAME=brainbuddy-e2e BRAIN_BUDDY_ENV=test BRAIN_BUDDY_PORT=8001 FRONTEND_PORT=8081 docker compose up -d --build
cd frontend && npx playwright test --config playwright.config.ts
COMPOSE_PROJECT_NAME=brainbuddy-e2e docker compose down -v --remove-orphans
```

**Concurrency hazard**: `scripts/run_playwright_e2e.sh` deletes the shared
Playwright allure and report directories on start, destroying a concurrent
agent's in-flight evidence. Set `BRAIN_BUDDY_E2E_PROJECT`, or serialize.

## Fixture model

Use deterministic, per-test fixtures:

- `e2eUserA` and `e2eUserB` with unique emails, fixed safe password length, and one invite each.
- `simpleTree`: one tree named with the test id, two nodes (`Root Cause`, `Observed Effect`), one `why` relation, and stable positions.
- `versionedTree`: `simpleTree` plus one snapshot named `baseline`, then a node label edit and second snapshot named `edited`.
- `largeViewportTree`: 12-20 nodes for pan/zoom/selection coverage. Do not use random graph generation in browser E2E.
- `importPayloadWithForeignOwner`: a valid exported tree whose embedded `owner_id` is not the importing user; browser import should succeed and display only the current user's stamped owner data where exposed. Deep owner stamping assertions belong in API tests.

Fixture creation rules:

- Browser tests may create data through the API only before the page starts, and only for setup. The user-observable action under test must still be performed through the UI.
- Each test owns its users and tree names. No test depends on execution order or shared persisted data.
- Prefer explicit waits on URL, role/name, and network responses over sleeps.

## Browser E2E acceptance scenarios

### Native tasks and Voice Brain Dump product matrix

The native task shell plus Voice Brain Dump suite is now a required product E2E
gate. It must run through the committed Compose stack (`frontend nginx ->
FastAPI -> file-backed persistence`) with only browser SpeechRecognition and
microphone boundaries deterministically faked. Fetch, task APIs, operation APIs,
auth, persistence, and owner scoping are not mocked. Legacy `/crt` smoke tests,
API-only dogfood scripts, screenshots, or skipped/fixme scenarios cannot satisfy
this matrix.

| Requirement | Executable scenario | Evidence gate |
|---|---|---|
| Native task shell opens `/tasks/next`, renders real Inbox/Next counts and rows, navigates by state/project/tag, and survives reload/relogin. | `frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts` story `Native task shell navigation` | Active Playwright Allure result with epic `BrainBuddy MVP loop` and feature `Native tasks and Voice Brain Dump` |
| MVP task CRUD creates an Inbox task, edits its title, moves Inbox -> Next, completes, reopens, and proves persistence after reload/relogin. | Story `Minimal native task management` | Same active Allure product labels |
| Voice Brain Dump happy path captures two deterministic utterances on mobile, shows the browser-preview transcript readout (never draft task cards; ADR-0002, 2026-09-05 amendment), pauses/resumes, reviews, edits/deletes, and saves exactly one edited Inbox task only after confirmation. | Story `Voice Brain Dump happy path` | Same active Allure product labels |
| Brain Dump recovery/idempotency reloads/resumes an active or paused operation, retries commit without duplicates, and proves the same single committed Inbox task after relogin. | Story `Voice Brain Dump idempotency and recovery` | Same active Allure product labels |
| Brain Dump failure handling shows recoverable errors for unavailable speech, denied mic, transcript conflicts, and failed pause/cancel/finish/commit while preserving the live transcript and creating no unintended backend operation. Every destructive exit (Discard, Discard all, Delete recording, Cancel processing) asks an inline question first; a refused cancel closes the question and reports through the alert. | Story `Voice Brain Dump failure recovery` | Same active Allure product labels |
| Owner isolation prevents a second user from seeing another user's tasks, operations, drafts, or committed task linkage. | Story `Owner isolation` | Same active Allure product labels |
| Mobile-first usability at representative 390x844 keeps capture/review/save primary controls visible with no horizontal overflow, while desktop task navigation remains covered by the native shell scenario. | Covered inside the Voice Brain Dump happy-path and native shell scenarios | Same active Allure product labels plus Playwright viewport assertions |

CI enforces the durable evidence contract in `.github/workflows/ci.yml` via the
`e2e` job, named **`Compose Playwright E2E`**. The job runs
`scripts/run_playwright_e2e.sh` (locally: `make test-e2e`), publishes the
**`playwright-allure-results`** artifact from
`frontend/allure-results/playwright`, and validates the active story-label
matrix with `scripts/validate_ci_artifacts.py product-e2e-results`. The
validator fails if no native product scenarios execute, if only skipped/stale
results exist, or if CRT-labeled evidence is presented as this product suite.

An acceptance auditor enforcing this charter must use the names above. Earlier
revisions of this section named a `Native Product Compose E2E` job, an
`npm run test:e2e:compose` script and a `native-product-e2e-allure-results`
artifact; none of the three has ever existed in this repository, and grading
against them produces false violations.

### E2E-AUTH-01: invite signup creates a session and reaches the workspace

Risk: broken invite/session cookie path blocks all product usage.

Steps:
1. Mint an invite through the backend CLI.
2. Open `/signup`.
3. Submit a unique email, a >=12 character password, and the invite code.
4. Assert navigation to `/`.
5. Assert the workspace header shows the signed-in email and the protected workspace, not the login form.
6. Reload the page.
7. Assert the session is hydrated and remains on `/`.

Acceptance:
- Signup returns the user to the workspace without manual login.
- Reload does not flash an unauthenticated terminal state after hydration completes.
- The session cookie is HTTP-only in browser context; tests must not read token contents from JavaScript.

### E2E-AUTH-02: used invite and invalid login fail without creating access

Risk: auth bypass or misleading login/signup failures.

Steps:
1. Use an invite once through `/signup`.
2. Sign out.
3. Attempt `/signup` again with a different email and the same invite.
4. Assert the visible error is `Invite code is invalid or already used.` and the URL remains `/signup`.
5. Open `/login` and submit the original email with a wrong password.
6. Assert `Invalid email or password.` and no workspace access.

Acceptance:
- Failed auth attempts never route to `/`.
- Error text is user-safe and does not expose invite existence beyond the current documented messages.

### E2E-AUTH-03: protected route redirects anonymous users and preserves intended destination

Risk: unauthenticated access or broken redirect after login.

Steps:
1. Clear browser storage/cookies.
2. Open `/`.
3. Assert redirect to `/login`.
4. Log in with an existing fixture user.
5. Assert navigation back to `/` and workspace load.

Acceptance:
- Anonymous users cannot render `TreeWorkspace`.
- Login uses the `from` location captured by `ProtectedRoute`.

### E2E-TREE-01: create, rename, switch, and delete a tree

Risk: core CRUD regressions in the highest-frequency browser path.

Steps:
1. Sign in as user A.
2. Open the tree menu.
3. Create `E2E Primary Tree`.
4. Assert it becomes the selected tree and the empty canvas state is gone.
5. Rename it to `E2E Renamed Tree`.
6. Create a second tree `E2E Secondary Tree`.
7. Switch back to `E2E Renamed Tree`.
8. Delete `E2E Secondary Tree`.
9. Reload.
10. Assert only `E2E Renamed Tree` is visible for user A.

Acceptance:
- React Query/cache updates and backend persistence agree after reload.
- Delete selects a valid remaining tree or empty state without stale detail errors.

### E2E-TREE-02: node and relation canvas happy path

Risk: canvas interactions can pass unit tests while failing in real browser layout/input.

Steps:
1. Sign in as user A and create a tree.
2. Add a parent/effect node and a child/cause node using the supported UI affordances.
3. Edit both node labels in the inspector or inline editor.
4. Create a `why` relation from cause to effect.
5. Assert relation counts/visual edge reflect the relation.
6. Reload.
7. Assert both labels and the relation are still present.

Acceptance:
- Use semantic roles or stable `data-testid` selectors added by the implementation card; do not couple tests to React Flow internals.
- Persisted backend state survives a browser reload.

### E2E-TREE-03: import/export round trip stays owner scoped

Risk: imported payloads can overwrite IDs, leak embedded owners, or produce unusable downloads.

Steps:
1. Sign in as user A and create `E2E Export Source` with at least two nodes and one relation.
2. Trigger browser download/export.
3. Assert a JSON file is downloaded with a deterministic `.json` filename prefix containing the tree id or name.
4. Sign in as user B in a fresh context.
5. Import the downloaded JSON.
6. Assert user B sees an imported tree with equivalent visible nodes/relations.
7. Sign out/in as user A.
8. Assert user A's original tree still exists and user B's imported tree is not listed.

Acceptance:
- Browser E2E checks visible isolation and successful round trip.
- API contract tests separately assert imported `owner_id` is stamped to user B and a fresh tree id is assigned.

### E2E-VERSION-01: create snapshot, modify tree, restore snapshot

Risk: version panel may display data but fail the real restore loop.

Steps:
1. Sign in as user A and create `versionedTree`.
2. Create a version named `baseline` with notes.
3. Modify a visible node label.
4. Create a second version named `edited`.
5. Restore `baseline` through the version panel confirmation.
6. Assert the original node label returns and the edited label is absent.
7. Reload and assert restored state persists.

Acceptance:
- Version list shows labels, notes/metadata if exposed, and restore feedback.
- Restore is confirmed before applying a destructive state change.

### E2E-VERSION-02: delete snapshot requires confirmation and updates list

Risk: accidental destructive version operations and stale cache.

Steps:
1. Sign in as user A and create a tree with two versions.
2. Start deleting one version.
3. Cancel the confirmation; assert the version remains.
4. Delete again and confirm.
5. Assert the deleted version is removed, the other version remains, and reload preserves the list.

Acceptance:
- Destructive action has a visible confirmation boundary.
- Cache invalidation does not remove the wrong version.

### E2E-SEC-01: cross-user tree isolation in browser-visible lists

Risk: multi-user owner isolation regressions.

Steps:
1. Sign in as user A and create `A Secret Tree`.
2. Sign out.
3. Sign in as user B and create `B Public Tree`.
4. Assert user B's tree menu/list does not contain `A Secret Tree`.
5. Sign back in as user A.
6. Assert user A's tree menu/list does not contain `B Public Tree`.

Acceptance:
- Browser UI never lists another user's tree names.
- API tests separately verify direct `GET/PATCH/DELETE /api/trees/{other_tree_id}` returns 404.

### E2E-SEC-02: unauthorized API response forces browser session clear

Risk: expired/revoked sessions leave stale private data visible.

Steps:
1. Sign in as user A and create/open a tree.
2. Revoke the session through `POST /api/auth/logout` using the same browser context or delete the backing session via a fixture helper.
3. Trigger a tree refetch or mutation from the UI.
4. Assert the app clears the session and navigates to `/login`.
5. Assert prior tree content is no longer visible after the redirect.

Acceptance:
- `setUnauthorizedHandler` clears auth state on 401.
- No private canvas data remains visible behind the login screen.

### E2E-A11Y-01: keyboard-first auth and primary tree controls

Risk: core flows are mouse-only or focus-trapping.

Steps:
1. Use keyboard only to tab through `/signup`, submit, and arrive at the workspace.
2. Open the tree menu with keyboard.
3. Reach create/rename/delete tree controls with visible focus.
4. Dismiss any modal with Escape and assert focus returns to the invoking control.

Acceptance:
- No keyboard trap in auth forms, menu, or modals.
- Focus order follows visible layout.
- This is not a replacement for component-level axe checks; it proves browser usability.

### E2E-MOBILE-01: smoke critical auth/tree path on a phone viewport

Risk: MVP is unusable on mobile-sized screens even if desktop passes.

Project: one mobile browser project, preferably Pixel 5 Chromium initially.

Steps:
1. Open `/signup` at mobile viewport and create a user.
2. Create a tree.
3. Open the tree menu, sign out, and log back in.
4. Assert the tree remains selectable/visible without horizontal page overflow hiding primary controls.

Acceptance:
- Auth and tree menu are usable at 393x851 or equivalent.
- Do not require full canvas editing on mobile until product UX explicitly supports it.

### E2E-VNEXT-01: confirmation gate for voice/review operation proposals

Risk: future model-backed flows mutate canonical records before user approval.

Status: pending product implementation; include as `test.fixme` or a skipped charter scenario until operation UI exists.

Required behavior when implemented:
1. Start a voice brain dump or voice Weekly Review operation with a fixture transcript/model stub.
2. Let provisional candidates appear.
3. Navigate away and back; assert proposals resume from operation projection.
4. Assert no canonical tree/capture/review/task-tracker write has occurred before explicit confirm.
5. Confirm a frozen batch.
6. Assert exactly one canonical write per accepted action, with visible provenance/result link.

Acceptance:
- Browser E2E proves the user-visible confirmation boundary.
- API/property tests own patch ordering, idempotency keys, retry checkpoints, redacted events, and cross-owner target resolution.

## API contract and property scope, not browser E2E

Keep the following out of Playwright browser journeys except as fixture helpers or one visible smoke assertion:

- Exhaustive FastAPI status-code matrix for every tree/node/relation/version/auth endpoint.
- Direct cross-owner attempts by tree/version/node/relation id returning 404.
- Pydantic schema validation, unknown fields, password length bounds, invite repository edge cases, and rate-limit counters.
- Import/export JSON byte-level schema and metadata/owner stamping assertions.
- Version diff summaries, conflict counts, filename construction, and historic export bytes.
- ADR-0001 module state-machine transition matrices, stale revisions, unsupported event versions, import-boundary checks, and no-repository-cross-import architecture tests.
- ADR-0002 operation patch ordering, event sequence gaps, retry/idempotency permutations, raw-audio retention, provider/model calibration thresholds, and redacted telemetry payloads.
- Performance/property checks for 100-200 node graphs. Browser E2E may include one deterministic large-viewport smoke, but load/perf budgets need a dedicated benchmark harness.

## Selectors and testability requirements

The later implementation card should add stable, user-intent selectors only where semantic roles are insufficient. Required selector surface:

- auth forms: email, password, invite inputs and submit buttons should be reachable by accessible labels/names;
- tree menu root and items;
- create/rename/delete tree dialogs and confirmation buttons;
- canvas root, empty state, node by label, relation edge by source/target label if not accessible by role;
- node/relation inspector root and editable fields;
- version panel, version row by label, create/restore/delete controls;
- toast stack and retry actions;
- import file input and export/download trigger.

Do not select generated React Flow class names, SVG path order, lucide icon internals, or Tailwind utility strings.

## Failure artifacts

CI must retain enough evidence to debug flakes without rerunning locally:

- Playwright HTML report.
- Trace on first retry and always-on trace for failures in CI.
- Screenshot and video only on failure.
- Browser console errors and failed network requests attached to the test output.
- Compose backend/frontend logs after failure, with cookies/session tokens redacted.
- Downloaded export JSON for failed import/export tests, unless it contains user-authored sensitive content; fixture data should be synthetic.
- Allure attachment integration when available, matching the existing Quality Spine artifact convention.

## Anti-flake rules

- No fixed sleeps. Wait for URL, role/name, visible text, response status, or persisted state.
- One test, one isolated user/data set. No test relies on another test's account, invite, tree, or browser context.
- Browser projects should initially run Chromium desktop plus one mobile Chromium smoke. Add Firefox/WebKit only after the suite is stable and runtime is acceptable.
- Run browser E2E serially in CI against one Compose stack unless each worker gets its own project name and ports.
- Disable or strictly control retries locally. CI may retry once or twice, but a retry pass must still publish first-failure artifacts.
- Prefer API fixture setup over UI setup for non-auth preconditions to reduce test length, but never assert API-only behavior through browser E2E.
- Use deterministic fixture names with the test id and timestamp/run id. Avoid random graph generation, external providers, network calls outside Compose, Fly, or paid LLM calls.
- Treat model/provider behavior as nondeterministic: model-backed future tests must use a stub/provider fixture with fixed outputs. Paid/credentialed LLM checks require explicit approval and are not part of this charter.

## Release gate recommendation

Minimum gate before enabling the E2E suite as required CI:

1. E2E-AUTH-01
2. E2E-TREE-01
3. E2E-SEC-01
4. E2E-VERSION-01
5. E2E-MOBILE-01

Add the remaining scenarios once selectors, dialogs, and fixture helpers are stable. The first required gate should target <=10 minutes on CI and produce artifacts for every failure.

## Handoff to implementation

Implementation should create or update:

- `frontend/playwright.config.ts`: baseURL from env, Compose webServer or documented external stack mode, artifacts, mobile project, CI workers/retries.
- `frontend/tests/fixtures/`: account/invite helpers, API fixture helpers, download helpers, synthetic tree payloads.
- `frontend/tests/*.spec.ts`: scenario files named by domain (`auth.spec.ts`, `tree-crud.spec.ts`, `versioning.spec.ts`, `security.spec.ts`, `mobile.spec.ts`).
- `Makefile`: `test-e2e` target once the harness exists.
- CI workflow: optional first, then required after the minimum gate is stable.

Do not contact Fly, deploy, merge, or use paid LLM/provider credentials for this acceptance suite.
