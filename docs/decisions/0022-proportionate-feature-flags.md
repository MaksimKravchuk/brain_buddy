# ADR-0022: Feature flags apply to significant new capabilities

Date: 2026-09-06
Status: Accepted by the product owner
Supersedes: ADR-0008's universal new-behavior flag requirement and universal SHOW OFF/INTERNAL rollout clause only
Related: ADR-0012 (preserve accepted decision history), ADR-0018 and ADR-0019 (existing flag ownership)

## Context and owner decision

While reviewing completed-task animation, the owner explicitly said no new flag was
needed because the behavior should already exist. The owner also directed the general
policy: «Давай мы зафиксируем, что флаг нужен для каких-то значительных новых фич, типа
агентского харнеса, брейндампа, current reality 3. Вот там вот будут флаги.»

## Decision

Significant new capabilities require server-owned feature flags, initially OFF and
rolled out through the applicable existing mechanism. Examples are the agent harness,
Brain dump and Current Reality Tree.

Corrections to expected existing behavior do not require a new flag. Completed-task
placement, readable completed styling and completion animation are such a correction.
Do not expand this correction into new backend/admin flag infrastructure or use the
release-smoke-only delivery_canary to control it.

Existing feature gates, risk classification, tests, independent review, exact-SHA
verified delivery, production smoke and image rollback remain unchanged. Flags are
exposure controls, never authorization. ADR-0008 stays intact as a historical decision;
this record is current authority for the two narrowed rollout clauses.

## Consequences

Small corrections can follow normal verified delivery without a separate rollout
control. They still require review, production verification and a usable image rollback.
Significant new capabilities retain staged exposure and applicable audience checks.
No runtime flag, authorization setting or delivery workflow is changed by this record.
