# Problem Definition: External-agent relay speaks a wire no agent implements

- **Slug**: a2a-relay-wire-contract
- **Created**: 2026-09-03
- **Inputs used**: intake.md skipped (the idea was supplied directly by the product owner), research.md used

## Problem Statement

BrainBuddy's bring-your-own-agent relay (feature 007) promises a provider-agnostic hand-off, but it only speaks a bespoke BrainBuddy envelope that no agent implements — inside or outside the repository — so the number of agents an owner can actually hand a Task to is zero and the relay has stayed rollout-OFF since it was ratified. The agents its intended users operate (self-hosted Hermes/OpenClaw-class runtimes and cloud-hosted Bedrock AgentCore, Azure AI Foundry and Google ADK agents) already interoperate through a shared, Linux Foundation-governed agent-to-agent standard that BrainBuddy does not speak, so every one of them would need a hand-written BrainBuddy-specific shim before the promise means anything.

## Affected Users & Stakeholders

- **Users**: Operators of personal self-hosted agents (Hermes/OpenClaw class) — cannot hand a BrainBuddy Task to the agent they already run. The Hermes A2A plugin exists and answers the standard, but the relay cannot talk to it (research.md: Users & Demand; Prior Art). Demand for standard-based interop is observed in the Hermes community issue cluster, not among BrainBuddy users.
- **Users**: Operators of cloud-hosted agents (Bedrock AgentCore, Azure AI Foundry, Google ADK) — same gap; named as in scope by the product owner on 2026-09-03 (decision 1). No BrainBuddy usage data exists for this population (research.md: Users & Demand, ASSUMPTION at low confidence).
- **Users**: Builders of custom agents — today must implement a BrainBuddy-only contract with no SDK, validation tooling or reference implementation; nobody ever has (research.md: Prior Art, internal).
- **Stakeholders**: Max, product owner — sole decision authority. Set the population, guarantee tiers, feature numbering, branch and definition of done on 2026-09-03 (research.md, product-owner decisions 1–8); ratifies specs and holds ASK landing authority.
- **Stakeholders**: Independent reviewers and CI — dual review on the exact SHA, green CI and ASK merge authority gate every landing (research.md: Governance; 007 ratification-provenance).
- **Stakeholders**: Security and privacy review — the 007 security suite (SC-003) and the wire-independent obligations (FR-003 secrets, FR-015 retention, FR-016 disconnect, FR-019 rollout-OFF, account purge) must hold on whatever wire replaces the current one (research.md: Data & Constraints).
- **Stakeholders**: Hermes A2A plugin maintainers (NousResearch) — external, no decision power; affected only if BrainBuddy proposes an upstream patch, which the owner made optional (decision 6).

## Goals

- An owner whose agent conforms to the shared agent-to-agent standard can connect it and hand a Task to it with **no BrainBuddy-specific code on the agent side** — for both the self-hosted and the cloud-hosted populations the owner named, over public HTTPS with bearer or API-key credentials.
- Every 007 product guarantee that does not depend on the wire survives unchanged: the consent preview of exactly what leaves BrainBuddy, recent reauthentication, sealed secrets, bounded retention, disconnect, rollout-OFF semantics, account purge, and the honesty rules (FR-011: BrainBuddy facts are distinguished from agent reports; FR-012: an external run never mutates the canonical Task).
- Replaying a confirmation never silently starts the work twice: agents that can guarantee it get the strong single-start guarantee; agents that cannot are still admitted, BrainBuddy performs its own deduplication before any resend, and the residual risk is disclosed to the owner before hand-off rather than hidden (decision 2).
- The owner-facing run projection stays honest and ordered — a stale report never overwrites a newer accepted state, silence reads **Stopped reporting**, completion reads **Agent reported complete** — even though the observed agents report on their own terms (replies that block for minutes, terminal-only notifications, no version counters).
- Web and iOS show one and the same projection for every required state (decision 7).
- The relay works against the reference personal-agent runtime exactly as shipped — the unmodified Hermes A2A plugin; no upstream change is a prerequisite (decision 6).
- The investment already ratified in 007 is reused, not discarded: the wire-independent product-guarantee layers (roughly 87% of the 5,485-line relay module) are preserved, and the work fits a medium (weeks) appetite (decision 8).

## Non-Goals

- OAuth2 and mTLS credential schemes (deferred, decision 1); agents reachable only through them are outside the intended population for now.
- Keeping the bespoke 007 envelope alive alongside a new wire, or preserving compatibility with it — it has zero consumers; the generic HTTP connector goes away and custom agents connect through an SDK for the standard (decision 5). The ratified 007 baseline stays as history and is not re-ratified (decision 3).
- Depending on, or waiting for, an upstream Hermes patch (decision 6).
- Private-network, plaintext or otherwise non-public agent destinations — 007 FR-004's public-HTTPS, DNS-pinned egress stays regardless of protocol.
- BrainBuddy-hosted agents, runtimes, tools, provider credentials, internet access, cost or safety controls (007 Out of Scope).
- Task classification, planning, decomposition, provider selection, automatic retry of accepted work, completion verification or automatic Task completion (007 FR-012 and Out of Scope).
- Multi-agent fan-out, routing, delegation chains, workflow builders, marketplace, billing, quotas, managed hosting, connection templates, shared connections and organisation policy (007 backlog and Out of Scope).
- Rich progress visualisation of structured or streamed partial output, and user push notifications for blocked/completed runs (007 backlog).
- A calendar deadline; the budget is an appetite, not a date (decision 8).

## Success Metrics

- Distinct **unmodified** third-party agent runtimes that complete an automated end-to-end hand-off (connect, test, reviewed dispatch, reported state, **Agent reported complete**): at least 2 — the unmodified Hermes A2A plugin and an official a2a-sdk sample agent (baseline: 0; no connector implementing the current envelope exists anywhere).
- BrainBuddy-specific code an operator must write to connect a conforming agent: 0 lines (baseline: a full bespoke shim per agent; none has ever been written).
- Replay safety: three identical confirmation/dispatch replays against each reference runtime produce exactly one external task and one Task-linked run (baseline: 007 SC-001 is proven only against an in-repo fake of the bespoke envelope, never against a real agent).
- Security regression: the 007 SC-003 suite (unauthenticated, cross-owner, malformed, oversized, unknown-run, unsafe-destination, stale-regression cases) passes on the new wire with zero accepted state changes and zero secret disclosure (baseline: passes on the bespoke wire only).
- Projection parity: web and iOS render the same state for every 007 SC-002 state against both reference runtimes (baseline: met for the bespoke wire with fakes; unproven against any real agent).
- Honest degradation (qualitative, labelled as such): when a connected agent cannot guarantee single-start, the residual duplicate-start risk is visible to the owner before confirmation, and no such agent is ever presented as guaranteed (baseline: such agents are refused outright as `unsupported`; the disclosure does not exist).
- Delivery: lands within the medium appetite through exact-SHA dual review, green CI and ASK authority, with rollout still OFF until separately authorised (baseline: 007 landed the same way and never rolled out).

## Cost of Inaction

Nothing breaks, and that is the trap. The relay stays behind a rollout-OFF flag with zero connectors, so no user is harmed today and no signal will ever arrive to say the wire is wrong — the feature simply never gets used. The provider-agnostic promise in 007's Product Boundary stays unfulfillable in practice: every agent an owner might bring needs a shim nobody has written, so the roughly 5,485 lines of ratified relay code (about 87% of them wire-independent product guarantees) yield nothing. The agents the owner wants to reach keep converging on the shared standard — 172 listed partner organisations verified from source, plus hyperscaler platform support and framework integrations reported in unfetched press coverage — and a shipped Hermes plugin already answers it; the standard keeps moving, so both the gap and the eventual rework grow with time. For Hermes operators specifically, delegation and a kanban board already exist inside Hermes; a BrainBuddy relay that cannot reach their agent gives them no reason to route work through BrainBuddy at all. The one bounded upside of waiting is stability: the standard is young (16 breaking changes to reach v1.0, a v1.0.1 eleven weeks later), so a later start would build on a steadier target — at the price of the feature staying dark for exactly as long as we wait.

## Open Questions

- [NEEDS CLARIFICATION: Demand is owner-stated, not observed. Is there any BrainBuddy user, ticket, interview or waitlist signal for handing Tasks to an external agent — self-hosted or cloud-hosted — that would let success be measured in usage rather than only in reference-runtime evidence? Not blocking for specification; must be answered before rollout widening.]
- [NEEDS CLARIFICATION: Does OpenClaw serve the standard natively? Hermes documentation lists it as a compliant peer; a search snippet says the opposite; neither was verified. Decides whether "personal self-hosted agents" means "Hermes" in practice.]
- [NEEDS CLARIFICATION: Do the cloud-hosted platforms the owner named (Bedrock AgentCore, Azure AI Foundry, Google ADK) accept plain bearer or API-key credentials for inbound agent calls, and which protocol version do they serve? research.md verified neither; if they require OAuth2/IAM-style tokens, the deferred credential schemes gate that entire population.]
- [NEEDS CLARIFICATION: Which official a2a-sdk sample agent (and SDK language) is the second reference runtime in the definition of done, and can it run deterministically in CI without a live provider?]
- [NEEDS CLARIFICATION: Can the Fly deployment sustain long-lived per-run activity — the reference runtime's reply can block for up to 300 seconds — when today's background thread only runs periodic sweeps? Resolve during planning, before implementation begins.]
- [NEEDS CLARIFICATION: Adoption figures beyond the 172-entry partner list (150+ organisations, hyperscaler GA, AAIF membership) come from unfetched search snippets; confirm from source before the spec cites them as rationale.]
