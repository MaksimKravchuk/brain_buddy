# External-agent relay specification quality checklist

**Purpose**: Verify the lean BYOA relay contract is bounded and testable.
**Created**: 2026-08-09
**Feature**: `specs/006-external-agent-relay/spec.md`

## Product boundary

- [x] Brain Buddy is a relay, not the owner or verifier of the external runtime.
- [x] Hermes is a reference connector rather than a permanent dependency.
- [x] Task lifecycle remains user-owned; completion copy is **Agent reported complete**.
- [x] Provider hosting, tools, cost, reliability, safety, and output remain user responsibilities.
- [x] Marketplace, managed hosting, multi-agent chains, and workflow builders are out of scope.

## Consent, state, and capability honesty

- [x] The exact outbound task/context manifest is reviewed before dispatch.
- [x] Duplicate start/reply/cancel commands have stable idempotency identities.
- [x] Accepted, running, blocked, completed, failed, cancelled, and stopped-reporting semantics are explicit.
- [x] Reply/cancel controls are omitted when unsupported.
- [x] No fabricated percentage, stage, ETA, success, or verified completion is allowed.

## Security and ownership

- [x] Owner isolation, recent reauthentication, encrypted credentials, and non-disclosure are explicit.
- [x] SSRF, DNS resolution, redirect, TLS, and destination-class rules are explicit.
- [x] Inbound event authentication, replay prevention, monotonic versions, and size limits are explicit.
- [x] Inert text and safe HTTPS result-link behavior are explicit.
- [x] Retention, disconnect, account purge, and correlation-ID expectations are explicit.

## Delivery quality

- [x] Web and iOS setup, reviewed hand-off, run monitor, blocked reply, and feature-flag behavior are testable.
- [x] Backend API/service/repository/egress/secret tests are identified.
- [x] Production rollout begins fail-closed for an internal cohort.
- [x] Optional follow-ups are separated into `backlog.md`.
- [x] No unresolved placeholder is required for the minimum release slice.

## Result

PASS — bounded minimum release contract; implementation and production evidence remain subject to the gates in `plan.md` and `docs/external-agent-relay-release.md`.
