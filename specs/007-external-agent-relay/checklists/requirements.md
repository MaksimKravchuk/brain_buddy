# External-agent relay specification quality checklist

**Purpose**: Verify the lean BYOA relay contract is bounded and testable.
**Created**: 2026-08-09
**Feature**: `specs/007-external-agent-relay/spec.md`

## Product boundary

- [x] Brain Buddy is a relay, not the owner or verifier of the external runtime.
- [x] Hermes is a reference connector rather than a permanent dependency.
- [x] Task lifecycle remains user-owned; completion copy is **Agent reported complete**.
- [x] Provider hosting, tools, cost, reliability, safety, and output remain user responsibilities.
- [x] Marketplace, managed hosting, multi-agent chains, and workflow builders are out of scope.

## Consent, state, and capability honesty

- [x] The exact outbound task/context manifest is reviewed before dispatch.
- [x] Barrier-concurrent duplicate start/reply/cancel commands converge on one durable winner and one connector action.
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

## Prospective landing contract

- [x] The plan and tasks require two distinct independent implementation reviews: one web and one iOS.
- [x] Both reviews and required CI are bound to the same exact candidate SHA and invalidated by a candidate change.
- [x] Separate explicit ASK merge authority remains required; neither review, CI, nor prior semantic approval supplies it.
- [x] These checks validate the landing contract only and do not claim that its prospective evidence or approval already exists.

## Result

PASS — bounded minimum release contract only; this is not implementation review,
exact-candidate approval, or merge authority. The prospective landing evidence itself
remains unsatisfied and subject to the gates in `plan.md`. The pending release runbook is
non-normative until its release-controls layer lands and validates it against FR-019.
