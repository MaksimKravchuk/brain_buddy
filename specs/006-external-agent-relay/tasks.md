# Tasks: Lean external-agent relay

**Input**: `spec.md`, `plan.md`, and `backlog.md`  
**Execution**: Release-essential scope only; optional follow-ups remain in backlog.

## Phase 1 — Secure backend relay

- [x] T001 Add failing tests for encrypted/non-returned credentials, key handling, owner isolation, and account purge.
- [x] T002 Implement owner-scoped connection/run/event/audit repository and encryption boundary.
- [x] T003 Add failing SSRF, resolution, redirect, TLS, timeout, and response-bound tests.
- [x] T004 Implement bounded HTTPS connector egress and capability test/start/reply/cancel adapter.
- [x] T005 Add failing service/API tests for reauthentication, manifest confirmation, idempotency, event authentication/replay/order, honest projection, retention, disconnect, and correlation IDs.
- [x] T006 Implement agent schemas, service, routes, feature flag, container wiring, and standard OpenAPI errors.

## Phase 2 — Web journey

- [x] T007 Add failing client/hook tests for connection, preview/confirm, run, reply, and cancellation contracts.
- [x] T008 Implement Connected agents setup/test/rotate/disconnect under the feature flag.
- [x] T009 Add failing task-surface tests for reviewed context, honest states, blocked reply, result, stopped reporting, and unsupported controls.
- [x] T010 Wire hand-off and run projection into real task detail/list surfaces and preserve existing design patterns.

## Phase 3 — Expo iOS journey

- [x] T011 Add failing API, guard, state-machine, and task-section tests.
- [x] T012 Implement connection settings, reviewed hand-off sheet, run monitor, reply/cancel guards, and polling/offline semantics.
- [x] T013 Wire `TaskAgentSection` into the real Expo task detail route under `agentRelayEnabled`.
- [x] T014 Add EAS development/preview/production profiles without credentials.

## Phase 4 — Release evidence

- [x] T015 Separate optional work into `backlog.md` and add production/TestFlight/App Store runbook.
- [x] T016 Run full backend, web, mobile, Expo export, spec, and diff gates; fix changed-path failures.
- [ ] T017 Complete independent security/correctness review and commit a clean focused change.
- [ ] T018 Open reviewed ASK PR and require exact-SHA CI.
- [ ] T019 Verify protected main landing and Fly production smoke with internal rollout.
- [ ] T020 Build and smoke TestFlight, submit to Apple, and verify App Store availability.

## Guardrails

- Never call a connector in automated tests; use deterministic fakes.
- Never return/log credentials or relayed content.
- Never retry ambiguous accepted work under a new run/key.
- Never translate agent completion into Brain Buddy task completion.
- Never present unsupported reply/cancel/progress controls.
- Never bypass ASK review, exact-SHA CI, Apple credentials, or App Store review.
