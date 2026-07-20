# Mobile boundary requirements checklist: Expo mobile first slice

**Purpose**: Reviewer-grade requirements quality gate for security, ownership, mobile
resilience, Expo/native boundaries, build/signing, design classification, and evidence
**Created**: 2026-07-20
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [ADR-0008](../../../docs/decisions/0008-add-one-expo-mobile-client-over-opaque-sessions.md)

## Identity and credential boundary

- [x] CHK001 Are server/session ownership requirements explicit that mobile adds no JWT, refresh-token family, client-owned owner ID, or second identity store? [Completeness, Spec §FR-002, ADR-0008 §Mobile session establishment]
- [x] CHK002 Is the distinction between browser HTTP-only cookie transport and mobile one-time opaque credential transport unambiguous? [Clarity, Spec §FR-003, Contract §Mobile session establishment]
- [x] CHK003 Are requirements defined for absent, malformed, expired, revoked, undecryptable, and dual-source credentials without silently choosing an authority? [Coverage, Spec US1/Edge Cases, Contract §Common transport rules]
- [x] CHK004 Is credential storage bounded to device-protected storage with explicit exclusions for passwords, files, generic state, caches, logs, telemetry, and artifacts? [Completeness, Spec §FR-004, ADR-0008 §Mobile session establishment]
- [x] CHK005 Is the iOS reinstall/Keychain-persistence risk and first-install cleanup requirement documented without turning an install marker into identity or fingerprinting? [Edge Case, Data model §Installation marker]
- [x] CHK006 Are sign-out and involuntary-auth-loss requirements clear for local clearing, remote revocation, active-recording discard choice, same-owner recovery quarantine, offline failure, browser-cookie compatibility, and account-switch isolation? [Coverage, Spec US1.3–US1.4, Contract §POST /auth/logout]

## API ownership and compatibility

- [x] CHK007 Is API semantic version ownership separated from persisted-data schema version before a second client ships? [Consistency, Spec §FR-007, Plan §Generated API boundary]
- [x] CHK008 Does the requirements set define backward-compatible versus breaking changes, snapshot generation authority, overlap window, and strict-enum behavior? [Completeness, Contract §API version ownership]
- [x] CHK009 Are backend Pydantic/OpenAPI contracts identified as source of truth, with generated transport DTOs distinguished from domain and mobile view models? [Clarity, Spec §FR-008, ADR-0008 §API contract]
- [x] CHK010 Are error statuses, `ErrorResponse`, correlation IDs, wrong-owner hiding, idempotency, and stale-revision behavior consistently specified across Task and voice commands? [Consistency, Spec §FR-012, Contract §Common transport rules]
- [x] CHK011 Is it explicit that existing Task/Project/Tag/operation routes are reused rather than duplicated as mobile-specific domain endpoints? [Completeness, Spec §FR-010/FR-013, Plan §Task projections]

## Mobile local-state and recovery boundary

- [x] CHK012 Are canonical server state, replaceable in-memory query projections, SecureStore credential state, and local voice recovery state clearly distinguished? [Clarity, Data model §§Server-owned/Mobile-owned/In-memory]
- [x] CHK013 Is local Voice recovery limited to the minimum operation/file/chunk/manifest/revision/key metadata and prohibited from storing transcript/proposal/task content? [Completeness, Spec §FR-017, Data model §VoiceRecoveryManifest]
- [x] CHK014 Are atomic write, corrupted-manifest quarantine, persisted-before-send command keys, chunk acknowledgement, account change, and cleanup semantics specified? [Coverage, Data model §VoiceRecoveryManifest]
- [x] CHK015 Is general offline Task mutation explicitly excluded while Voice recovery remains a bounded durable queue? [Boundary, Spec Assumptions/Out of Scope]
- [x] CHK016 Are low storage, process kill, audio-route loss, permission withdrawal, network loss, and every operation checkpoint covered as requirement scenarios? [Coverage, Spec Edge Cases/US3]

## Voice permission, authority, and idempotency

- [x] CHK017 Are microphone permission and external-processing consent separate and ordered before recording/upload/provider invocation? [Consistency, Spec §FR-014, Contract §Start]
- [x] CHK018 Is foreground-only recording explicit, including durable document storage and the absence of background/live-streaming claims? [Clarity, Spec §FR-015/Design M-05, Research Decision 5]
- [x] CHK019 Are chunk numbering, content identity, same-content retry, conflicting-content failure, manifest completeness, and seal prerequisites defined? [Completeness, Spec §FR-016, Contract §§Audio chunks/Seal]
- [x] CHK020 Is closing/backgrounding explicitly prevented from meaning cancel, commit, or Task creation, with server projection reconciliation on reopen? [Clarity, Spec §FR-018, Plan §Voice sequence]
- [x] CHK021 Are proposal edit/remove/lineage/conflict requirements consistent with explicit confirmation and deterministic child idempotency? [Consistency, Spec §FR-019/FR-020, ADR-0002]
- [x] CHK022 Is every failure/cancel/partial-commit requirement honest about actual results and prohibited from promising atomic rollback? [Coverage, Spec US3.9, Contract §Cancellation]
- [x] CHK023 Is title-only Inbox creation explicit, with due date/Project/Tag/Priority inference and pre-confirmation Task creation prohibited? [Clarity, Spec §FR-020, Contract §Confirmation]
## Expo and native escape boundary

- [x] CHK024 Are the SDK, development-build, CNG, generated-native-project, and Expo Go boundaries explicit enough to prevent accidental bare/ejected ownership? [Completeness, Plan §Expo/native escape]
- [x] CHK025 Are native Swift/Kotlin escape criteria measurable: reproduced capability gap, narrow interface/fake, both-platform evidence, rollback, and ADR amendment? [Measurability, ADR-0008 §Expo and native escape]
- [x] CHK026 Is the first likely escape trigger—continuous encoded chunks while recording—distinguished from the accepted post-stop chunk upload slice? [Clarity, Research Decision 5]
- [x] CHK027 Are config-plugin-owned permission/security changes preferred over committing native projects, with no ideological promise that Expo can never be escaped? [Consistency, ADR-0008 §Expo and native escape]

## Package and code-sharing boundary

- [x] CHK028 Is the single `mobile/` package boundary explicit, with no mobile BFF, root workspace, second app, or Expo web rewrite? [Completeness, Spec §FR-001/Out of Scope, Plan §Project Structure]
- [x] CHK029 Are permitted future shared-package contents separated from prohibited framework/storage/navigation/domain contents? [Clarity, ADR-0008 §API contract and compatibility]
- [x] CHK030 Is design-token mirroring governed by the authoritative design skill and adherence tests rather than importing browser CSS into native? [Consistency, Plan §Generated API boundary/Project Structure]
- [x] CHK031 Is web migration to generated types explicitly deferred so mobile delivery is not coupled to an unrelated Vite refactor? [Boundary, Research Decision 6]

## Design classification and non-goals

- [x] CHK032 Does every M-01 through M-09 frame have exactly one Build, Bounded build, or Deferred disposition? [Traceability, Spec §Design Classification]
- [x] CHK033 Are M-04 Subtasks/Comments/run actions, M-05 live proposals, M-06 Add date/inference, M-07 Think, and M-09 Weekly Review explicitly excluded or bounded? [Coverage, Spec §Design Classification]
- [x] CHK034 Are current Tag vocabulary and exactly four open GTD states consistent with ADR-0006, without historical Context or date-view state drift? [Consistency, Spec §FR-009, ADR-0006]
- [x] CHK035 Is the requirement that every enabled control maps to a real command/client action measurable through an inventory gate? [Measurability, Spec §FR-023/SC-008]
- [x] CHK036 Are Execution, CRT, external routing, autonomous actions, Smart Add, metadata editing, general offline sync, notifications, and public store rollout explicit first-slice non-goals? [Completeness, Spec §Out of Scope]

## Build, signing, and release authority

- [x] CHK037 Are public app configuration and secret/signing/provider/store credentials clearly separated? [Security, Spec §FR-025, ADR-0008 §Build]
- [x] CHK038 Are PR CI, simulator/emulator builds, preview/internal distribution, production signing, and store submission assigned to distinct authorities? [Clarity, ADR-0008 §Build, Plan §Release Gates]
- [x] CHK039 Is production build/submit a separately approved action rather than an automatic consequence of merge or EAS configuration? [Boundary, Spec Out of Scope, ADR-0008]
- [x] CHK040 Are rollback and revocation requirements honest about the inability to selectively revoke mobile sessions until a channel field exists? [Risk, ADR-0008 §Migration and rollback]

## Test and evidence quality

- [x] CHK041 Are backend cookie/Bearer parity, no-cache/no-cookie, ambiguity, expiry, revocation, owner isolation, version, and contract statuses all required? [Coverage, Plan §Test Strategy]
- [x] CHK042 Are SecureStore, first-install cleanup, auth bootstrap, owner cache clearing, recovery manifest, chunking, reducer, and proposal confirmation covered by focused mobile tests? [Coverage, Plan §Mobile unit/component]
- [x] CHK043 Are simulator/emulator and one real-device smoke per platform required where Keychain/Keystore/microphone/interruption behavior cannot be proven by mocks? [Evidence, Quickstart §§7–8]
- [x] CHK044 Does the privacy gate cover source, logs, Allure, screenshots/video, crashes, bundle/source maps, generated native config, and build output with canary values? [Completeness, Quickstart §10]
- [x] CHK045 Is Allure taxonomy required centrally for backend, mobile unit/component, and black-box product tests? [Consistency, Spec §FR-024, Plan §Test Strategy]
- [x] CHK046 Are both-platform internal builds, deterministic fixture integration, control inventory, and independent QA/review included before release approval? [Completeness, Spec §SC-007/SC-008, Plan §Release Gates]
- [x] CHK047 Does mobile consume canonical append-only proposal patch → immutable freeze → confirm routes while deprecated direct `PATCH`/`commit` aliases remain excluded from its generated operation allowlist? [Consistency, Contract §§Canonical proposal/Freeze/Confirm, ADR-0002]
- [x] CHK048 Are frozen-batch invalidation, deterministic child receipts, legacy payload migration, alias delegation/overlap, process restart, and partial failure covered before mobile Voice implementation? [Coverage, Plan §Canonical Voice backend prerequisite]
- [x] CHK049 Is recovered consent time-bounded and bound to fresh server policy/provider categories, with restart/configuration revalidation and fail-closed withdrawal/cleanup semantics? [Coverage, Spec §FR-014, Data model §VoiceRecoveryManifest]
- [x] CHK050 Are raw-audio deletion state, `retained_until`, delete-now eligibility, local-versus-server cleanup, and preserved confirmed provenance explicit and testable? [Completeness, Spec §FR-026, Contract §Raw-audio retention]
- [x] CHK051 Does ADR-0008 explicitly refine only first-mobile capture timing while ADR-0002 remains authoritative for shared contracts and the long-term live-primary UX? [Precedence, ADR-0008 §ADR precedence]

## Notes

- All 51 requirement-quality checks pass against the current spec, plan, contract, data model,
  research, quickstart, and ADR-0008.
- This checklist validates that requirements are complete and coherent; it does not claim
  product code exists or replace failing-first implementation tests, review, CI, or device
  evidence.
