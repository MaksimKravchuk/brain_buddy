# Tasks: Lean external-agent relay

**Input**: `spec.md`, `plan.md`, and `backlog.md`
**Execution**: Release-essential scope only; optional follow-ups remain in backlog.
Checkboxes record artifacts present in this bottom specification layer only. Backend,
web, mobile, and release work remain unchecked here; the release-controls layer may mark
cumulative completion after the corresponding artifacts and gates exist in the stack.

## Phase 1 — Secure backend relay

- [ ] T001 Add failing tests for encrypted/non-returned credentials, key handling, owner isolation, and account purge.
- [ ] T002 Implement owner-scoped connection/run/event/audit repository and encryption boundary.
- [ ] T003 Add failing SSRF, resolution, redirect, TLS, timeout, and response-bound tests.
- [ ] T004 Implement bounded HTTPS connector egress and capability test/start/reply/cancel adapter.
- [ ] T005 Add failing service/API tests for reauthentication, manifest confirmation, barrier-concurrent duplicate start/reply/cancel convergence, idempotency, event authentication/replay/order, honest projection, retention, disconnect, and correlation IDs.
- [ ] T006 Add deterministic backend/API tests for the complete FR-019 `OFF` matrix: block connection create/update/test, credential rotate/mutation, hand-off preview, and fresh dispatch; preserve authenticated owner-scoped connection/run reads, safe existing-run reply/cancel, authenticated inbound reports, retention maintenance, and account purge.
- [ ] T007 Implement agent schemas, service, routes, feature flag, container wiring, and standard OpenAPI errors.

## Phase 2 — Web journey

- [ ] T008 Add failing client/hook tests for connection, preview/confirm, run, reply, and cancellation contracts.
- [ ] T009 Implement Connected agents setup/test/rotate/disconnect under the feature flag.
- [ ] T010 Add failing task-surface tests for reviewed context, honest states, blocked reply, result, stopped reporting, and unsupported controls.
- [ ] T011 Wire hand-off and run projection into real task detail/list surfaces and preserve existing design patterns.

## Phase 3 — Expo iOS journey

- [ ] T012 Add failing API, guard, state-machine, and task-section tests, including rollout-`OFF` coverage proving that new connection/test/rotate/dispatch affordances are absent while an existing run remains monitorable and its supported safe reply/cancel controls remain available.
- [ ] T013 Implement connection settings, reviewed hand-off sheet, run monitor, reply/cancel guards, and polling/offline semantics.
- [ ] T014 Wire `TaskAgentSection` into the real Expo task detail route so existing-run monitoring and supported safe reply/cancel remain mounted when `agentRelayEnabled` is `OFF`; apply the flag only to new connection/test/rotate and hand-off/dispatch affordances.
- [x] T015 Add EAS development/preview/production profiles without credentials.

## Phase 4 — Release evidence

- [x] T016 Separate optional work into `backlog.md` and add production/TestFlight/App Store runbook.
- [ ] T017 Run full backend, web, mobile, Expo export, spec, and diff gates; fix changed-path failures. (External/canonical exact-candidate evidence is not yet recorded.)
- [ ] T018 Commit a clean focused candidate, then complete two independent implementation reviews — one web and one iOS — with both reviews bound to that exact candidate SHA and no blockers; any candidate change invalidates both reviews until repeated on the new SHA.
- [ ] T019 Open the ASK PR and require evidence that both T018 reviews and required CI cover the same exact candidate SHA; landing remains blocked pending separate explicit ASK merge authority, which no review, CI result, or prior semantic approval supplies.
- [ ] T020 Verify protected main landing and Fly production smoke with internal rollout.
- [ ] T021 Build and smoke TestFlight, submit to Apple, and verify App Store availability.

## Guardrails

- Never call a connector in automated tests; use deterministic fakes.
- Never return/log credentials or relayed content.
- Never retry ambiguous accepted work under a new run/key.
- Never translate agent completion into Brain Buddy task completion.
- Never present unsupported reply/cancel/progress controls.
- Never bypass ASK review, exact-SHA CI, Apple credentials, or App Store review.
