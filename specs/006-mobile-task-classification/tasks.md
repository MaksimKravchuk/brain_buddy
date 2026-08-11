# Tasks — 006 Mobile task classification

**Input**: `spec.md`, `plan.md`, `design.md`, `data-model.md`, `research.md`,
`quickstart.md`, `contracts/README.md`
**Gate**: campaign 2 closed by founder acceptance 2026-08-11, expiring
2026-11-09 (`review-history.md`). Implementation is unblocked until that date.

## Conventions that apply to every task here

- **TDD.** Every test task lands a *failing* test before its implementation task
  runs. `plan.md` names this explicitly; it is not a stylistic preference.
- **Every test carries its feature-qualified id** — `006-FR-017`, `006-SC-008`.
  A bare `FR-017` is rejected: every feature restarts at 001, so
  `scripts/check_requirement_coverage.py` cannot trace it.
- **`mobile/` cannot render a component in a test.** Jest runs over pure modules
  only. Anything in a `.tsx` file has typecheck, bundle and a numbered
  `quickstart.md` step as its evidence — and the task says so rather than
  implying coverage that does not exist.
- **No module reads the clock except through an argument.** `expireQueue` and
  `formatLastSynced` take `now`. There is no fake-timer precedent in `mobile/`,
  so an internal `Date.now()` makes the 30-day boundary untestable.
- **Allure taxonomy on backend tests only.** `CLAUDE.md` scopes the rule to
  pytest, Vitest and Playwright. `mobile/` runs plain Jest with no taxonomy
  helper, so the backend test carries full `epic`/`feature`/`story` and a named
  step, and the Jest suites carry none. See T003.

---

## Phase 1: Setup

- [x] T001 Develop on the designated feature branch. **The worktree is deliberately skipped**: the session's branch policy requires this branch, a second worktree fights that for no benefit, and the parallel agents are already isolated by disjoint file ownership rather than by directory
- [x] T002 **Dropped.** The directory already existed, and a barrel nothing imports is dead code that the coverage floor then counts. Every module here is imported by path, matching the rest of `mobile/src`
- [x] T003 **Dropped, and the original task was wrong.** `CLAUDE.md` scopes the Allure taxonomy rule to pytest, Vitest and Playwright; `mobile/` runs plain Jest and has no `src/test/allureTaxonomy.ts` to extend. Inventing one to satisfy a rule that does not apply would add a fixture nothing reads. The backend test in T039 still carries full Allure, because backend tests genuinely are in scope
- [ ] T004 Confirm `make typecheck-mobile`, `make test-mobile` and `make build-mobile` are green on the untouched branch, so every later failure is attributable
- [x] T004a Write the shared type contract in mobile/src/features/tasks/classificationTypes.ts before fanning out, so the reducer, storage adapter and drain hook can be built in parallel without racing on a shared file

---

## Phase 2: Foundational (blocks every user story)

**These are the pure modules and the identity/session substrate. No user story
can be demonstrated until they exist.**

### The session substrate — FR-019, FR-020, FR-011

- [x] T005 [P] Write failing `006-FR-019` table test in mobile/src/auth/__tests__/sessionOutcome.test.ts: `ApiError(401)` → `unauthenticated`, `ApiError(503)` → `other`, bare `TypeError` (what fetch throws offline) → `unreachable`
- [x] T006 Implement `classifySessionFailure(error: unknown)` in mobile/src/auth/sessionOutcome.ts to make T005 pass
- [x] T007 Add the fourth `SessionStatus` value `"signed-in-offline"` in mobile/src/auth/SessionProvider.tsx — FR-019 requires a representable "authenticated, offline, no live profile" state and the union has nowhere to put it today
- [x] T008 Rewrite `probe()` in mobile/src/auth/SessionProvider.tsx to dispatch on `classifySessionFailure` — only `unauthenticated` signs the person out; `unreachable` resolves from persisted state. This is the line that made an offline launch indistinguishable from a sign-out
- [x] T009 [P] Write failing `006-FR-019` test in mobile/src/api/__tests__/client.test.ts asserting `onUnauthorized` fires on a 401 and does NOT fire when the injected `fetchImpl` rejects
- [x] T010 Persist identity and the resolved rollout flag on **every** response yielding a `MeResponse` — `/auth/me`, `/auth/login`, `/auth/signup` — in mobile/src/auth/SessionProvider.tsx. `signIn`/`signUp` never call the probe, so persisting only on `/auth/me` leaves a fresh sign-in with no stored identity (FR-009, FR-020)
- [x] T011 [P] Write failing `006-FR-020` test in mobile/src/auth/__tests__/flagResolution.test.ts: the flag resolves `true` from persisted state with a null `me`, and `false` when it was never known for this identity
- [x] T012 Implement the persisted-flag read beside `voiceEnabled` in mobile/src/auth/SessionProvider.tsx to make T011 pass — fail-closed means closed when never known, not closed whenever the network is down
- [x] T013 Make `updateServerUrl` a real identity transition in mobile/src/auth/SessionProvider.tsx (clear `me`, set signed-out, re-probe). Today it only persists the URL, so FR-011's server-change binding has nothing to hang on while settings.tsx already tells the user it signs them out

### Storage keys and the device stores — FR-011, FR-018, SC-007

- [x] T014 [P] Write failing `006-SC-007` test in mobile/src/features/tasks/__tests__/storageKey.test.ts: components are escaped separately, and two distinct (serverUrl, accountId) pairings can never render to one key
- [x] T015 Implement `queueKey()` and `cacheKey()` in mobile/src/features/tasks/storageKeys.ts using `encodeURIComponent` per component
- [x] T016 [P] Write failing `006-FR-018` boundary table in mobile/src/features/tasks/__tests__/expireQueue.test.ts: 29d23h kept, 30d1m expired, payload retained on expiry, dropped count returned not swallowed, a future timestamp clamped rather than becoming immortal
- [x] T017 Implement `expireQueue(entries, now)` in mobile/src/features/tasks/classificationQueue.ts — pure, clock injected
- [x] T018 [P] Write failing `006-FR-018` test for the cross-identity sweep in mobile/src/features/tasks/__tests__/sweep.test.ts: the age rule applies to every stored key, and a non-active key is deleted outright once a different identity signs in
- [x] T019 Implement `sweepAllIdentities()` in mobile/src/features/tasks/classificationQueue.storage.ts over `AsyncStorage.getAllKeys()` — identity-in-the-key closes disclosure but cannot delete, and a key nobody reads never expires
- [x] T020 [P] Write failing `006-FR-011` / `006-SC-008` table in mobile/src/features/tasks/__tests__/identityEvent.test.ts for `resolveQueueOnIdentityEvent`: involuntary+same → keep, involuntary+different → discard, deliberate+same → warn-then-discard, deliberate+different → warn-then-discard
- [x] T021 Implement `resolveQueueOnIdentityEvent()` in mobile/src/features/tasks/classificationQueue.ts
- [x] T022 Implement the AsyncStorage adapter in mobile/src/features/tasks/classificationQueue.storage.ts, including the defence-in-depth read check that verifies each entry's own `accountId`/`serverUrl` against the active identity and discards a mismatch before display or send

### The queue reducer — FR-010, FR-017, FR-021

- [x] T023 [P] Write failing `006-FR-010` reducer tests in mobile/src/features/tasks/__tests__/classificationQueue.test.ts: net-effect coalescing; a tag added then removed leaves no trace; an entry whose net set equals the server's is dropped rather than sent as a no-op
- [x] T024 [P] Write failing `006-FR-010` test that after N coalesces including a `null` clear, `originalValue` is unchanged from first capture, and `firstQueuedAt` is immutable while `lastEditedAt` moves
- [x] T025 [P] Write failing `006-FR-017` tests: `idempotencyKey` is byte-identical across an unchanged retry, and **changes** when coalescing alters `projectId` or `tagIds`
- [x] T026 [P] Write failing `006-FR-017` single-flight test: an entry in `sending` is not returned by a second `selectDrainable`, and two concurrent drain triggers produce exactly one call to an injected sender
- [x] T027 [P] Write failing `006-FR-021` test that loads a queue fixture containing a `sending` entry and asserts it is reset to `queued` and drained
- [x] T028 [P] Write failing `006-FR-010`/`006-FR-017` test for an edit arriving while an entry is `sending`: it creates a successor entry with its own key, and the in-flight acceptance does not remove the successor's work
- [x] T029 Implement the reducer in mobile/src/features/tasks/classificationQueue.ts — coalescing, key lifecycle, `selectDrainable`, the successor rule, and the cold-read `sending` → `queued` reset — to make T023–T028 pass

### The remaining pure modules

- [x] T030 [P] Write failing `006-FR-005` table in mobile/src/features/tasks/__tests__/matchExisting.test.ts: exact match, case difference, leading/trailing whitespace all match; a substring must NOT
- [x] T031 Implement `matchExisting(typedName, candidates)` in mobile/src/features/tasks/matchExisting.ts
- [x] T032 [P] Write failing `006-SC-004` table in mobile/src/features/tasks/__tests__/syncStatus.test.ts over `now - lastSyncedAt`
- [x] T033 Implement `formatLastSynced(lastSyncedAt, now)` in mobile/src/features/tasks/syncStatus.ts
- [x] T034 [P] Write failing `006-FR-008` table in mobile/src/features/tasks/__tests__/conflictDecision.test.ts, including the branch on `detail.resource`: `"Task"` opens the conflict sheet, `"Idempotency-Key"` is a client bug that must never be retried with the same key
- [x] T035 Implement `conflictDecision.ts` in mobile/src/features/tasks/conflictDecision.ts, including the "server already holds what the entry intended" resolution that drops the entry and advances last-synced without prompting
- [x] T036 [P] Write failing `006-FR-006` test for the list cache in mobile/src/features/tasks/__tests__/classificationCache.test.ts, including that it is cleared on a deliberate identity transition **even when the queue is empty**
- [x] T037 Implement mobile/src/features/tasks/classificationCache.ts

### Backend and API surface

- [x] T038 Add the rollout flag to the per-user feature flags in backend/app/core/config.py, defaulting OFF (FR-015). This is the one backend line; FR-014 forbids any other backend change
- [x] T039 [P] Add a backend test naming `006-FR-015` in backend/tests/test_feature_flags.py asserting the flag defaults off and is delivered in `MeResponse`
- [x] T040 Change `useUpdateTask` in mobile/src/api/hooks.ts to accept the entry's idempotency key instead of minting its own — FR-017 requires the entry to own its key, and the hook is the call path the task screen actually uses
- [x] T041 Add cache write-through to `useProjects`/`useTags` in mobile/src/api/hooks.ts, and read-back on fetch failure

**Checkpoint**: pure modules green, session substrate in place. User stories can now proceed.

---

## Phase 3: User Story 1 (P1) — classify a task on the phone

**Goal**: a person sets and clears a project and attaches and detaches Tags on
the task screen, and it reaches the server.

**Independent test**: `quickstart.md` "Manual end-to-end check" passes — set a
project and two Tags on the phone, refresh the web client, see both.

- [ ] T042 [P] [US1] Write the failing integration assertion `006-FR-001` in mobile/integration/run.ts: set a project on a real task against the disposable backend, then read it back
- [ ] T043 [P] [US1] Write the failing integration assertion `006-FR-002` in mobile/integration/run.ts for attaching and detaching a Tag
- [ ] T044 [P] [US1] Write the failing integration assertion `006-FR-003` in mobile/integration/run.ts for clearing a project with an explicit `null`
- [ ] T045 [P] [US1] Write the failing integration assertion `006-SC-002` in mobile/integration/run.ts proving the server holds exactly what the phone sent (pairs with the manual web-client refresh)
- [ ] T046 [US1] Relayout the task-detail metadata area in mobile/src/app/task/[id].tsx from the current chip row into labelled Project/Tags/Due/Priority rows with chevrons, keeping muted placeholders when unset rather than hiding the row. Evidence: typecheck + bundle + quickstart step 2 — this is a component, so there is no unit path
- [ ] T047 [US1] Render the existing chip presentation when the flag is OFF in mobile/src/app/task/[id].tsx (M-01c). The screen carries both presentations behind the flag read
- [ ] T048 [P] [US1] Build the project picker in mobile/src/features/tasks/ProjectPicker.tsx — M-02 default, loading, empty-first-run, offline-never-fetched (with "None" still available), error
- [ ] T049 [P] [US1] Build the Tag picker in mobile/src/features/tasks/TagPicker.tsx — M-03 states, including that in offline-never-fetched the task's own attached Tags stay listed and detachable, sourced from the task rather than the uncached list
- [ ] T050 [US1] Wire the rows to the pickers and the queue in mobile/src/features/tasks/useClassificationQueue.ts, with drain on foreground and after a successful request
- [ ] T051 [US1] Add the last-synced footer to mobile/src/app/task/[id].tsx as a live region announcing only on material change (SC-004, FR-007 — no per-change markers anywhere)
- [ ] T052 [US1] Run quickstart "Manual end-to-end check" steps 1–5 and record the SC-006 interaction count against the ceiling in `design.md`'s affordance map

**Checkpoint**: US1 is independently demonstrable. This is the MVP.

---

## Phase 4: User Story 2 (P2) — create a project or Tag without leaving the task

**Goal**: a name typed in a picker becomes a real project or Tag and is attached
in one move, and an existing match is offered rather than duplicated.

**Independent test**: type a new name, create, see it attached; type an existing
name, be offered the existing one.

- [ ] T053 [P] [US2] Write the failing integration assertion `006-FR-004` in mobile/integration/run.ts that create-then-attach lands both the new entity and the task's reference in one observable outcome
- [ ] T054 [US2] Add the inline create row to mobile/src/features/tasks/ProjectPicker.tsx, using `matchExisting` to offer an existing project instead of creating a duplicate (FR-005)
- [ ] T055 [US2] Add the same to mobile/src/features/tasks/TagPicker.tsx
- [ ] T056 [US2] Disable the create affordance offline **with its reason stated in text**, before it is tapped, in both pickers (FR-016) — never colour alone
- [ ] T057 [US2] Preserve the typed name and the existing classification when creation fails, so the person retries without retyping. Evidence: quickstart "Manual end-to-end check" step 5

**Checkpoint**: US2 demonstrable on top of US1.

---

## Phase 5: User Story 3 (P3) — it works with no connection, and nothing is lost

**Goal**: classification works offline, survives a restart, resolves conflicts by
asking, and never crosses identities.

**Independent test**: `quickstart.md` offline, expiry, conflict and identity
checks all pass.

- [ ] T058 [P] [US3] Write the failing integration assertion `006-FR-017` in mobile/integration/run.ts, classification-specific: after two PATCHes with the same key, the task's `revision` advanced exactly once and `project_id` equals the intended value
- [ ] T059 [P] [US3] Write the failing integration assertion `006-FR-008` in mobile/integration/run.ts for a stale `expected_revision` → 409 on a classification change
- [ ] T060 [US3] Build the conflict sheet in mobile/src/features/tasks/ConflictSheet.tsx per M-04: three labelled rows, the first sourced as what the device last showed **with its age**, the "changed more than once" line when `serverRevision - observedRevision > 1`, the non-chosen button disabled while sending, correlation id
- [ ] T061 [US3] Handle the Tags and combined-field conflict layout in mobile/src/features/tasks/ConflictSheet.tsx — one heading per changed field, each with its own three-row diff, stacked vertically; three tag sets side by side do not fit 390px
- [ ] T062 [US3] Build the discard-unsent sheet in mobile/src/features/tasks/DiscardUnsentSheet.tsx per M-05: count only, never a list; live-decrementing; discard blocked while any entry is `sending`, since the client cannot abort an in-flight send
- [ ] T063 [US3] Gate both identity transitions on the sheet in mobile/src/app/settings.tsx — sign-out **and** server change. These are the only call sites and were previously unlisted, so the sheet would have shipped with no caller
- [ ] T064 [US3] Gate the remaining `signOut` call site in mobile/src/app/sign-in.tsx
- [ ] T065 [US3] Add the expired-unsent-work notice to mobile/src/app/task/[id].tsx naming the field and what it reverted to, with a labelled "Dismiss" button in tab order after the affected row (FR-018, SC-003)
- [ ] T066 [US3] Add the account-level dismiss-once expiry notice with the total, on whichever task screen or list opens next after a sweep — triage happens from lists, so a per-task banner alone leaves FR-018's MUST unmet
- [x] T067 [US3] Persist the last server `Date` header seen and require the expiry test to pass against it too, in mobile/src/features/tasks/classificationQueue.storage.ts
- [ ] T068 [US3] Implement the >24h drain rule in mobile/src/features/tasks/useClassificationQueue.ts: past `firstSentAt + 24h` the drain re-reads the task first, then drops the entry if the server already holds the intended value or re-presents it against the current revision with a new key and refreshed `originalValue`
- [ ] T069 [US3] Run the quickstart offline, expiry, conflict and identity checks and record the results

**Checkpoint**: all three stories demonstrable.

---

## Phase 6: Polish & cross-cutting

- [ ] T070 [P] Verify no per-change marker exists anywhere — grep `mobile/src` for marker/pending/unsent decoration and confirm the only surfaces are the last-synced footer and the discard sheet (FR-007)
- [ ] T071 [P] Confirm `git diff --stat` shows no change to backend/app/api/tasks.py or the web client (FR-014)
- [ ] T072 [P] Confirm the forbidden term does not appear in any new surface (FR-013, ADR-0006 — "Tag", never "Context")
- [ ] T073 Run `scripts/check_requirement_coverage.py` and confirm all 30 ids (FR-001–FR-021, SC-001–SC-009) resolve to a named check
- [ ] T074 Run `make verify-all` and fix what it surfaces
- [ ] T075 Confirm the mobile coverage floor in mobile/coverage-floor.json ratchets up rather than down
- [ ] T076 Update `review-history.md` with the implementation outcome and any finding that proved wrong in practice

---

## Dependencies

```
Phase 1 (setup)
   └─▶ Phase 2 (foundational) ── blocks everything
          ├─▶ Phase 3  US1 (P1)  ── MVP, independently shippable
          │      └─▶ Phase 4  US2 (P2)  ── needs US1's pickers
          └─▶ Phase 5  US3 (P3)  ── needs Phase 2's queue; independent of US2
                 └─▶ Phase 6 (polish)
```

US3 depends on the foundational queue rather than on US1's screens, so it can
proceed in parallel with US2 once Phase 3 lands.

## Parallel opportunities

- **Phase 2**: T005, T009, T011, T014, T016, T018, T020, T023–T028, T030, T032, T034, T036 are all independent failing tests in different files — write them together, then implement against them.
- **Phase 3**: T042–T045 (integration assertions) in parallel; T048 and T049 (the two pickers) in parallel.
- **Phase 5**: T058 and T059 in parallel.
- **Phase 6**: T070, T071, T072 are independent greps.

## MVP scope

**Phase 1 + Phase 2 + Phase 3 (US1).** That delivers the whole stated problem —
a person classifies a task on the phone instead of reopening the laptop. US2 is
convenience; US3 is robustness. Both are real, and neither is the reason the
feature exists.

Note that Phase 2 is unusually large for this feature, and deliberately so: the
offline queue, the identity substrate and the clock discipline are prerequisites
for US1 behaving correctly the first time it is used on a train, not extras that
US3 adds later.
