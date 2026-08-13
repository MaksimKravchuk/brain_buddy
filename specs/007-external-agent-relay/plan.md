# Implementation Plan: Lean external-agent relay

**Feature Branch**: `007-external-agent-relay-lean-v1` (as recorded in `spec.md`; the delivery worktree branch name varies per run and is not normative)
**Date**: 2026-08-09
**Spec**: `specs/007-external-agent-relay/spec.md`
**Intake**: `specs/007-external-agent-relay/intake.md`
**Design**: `specs/007-external-agent-relay/design.md`

> This lean delivery plan replaces the archived non-converging requirements attempt. It records only the architecture and release gates required for the production slice; optional work is in `backlog.md`.

## Summary

Add an owner-scoped BYOA relay to the existing FastAPI/React/Expo modular monolith. A user connects and verifies an HTTPS agent endpoint through a governed, server-allowlisted connector adapter, reviews the exact task/context manifest, dispatches once, and monitors authenticated events from the canonical task. Owners cannot select an arbitrary URL/tool transport. Brain Buddy reports what the agent said without owning execution or completing the task.

## Technical context

- **Backend**: Python 3.11, FastAPI, Pydantic, SQLite repositories, httpx, cryptography.
- **Web**: TypeScript, React, React Query, Vite, Vitest.
- **iOS**: Expo SDK 57, Expo Router, React Native, React Query, Jest, EAS cloud builds.
- **Storage**: owner-scoped connection, run, event-ID, command/idempotency, and audit records in the existing data directory; credential payload encrypted with `BRAIN_BUDDY_AGENT_RELAY_KEYS`.
- **Rollout**: existing `external_agent_relay` feature flag, initially internal only.
- **Release**: ASK PR with two independent implementation reviews — one web and one iOS — and required CI all bound to the exact candidate SHA; landing additionally requires separate explicit ASK merge authority. Fly deploy, EAS TestFlight, and App Store review remain subsequent gates.

## Architecture

1. **Connection boundary** — API/service/repository manage owner-scoped endpoints selected through governed server-allowlisted connector adapters, encrypted credentials, capability disclosure, test, rotation, and disconnect. No owner-controlled arbitrary URL/tool adapter is permitted. Sensitive mutations require recent server-verified reauthentication at the account's highest enrolled assurance, using the current server-supported reauthentication mechanism, and rate-limit failures.
2. **Safe egress** — HTTPS only; validate scheme/host, resolve every attempt, reject disallowed address classes, pin each socket to one address from that validated result while preserving hostname-based TLS verification, disable unsafe redirects, cap response bytes/time, and never log secret/content payloads. Resolver-change/DNS-rebinding tests prove that the connector cannot perform a second unbound lookup and reach a disallowed address.
3. **Reviewed hand-off** — preview creates a versioned immutable manifest/token. Confirmation requires the same manifest plus an idempotency key and reserves one run before outbound start.
4. **Authenticated reporting** — connector events sign the complete body with timestamp and connection identity. The service validates freshness, owner/run correlation, event ID, monotonic version, transition, and payload bounds atomically.
5. **Honest projection** — one server projection supplies compact/detail labels. Sent, connector state, stopped-reporting, pending reply/cancel, disconnected connection, and content expiry remain separate facts.
6. **Clients** — web and iOS share server contracts, review outbound content before
   dispatch, and display capability-gated controls. The account flag gates the *new-work*
   entry points: creating or updating a connection, testing a connection, rotating or
   otherwise mutating credentials, the hand-off preview, and fresh dispatch. It does not
   gate owner-scoped reads or the existing-run section:
   when rollout is `OFF`, monitoring of already-dispatched runs stays reachable and
   supported safe `reply`/`cancel` controls remain available for existing non-terminal runs
   whose connector and connection state support that command, matching FR-019 and the
   rollback contract below. Closing a client does not cancel a run.

## Constitution check

- **Consent**: exact content and external-copy notice are visible before dispatch.
- **Safety**: credentials encrypted/non-readable; SSRF/replay/cross-owner tests are release gates.
- **Honesty**: no runtime ownership, auto-completion, silent resend, or fabricated progress.
- **TDD**: focused backend, web, and mobile tests cover new behavior; full suites remain required.
- **Operations**: feature flag `OFF` is the first rollback. It blocks connection
  create/update/test/credential rotation, preview, and fresh dispatch while owner-scoped reads and supported safe
  reply/cancel commands for existing non-terminal runs remain available; inbound reports
  and privacy maintenance continue for already-dispatched runs.
- **Scope**: no managed runtime, marketplace, payments, fan-out, or workflow builder.

## Affected surfaces

- `backend/app/api/agents.py`, agent schemas/module, config/container/account purge, API contract tests.
- `frontend/src/api/*agent*`, `features/agents/`, task detail/list and settings navigation.
- `mobile/src/api/*`, `agents/`, `features/agents/`, agent settings route, and real task detail.
- `mobile/eas.json`, release runbook, spec/checklist/tasks/backlog artifacts.

## Verification and release gates

1. Focused agent suites pass on backend, web, and iOS.
2. Full backend pytest reaches repository coverage threshold and OpenAPI contract tests pass.
3. Full web Vitest/typecheck/build pass.
4. Full mobile Jest/typecheck/integration and `expo export --platform ios` pass.
5. Spec checker and `git diff --check` pass.
6. Two independent implementation reviews — one covering web and one covering iOS — find no blocker on the same exact candidate SHA; any candidate change invalidates both reviews until repeated on the new SHA.
7. Required CI passes on that same exact candidate SHA, and landing occurs only with separate explicit ASK merge authority. No review, CI result, or prior semantic approval supplies that authority. The Fly workflow then proves and smokes the deployed SHA.
8. EAS production build is tested in TestFlight before App Store submission and clean-device availability verification.

The release-controls layer will add `docs/external-agent-relay-release.md`. Until that
layer lands, the runbook path is pending and non-normative; the rollback contract in
FR-019 and this plan governs implementation. The release layer may make the runbook
normative only after it exists and is validated against those requirements.
