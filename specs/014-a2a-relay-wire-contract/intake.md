# Business Intake: A2A relay wire contract

**Feature**: `specs/014-a2a-relay-wire-contract/`
**Interviewed**: 2026-09-03
**Interviewee**: Max (product owner)

<!--
  Produced by /speckit-interview before /speckit-specify. This is the record of
  what the human actually agreed to, in their own terms. It is not a
  specification: no schemas, no endpoints, no module boundaries. Where a
  heading did not apply, say why — never delete the heading.
-->

## The ask, as given

> надо сделать a2a, ты оркестратор. Доведи дело до конца, используй субагентов

Preceded in the same session by: "Ок, прогони assess-research по A2A", which produced
`.specify/assessments/a2a-relay-wire-contract/research.md`. Stage 0 note: the define,
shape and decide stages ran in parallel with this interview; the verdict in
`decision.md` is checked before `/speckit-specify` runs, and this intake is not adopted
into a feature directory unless that verdict is `go`.

## 1. Problem

- **Whose problem**: a BrainBuddy user who operates their own AI agent and wants to hand a task to it from BrainBuddy.
- **How it shows up today**: the external-agent relay (feature 007) speaks a bespoke connector envelope that no agent implements. Zero connections exist; the rollout flag is OFF. The "provider-agnostic" promise of 007 means "any agent whose operator writes a BrainBuddy-specific shim", which in practice is nobody.
- **What it costs**: the whole relay investment (about 5,500 backend lines plus web and iOS surfaces) delivers nothing to users; every future agent needs bespoke integration work; the A2A ecosystem (172 partner organisations, native support in the major agent frameworks and cloud agent runtimes) is unreachable.
- **If we build nothing**: the relay stays dark, and each connector still has to be hand-built per vendor.

## 2. Customer and persona

- **Primary**: a BrainBuddy user operating an A2A-capable agent they own: a personal self-hosted agent (Hermes/OpenClaw class) or a cloud-hosted agent (Amazon Bedrock AgentCore, Azure AI Foundry, Google ADK).
- **Secondary**: none. BrainBuddy does not host, run or verify agents.
- **Deployment shape**: multi-tenant service where each account is a single user; agent connections stay owner-scoped exactly as in 007.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| Stock A2A agents reachable end-to-end without agent-side modification | 0 | 2: the unmodified Hermes A2A plugin and an official a2a-sdk sample agent | no calendar deadline; medium appetite (weeks) |
| External starts created per confirmed hand-off across three identical replays | no connector exists | exactly 1 with both stock agents | same |
| 007 security suite (the SC-003 rejection cases) passing on the A2A wire | 100% on the bespoke wire | 100% on the A2A wire | same |
| Task surfaces showing one server projection of a run | web and iOS on the bespoke wire | web and iOS on the A2A wire | same |

These become the `SC-###` success criteria. An objective with no number
produces a spec the acceptance auditor cannot grade.

## 4. Scope boundary

**In scope**

- [ ] Replace the bespoke connector envelope with the A2A v1.0 protocol as the only wire contract; the generic HTTP connector is removed (it has zero consumers).
- [ ] Connect an A2A agent by its Agent Card, with bearer or API-key authentication, over public HTTPS.
- [ ] Disclose what the agent supports (streaming, push notifications, skills) and whether it implements the optional BrainBuddy extension.
- [ ] Hand off one task without blocking the user: BrainBuddy keeps the agent call alive in the background and treats an authenticated poll as the source of truth; push notifications only wake the poll.
- [ ] Guard against duplicate starts on BrainBuddy's side (look the run up by its context before any resend) and disclose the residual risk honestly for agents without the extension; agents with the extension get the strong guarantee.
- [ ] Optional BrainBuddy A2A extension that carries the strong single-start and ordered-reporting guarantees for agents that choose to implement it.
- [ ] Reply to an agent question and request cancellation through A2A when the agent supports them; unsupported controls stay hidden as in 007.
- [ ] Keep every 007 guarantee: consent manifest, recent reauthentication for sensitive operations, sealed secrets, HTTPS and public-address egress, honest state labels, 30/90-day retention, account purge, rollout-OFF semantics.
- [ ] Update the web and iOS surfaces so both show the same projection, including the degraded-mode disclosure.
- [ ] Work with the unmodified Hermes A2A plugin; an upstream patch may be proposed but nothing depends on it.

**Out of scope — explicitly confirmed by the human**

- [ ] BrainBuddy-owned agent hosting, runtime, tools or output verification (unchanged from 007).
- [ ] Multi-agent fan-out, routing and delegation chains.
- [ ] OAuth2 and mTLS authentication schemes and verification of signed Agent Cards (deferred, not rejected).
- [ ] Marketplace, billing, quotas.
- [ ] Automatic Task completion or verification of the agent's result (unchanged from 007).
- [ ] Keeping the bespoke envelope alongside A2A.
- [ ] Exposing BrainBuddy itself as an A2A server with an Agent Card.
- [ ] Changes to voice capture, capture review, Weekly Review or the canonical Task lifecycle.
- [ ] Depending on a Hermes patch or configuration change.

<!--
  Non-goals are the highest-value answers in the interview. Both lists were
  read back and confirmed; record the confirmation, not an assumption.
-->

**Confirmed by**: Max on 2026-09-03

## 5. Constraints

- **Deadline**: none; medium appetite (weeks).
- **Platform**: web and iOS (Expo).
- **Offline behavior**: as in 007: cached state labelled potentially stale, reply/cancel disabled offline rather than queued.
- **Must not break**: canonical Task ownership and lifecycle, session auth and owner scoping, account purge, the FR-004 egress policy (HTTPS, public addresses, DNS pinning), the Admin Portal rollout flag semantics, verified-trunk landing rules.
- **Budget / provider cost limits**: the user owns agent and provider costs; BrainBuddy adds no provider billing.

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management —
profile/email/password, ZIP data export, 14-day-grace deletion and purge — and
is never feature-flagged (see `docs/data-retention.md`). Record what **this
feature adds** to that baseline.

- **New durable records**: A2A task and context identifiers per run, the agent's discovered card metadata (name, skills, capabilities, auth scheme), and the extension-support flag per connection. No new content categories beyond 007.
- **Consent**: unchanged from 007: the hand-off review lists exactly what leaves BrainBuddy; sensitive connection operations require recent server-verified reauthentication.
- **Retention**: unchanged from 007: relayed content within 30 days, coarse audit within 90 days; card metadata follows the connection's lifetime.
- **Export**: as 007: covered where the ratified contract permits; secrets never exported.
- **Purge**: covered by the existing account purge; the new identifiers live inside the same owner-scoped records.
- **Residency / other obligations**: none new; the agent receives a separate copy that BrainBuddy cannot erase (already disclosed in 007).

## 7. Existing-system dependencies

- **Backend surfaces**: `app/modules/agents/` (connector, service, domain, repository, egress, secrets), `app/api/agents.py`, the `external_agent_relay` flag, the background maintenance thread.
- **Frontend surfaces**: `features/agents/` (connection settings, hand-off overlay, run section) and Task detail.
- **Mobile**: must change: `features/agents/` sheets and Task agent section.
- **AI providers**: not used by BrainBuddy; the agent is user-operated.
- **Primary loop impact**: no impact. The relay remains an optional evidence lane after a canonical Task exists.

## 8. Definition of done

What the human wants to see to believe it works. Observable, not "it works":

- [ ] A hand-off from a Task to an unmodified Hermes A2A plugin and to an official a2a-sdk sample agent completes end-to-end, and three identical replays of the confirmation produce exactly one agent task.
- [ ] The 007 security rejection cases (SC-003) all pass on the A2A wire with zero accepted state changes and no secret disclosure.
- [ ] Web and iOS show the same run projection, including the degraded-mode disclosure for agents without the extension.
- [ ] Exact-SHA review, CI and ASK landing authority as for 007.

## Deferred to /speckit-clarify

- [ ] Where the degraded-mode (no strong single-start guarantee) disclosure is shown: at connection time, at hand-off review, or both.
- [ ] Whether existing 007 connection records in non-production data are migrated or dropped (no production records exist; rollout is OFF).
- [ ] Whether the BrainBuddy A2A extension is published under a public extension URI so third-party agents can implement it, or stays private to the reference implementation.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| 007: "provider-agnostic BYOA protocol; Hermes only a reference connector" | 2026-09-03: A2A is the only wire contract | A2A is the provider-agnostic contract; the bespoke envelope is removed, Hermes stays the reference agent | Max, 2026-09-03 |
