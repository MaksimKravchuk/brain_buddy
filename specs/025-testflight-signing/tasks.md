# Tasks: Reusable TestFlight signing identity

## Phase 1: Planning gate
- [x] T001 Complete portable review for specs/025-testflight-signing/plan.md and record actual owner high-risk approval in the campaign evidence.

## Phase 2: User Story 1 — reusable signing
- [x] T002 [US1] Add failing installer/cleanup/security-boundary evidence in scripts/test_validate_trunk_delivery.py for FR-001–FR-004 and SC-002.
- [x] T003 [US1] Implement ios/ci/install_signing_identity.sh and .github/workflows/ios.yml; prove valid identity import, archive leaf-certificate matching, safe redaction and idempotent fail-closed cleanup.
- [x] T004 [US1] Update ios/README.md for FR-005 and record environment-only secret names/update metadata and unchanged environment policy for SC-004.

## Phase 3: Candidate freeze and independent evidence
- [ ] T005 [US1] Run affected checks and make verify-all, freeze one candidate with .specify/workflows/runs/025-testflight-signing-candidate/pre-freeze-receipt.json, validate it with python3 scripts/validate_pre_freeze_receipt.py --sha CANDIDATE_SHA .specify/workflows/runs/025-testflight-signing-candidate/pre-freeze-receipt.json, and create one ASK review PR for the exact SHA (ADR-0008).
- [ ] T006 [US1] Obtain independent exact-SHA code review and required CI; verify a signed branch upload and unchanged portal count for SC-001. No identity/secret changes between accepted runs.

## Phase 4: Authorized landing and acceptance
- [ ] T007 [US1] Obtain recorded landing approval, perform audited temporary ruleset intervention (actor/reason/restoration time), and verify automatic main TestFlight upload, leaf-certificate match, private unchanged certificate identity set/count and all operational evidence. Fly smoke requires the explicit bounded exception in plan.md or a separately approved trusted smoke-only path.

## Dependencies

T001 → T002 → T003 → T004 → T005 → T006 → T007. One bounded serial
delivery path; no disjoint execution lane justifies a parallel marker. Writer
checks precede T005 freeze; T006 review/CI and T007 acceptance remain independent
of implementation. Required evidence must not be replaced by writer self-certification.

## Post-task stages

After every checklist item is complete, an independent auditor writes
specs/025-testflight-signing/acceptance.md and traceability.md; report.md records
actual results. Post-task artifacts are not prerequisites of their own audit.
