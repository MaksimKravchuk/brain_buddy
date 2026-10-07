# Authentication requirements quality checklist

**Purpose**: reviewer-owned checks of requirement clarity and completeness, not implementation acceptance.
**Created**: 2026-10-06
**Feature**: [spec.md](../spec.md), [plan.md](../plan.md)

- [ ] CHK001 Are all new/returning web/iOS login methods and legacy/Mac compatibility boundaries explicit? [Completeness, FR-001–003/015/024]
- [ ] CHK002 Are stable subjects, mailbox authority, explicit linking, owner/session/action binding and collision outcomes unambiguous? [Security, FR-004–007/014/017]
- [ ] CHK003 Are proof lifetimes, one-use consumption, resend and persistent attempt budgets measurable and restart-safe? [Clarity, FR-008–010]
- [ ] CHK004 Are recovery, new-email verification and passwordless sensitive actions specified without weakening existing rights? [Coverage, FR-011–014/018]
- [ ] CHK005 Are local-work retention, candidate credential isolation and legacy native defaults stated for interruption/account mismatch? [Resilience, FR-015–016/024]
- [ ] CHK006 Are foreign-resource 404, own-account reauthentication 403 and public neutral errors distinguished? [Consistency, contracts/http-auth.md]
- [ ] CHK007 Are export exclusions, purge/grace, Apple grant/notice cleanup and missing-key limits bounded? [Privacy, FR-018–021/025]
- [ ] CHK008 Are uncertainty, unlink consequences, reset result, partial cleanup and accessible feedback specified in approved screen families? [UX, design.md]
- [ ] CHK009 Does SC-007 define candidate-bound web/native timing evidence rather than prototype screenshots? [Measurability, quickstart.md]
- [ ] CHK010 Are free-service constraints, actual provider setup, verified legal facts and live evidence limits explicit? [Scope, FR-020/023, SC-008]
- [ ] CHK011 Is migration rollback/containment executable through the actual release path, with no unsafe JSON restoration? [Data safety, contracts/persistence-migration.md]
- [ ] CHK012 Are tests, coverage/taxonomy/native gates, ASK landing and production acceptance distinguished? [Delivery, quickstart.md]

## Pre-freeze evidence

<!-- BrainBuddy constitution gates: typed writer receipt is required before freeze. -->
<!-- BrainBuddy pre-freeze receipt contract: checklist. Preserve this section. -->

- [ ] CHK013 Does the writer receipt validate with scripts/validate_pre_freeze_receipt.py against the full lowercase implementation SHA?

Checkboxes belong to the reviewer. Generation does not claim these criteria, implementation or production evidence have passed.
