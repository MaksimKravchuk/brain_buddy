# Implementation Plan: Assign project and tags from the mobile task screen

**Branch**: `claude/multi-agent-plugin-search-37qezh` | **Date**: 2026-08-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-mobile-task-classification/spec.md`

## Summary

Make the mobile task detail screen's project and Tag rows editable, add
pick-or-create pickers behind them, and hold changes on the device when there
is no connection. Exposure sits behind a server-owned flag defaulting to OFF.

The technical shape is unusually constrained by what already exists, and the
research below is mostly the discovery that **nothing new has to be invented**:
the wire contract, the create endpoints, the flag delivery channel and the
storage mechanism are all in place and in use. The genuinely new code is a
device-local queue and the pure logic around it.

## Technical Context

**Language/Version**: TypeScript 5.x (strict), React Native via Expo SDK; Python 3.11 for the one backend line

**Primary Dependencies**: `expo-router`, `@tanstack/react-query`, `@react-native-async-storage/async-storage` — all already in `mobile/`. No new dependency is added.

**Storage**: `AsyncStorage` for the pending-change queue, the same mechanism `mobile/src/config/serverUrl.ts` already uses for `bb.serverUrl`. Server-side storage is unchanged.

**Testing**: Jest for the extracted pure modules; `make integration-mobile` against a disposable local backend; `make typecheck-mobile` and `make build-mobile`. `mobile/` has **no component-render test library**, which is the single biggest force shaping this plan — see Testing strategy.

**Target Platform**: iOS first, via Expo Go. 390×851 is the design viewport.

**Project Type**: mobile app feature, plus one backend configuration line

**Performance Goals**: no new target. The feature does not touch the CRT canvas, so the ~200-node responsiveness requirement does not apply. Picker lists are the existing project/Tag sets, tens of items, not thousands.

**Constraints**: no new task route (`backend/app/api/tasks.py` is ASK-classified by exact path); offline-capable by requirement, not by aspiration; the queue must be bound to account and server.

**Scale/Scope**: 7 designed screens/states, 16 functional requirements, 3 user stories. Roughly 6 new mobile modules, 1 backend line, 1 client flag read.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design — see the bottom of this document.*

**Spec workflow.** `spec.md` is current. Its `## Clarifications` section records the 2026-08-11 session including the reversal on the not-sent marker, and both sign-off decisions are reflected in FR-007, SC-004 and the M-05 rows of `design.md`. Planning follows the clarifications rather than preceding them.

**Consent & Safety.** No new consent surface: no new personal data is collected and no AI provider is involved. One new place account content rests — the device queue — and FR-011 bounds its lifetime to a single account-and-server pairing, clearing on any identity transition. No real data, secrets, transcripts, paths or fingerprints are committed or logged; the queue holds task ids and classification ids the device already had.

**Tests.** Failing first, then passing: the queue reducer's coalescing and identity-binding tests (`006-FR-010`, `006-FR-011`), the conflict-decision table (`006-FR-008`), the offline create-guard (`006-FR-016`), the single-flight and stable-key rules (`006-FR-017`), and an integration test driving `PATCH /tasks/{id}` with a stale `expected_revision` to prove the rejection path is the ordinary one (`006-FR-008`). A second integration test sends one entry's key twice and asserts one applied change, which is the only honest proof of `006-FR-017` — a unit test would assert that the mock was written. Edge cases from the spec — a queued change for a deleted task, a Tag added then removed before the drain, a mid-send sign-out — are table cases in the reducer suite.

**Contracts.** **No contract changes.** `TaskUpdateRequest` already carries `project_id`, `tag_ids` and the required `expected_revision`; `POST /projects` and `POST /tags` already exist and are already called from `mobile/src/api/client.ts` with idempotency keys. The only backend edit is adding one name to `KNOWN_FEATURE_FLAGS` in `backend/app/core/config.py`, which widens an allow-list and breaks nothing. `/auth/me` already returns `feature_flags`, so the flag needs no new endpoint either. FR-017 needs no contract change
either, and this was checked rather than assumed: `backend/app/api/tasks.py`
already *requires* an `Idempotency-Key` header on every task mutation, and
`mobile/src/api/client.ts` already takes the key as a caller-supplied argument
rather than minting one per call. The queue entry owning its key is therefore a
change to who generates the value, not to the wire.

**Observability.** Every user-visible failure carries the correlation id of the failed request (FR-012), matching the rest of the product. The queue logs enqueue, drain-attempt and drain-outcome with the correlation id and the task id — never the classification names, which are user content.

**Mobile/resilience/performance.** This is the resilience story, not an afterthought to it: the queue exists because the human chose deferred send over an honest error. Interruption behaviour is specified per ADR-0002 — a change survives app closure (FR-009), a conflict prompt dismissed by backgrounding counts as unanswered rather than as a decision, and the discard warning is the guard before destructive loss. No canvas impact.

**Delivery boundary.** `tasks.md` from the next stage is portable planning input. Isolated worktree, TDD, independent verification, ADR-0008 landing and CI gates remain authoritative. This plan changes none of that.

**Design citation.** This feature has a user-visible surface and cites
[`design.md`](./design.md), signed off 2026-08-11. Each implementation section
below names the screen and state ids it realizes:

| implementation section | design ids realized |
|---|---|
| Task screen classification rows | M-01 default, empty-first-run, error, partial-failure, flag-OFF (M-01c) |
| Pickers | M-02 all states, M-03 all states including the offline create-guard |
| Queue and drain | M-01b, plus M-01's offline row and the last-synced footer |
| Conflict resolution | M-04 all states including `dismissed` |
| Identity transitions | M-05 all states |

## Project Structure

### Documentation (this feature)

```text
specs/006-mobile-task-classification/
├── intake.md            # business intake, /speckit-interview
├── spec.md              # what and why, with Clarifications
├── design.md            # screens, states, affordance map — signed off
├── design/*.html        # 7 static screens
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1 — records that no contract changes
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
backend/
└── app/core/config.py                      # +1 name in KNOWN_FEATURE_FLAGS (FR-015)

mobile/src/
├── auth/SessionProvider.tsx                # +1 flag read, fail closed, beside voiceEnabled
│                                           # + persist accountId, + distinguish 401 from offline
├── features/tasks/classificationCache.ts   # NEW: project/Tag lists survive a cold start offline
├── api/client.ts                           # unchanged — updateTask/createProject/createTag exist
├── features/tasks/
│   ├── classificationQueue.ts              # NEW pure: enqueue, coalesce, bind identity, clear
│   ├── classificationQueue.storage.ts      # NEW thin AsyncStorage adapter
│   ├── conflictDecision.ts                 # NEW pure: what a rejection means and what may follow
│   ├── syncStatus.ts                       # NEW pure: last-synced formatting and staleness
│   ├── useClassificationQueue.ts           # NEW hook: drain on foreground and after a success
│   ├── ProjectPicker.tsx                   # NEW screen component (M-02)
│   ├── TagPicker.tsx                       # NEW screen component (M-03)
│   ├── ConflictSheet.tsx                   # NEW (M-04)
│   └── DiscardUnsentSheet.tsx              # NEW (M-05)
└── app/task/[id].tsx                       # rows become editable; footer shows last synced

mobile/src/features/tasks/__tests__/        # Jest over the pure modules only
mobile/integration/                         # real client vs disposable local backend
```

The integration path is `mobile/integration/`, which is what `make
integration-mobile` actually runs. An earlier draft of this plan wrote
`mobile/tests/integration/`, a directory that does not exist; the constitution
requires plans to name real paths, and a reviewer caught it.

**Structure decision.** Four of the nine new mobile files are pure modules with
no React import. That split is forced rather than stylistic: with no
component-render test library in `mobile/`, anything left inside a component is
untestable except through the integration harness, so every rule worth asserting
— coalescing, identity binding, conflict outcomes, staleness — is pushed out of
the components and into functions that take state and return state.

### Two mechanisms the review found missing

Both are required by requirements already agreed, not by new ones. Neither was
in the first draft of this plan, and without either the feature does not work
after the case it exists for — a cold start with no connection.

**Identity must be readable offline.** The storage key is
`<serverUrl>.<accountId>`, but today the only source of `accountId` is
`/auth/me`, which is exactly the call that fails offline. On a cold start with
no connection the key cannot be constructed, so the queue cannot be read, so
FR-009 fails. `SessionProvider` therefore persists the account id alongside the
server URL on every successful `/auth/me`, and the queue reads that rather than
the live session.

**The pickers need a cache that survives a cold start.** `design.md` says
existing projects and Tags stay "selectable from cache" offline. React Query's
cache is in memory and `mobile/` installs no persister, so after a cold start
that cache is empty and the claim is false — a person offline would see empty
pickers and could classify nothing, which is the whole of FR-006. The project
and Tag lists are therefore written to `AsyncStorage` on every successful fetch
and read back when the fetch fails. This is a list of names the device already
displayed, under the same identity key as the queue and cleared with it.

## Testing strategy

The constraint is unusual enough to state plainly: **`mobile/` cannot render a
component in a test.** Three consequences shape the whole plan.

1. **Logic lives outside components.** The queue reducer, the conflict decision
   table, and the sync-status formatter are pure functions over plain data.
   These carry the `006-FR-###` ids and are where TDD actually happens.
2. **Wire behaviour is proved by integration, not by mocks.**
   `make integration-mobile` runs the real API client against a disposable
   local backend. The stale-`expected_revision` rejection is exercised there
   for real, because a mocked 409 would prove only that the mock was written.
3. **Rendering is proved by typecheck and build.** `make typecheck-mobile` and
   `make build-mobile` (Metro bundle) are the evidence that the components
   compile and bundle. That is genuinely weaker than a render test, and the
   acceptance stage must not be allowed to describe it as more than it is.

The end-to-end criterion the human named — change it on the phone, see it in
the web client — is a manual check. It is recorded as such in `quickstart.md`
rather than dressed up as automation.

### Every User Story 1 scenario, and what proves it

The review found three of the five with no test path at all. Each now has one,
and where the only honest answer is "a person looks at it", that is what it
says — the acceptance auditor grades against this table.

| scenario | evidence |
|---|---|
| 1 — set a project on a task that had none | integration: `PATCH` with `project_id`, re-read shows it |
| 2 — clear a project | integration: `PATCH` with `project_id: null`, re-read shows none. The reducer's `null`-vs-`undefined` case is a unit test — `null` must survive coalescing as a deliberate clear |
| 3 — add two tags, order-independent | reducer unit test over both orders producing one set; integration confirms the set round-trips |
| 4 — remove one of two tags | integration: `PATCH` with the one-element set. Reducer test that removing a tag added in the same offline session leaves no entry at all |
| 5 — pick a second project, only the newer survives | reducer unit test: two project changes coalesce to one entry, not two; integration confirms the server holds one project |

Scenarios 2, 4 and 5 are all cases where the wrong answer is silent — an
un-cleared project, a re-attached tag, a stale project — which is why each is
pinned at the reducer, where the failure is a diff, and not only at the wire.

## Risks

**The queue is the whole risk surface.** Everything else is wiring existing
calls to existing endpoints. If the reducer coalesces wrongly, a person loses a
classification silently, and with no per-change marker and a count-only discard
warning there is no surface that would show them. That is why the reducer is
pure and table-tested first, before any component touches it.

**Two decisions taken at sign-off narrow the safety net**, and the plan does not
reopen them — it records that they raise the cost of a reducer bug: there is no
not-sent marker and no list in the discard warning, so no surface in the app
names an unsent change.

**The flag is exposure control, never authorization.** AGENTS.md is explicit and
`dependencies.py` already enforces per-owner filtering server-side. Nothing in
this feature may treat the flag as a permission check.

## Complexity Tracking

| addition | why it is not avoidable | cheaper alternative rejected |
|---|---|---|
| Device-local queue | The human chose deferred send over an honest error when asked directly | An error toast — offered and declined |
| Conflict resolution UI | `expected_revision` is required, so rejection is ordinary, not rare | Last-write-wins — silently discards someone's work |
| Four pure modules | No component-render test library; logic inside components is untestable | Testing through the integration harness only — slower and it would not cover the table cases |

Nothing else new. No new dependency, no new endpoint, no new backend module.

## Constitution Check — post-design re-evaluation

Re-checked after Phase 1. No gate moved. Two notes worth carrying to review:

- **Contracts stayed genuinely unchanged.** Phase 1 confirmed the wire shape is
  sufficient as-is; `contracts/README.md` records that finding explicitly so a
  reviewer sees a checked claim rather than an absence.
- **The testing gate passes on a technicality worth naming.** "Tests that fail
  first and then pass" is satisfied by the pure modules and the integration
  test. It is not satisfied for the components themselves, and no amount of
  planning fixes that inside this feature — it is a repository-level gap that
  this run has surfaced. Flagged for review rather than smoothed over.
