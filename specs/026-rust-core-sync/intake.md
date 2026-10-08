# Intake: shared Rust core and custom synchronization

Date: 2026-10-08. Requirements come from the architecture discussion with the owner and this choice (translated): “Rust and custom sync look promising. We need a specification for this solution.” The owner subsequently required documentation to be in English and requested a PR.

## Problem

Task rules are implemented in several languages, while local operation and server communication have their own recovery mechanisms. Every change must be reconciled across implementations. Android, Windows, and Linux will increase this cost if each receives another copy of the rules. iOS and macOS already use BrainBuddyKit; describing them as two independent domain engines is outdated.

## User and objective

The primary scenario is one person using their own devices. Shared data and delegation may follow, but those features are not yet defined. Native iOS, Android, macOS, Windows, and Linux are the target platforms; the web retains existing functionality and becomes secondary. Users must be able to capture and organize tasks quickly offline, then obtain consistent state after reconnecting without loss or duplicates.

## Measurable outcome

Task rules have one normative implementation and one set of behavioral examples. Identical commands produce identical decisions on every connected client. The first delivery verifies the complete iOS ↔ server ↔ macOS path, including lost responses and concurrent edits. Proposed budgets: local writes at p95 ≤ 50 ms; active online clients converge at p95 ≤ 2 s under the stated conditions. These are criteria for the future implementation, not benchmark results.

## Scope boundary

This work produces a specification and technical proposal. It does not start a migration, implementation, or release. The first product stage covers existing tasks, projects, Tags, child records, and native-task Weekly Review. Existing voice operations, Identity, CRT, and A2A retain their boundaries and gain adapters to task commands where needed.

Outside the first stage: shared workspaces, assignee permissions, a CRDT editor, a new recurrence language, new automation, a complete backend rewrite, replacement of the CRT model, a required model on every phone, and simultaneous release of all five clients. The target architecture describes integration points without presenting them as agreed product functionality.

## Constraints and compliance

Local AI models take priority; remote processing requires current consent. Existing account deletion, export, session revocation, and confirmation of voice proposals remain intact. Ordinary server sync retains the current trusted-server model; content E2EE is not added implicitly. Requiring E2EE would change command validation and server AI and would need a separate decision.

The user has not specified a deadline, team budget, or workload model. Performance figures and the Android → Windows/Linux order below are planning proposals. Approval of UX in previous features does not approve the new screens.

## Dependencies

Audit baseline: `3b5967f5bc01abae43cb0fc143d8c038cd5c8b0d`. Relevant decisions: ADR-0001/0002/0006/0007/0020/0026/0027/0028/0029 and specs 020, 021, 022, 023, 024. Moving storage requires an explicit new ADR, an identified oldest compatible rollback build, and separate migration authorization. Apple's current third-party dependency restriction needs a narrow amendment for the selected bindings; this specification does not edit that restriction.

## Definition of a complete specification

The package contains testable requirements, a component diagram, a sync algorithm covering conflicts and crash recovery, shared-logic boundaries, a migration strategy, UI states, and acceptance criteria. Assumptions are separate from owner decisions. The artifacts pass the repository spec check and substantive review; product tests and sign-off are not represented as complete.

A separate assessment was not started because the user had already compared alternatives and chosen a direction. Repeating the interview is unnecessary to record known requirements. Formal UX, review, and PR-slice gates remain prerequisites for implementation; this package has Draft status.
