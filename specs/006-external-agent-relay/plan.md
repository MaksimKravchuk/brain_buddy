# Implementation Plan: Lean external-agent relay

**Branch**: `brain-buddy/t_f6b6162c-outcome-lean-v1-external-agent-relay-and`  
**Date**: 2026-08-09  
**Spec**: `specs/006-external-agent-relay/spec.md`
**Intake**: `specs/006-external-agent-relay/intake.md`
**Design**: `specs/006-external-agent-relay/design.md`

> This lean delivery plan replaces the archived non-converging requirements attempt. It records only the architecture and release gates required for the production slice; optional work is in `backlog.md`.

## Summary

Add an owner-scoped BYOA relay to the existing FastAPI/React/Expo modular monolith. A user connects and verifies an HTTPS agent endpoint, reviews the exact task/context manifest, dispatches once, and monitors authenticated events from the canonical task. Brain Buddy reports what the agent said without owning execution or completing the task.

## Technical context

- **Backend**: Python 3.11, FastAPI, Pydantic, SQLite repositories, httpx, cryptography.
- **Web**: TypeScript, React, React Query, Vite, Vitest.
- **iOS**: Expo SDK 57, Expo Router, React Native, React Query, Jest, EAS cloud builds.
- **Storage**: owner-scoped connection, run, event-ID, command/idempotency, and audit records in the existing data directory; credential payload encrypted with `BRAIN_BUDDY_AGENT_RELAY_KEYS`.
- **Rollout**: existing `external_agent_relay` feature flag, initially internal only.
- **Release**: reviewed ASK PR, exact-SHA CI, protected main landing, automatic Fly deploy; EAS TestFlight then App Store review.

## Architecture

1. **Connection boundary** — API/service/repository manage owner-scoped endpoints, encrypted credentials, capability disclosure, test, rotation, and disconnect. Sensitive mutations verify the current account password and rate-limit failures.
2. **Safe egress** — HTTPS only; validate scheme/host, resolve every attempt, reject disallowed address classes, disable unsafe redirects, cap response bytes/time, and never log secret/content payloads.
3. **Reviewed hand-off** — preview creates a versioned immutable manifest/token. Confirmation requires the same manifest plus an idempotency key and reserves one run before outbound start.
4. **Authenticated reporting** — connector events sign the complete body with timestamp and connection identity. The service validates freshness, owner/run correlation, event ID, monotonic version, transition, and payload bounds atomically.
5. **Honest projection** — one server projection supplies compact/detail labels. Sent, connector state, stopped-reporting, pending reply/cancel, disconnected connection, and content expiry remain separate facts.
6. **Clients** — web and iOS share server contracts, gate all entry points by the account flag, review outbound content, and display capability-gated controls. Closing a client does not cancel a run.

## Constitution check

- **Consent**: exact content and external-copy notice are visible before dispatch.
- **Safety**: credentials encrypted/non-readable; SSRF/replay/cross-owner tests are release gates.
- **Honesty**: no runtime ownership, auto-completion, silent resend, or fabricated progress.
- **TDD**: focused backend, web, and mobile tests cover new behavior; full suites remain required.
- **Operations**: feature flag is the first rollback; inbound reports remain available for already-dispatched runs.
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
5. Spec checker and `git diff --check` pass; independent security/correctness review finds no blocker.
6. Reviewed ASK PR lands only after exact-SHA CI; Fly workflow proves and smokes the deployed SHA.
7. EAS production build is tested in TestFlight before App Store submission and clean-device availability verification.

Rollback and operational details are normative in `docs/external-agent-relay-release.md`.
