# Modern authentication verification

Status: implemented candidate under verification. This file records actual
evidence, including failures. It does not certify launch or GDPR compliance.

## Candidate and compatibility

- Implementation branch: `feat/modern-auth`; current main
  `afaa820ae8f5edcac99764c386ed748d6dca037c` integrated in `90035ca`.
- Mac PR [#265](https://github.com/MaksimKravchuk/brain_buddy/pull/265)
  inspected before implementation and rechecked at head
  `10923345745dd38e6c176ea79e91bfff6c2a7885`: open, unmerged, planning changes
  under `specs/021-mac-sync`. Existing password/me/logout wire contract,
  default shared client identity and Mac Keychain namespace are preserved.
  Future remembered-email/outbox handling still belongs to 021.
- The CI native lane now also builds/tests the Mac app with the same shared
  package. A green job title alone will not count: inspect RUN=true, checkout
  SHA and executed commands.

## Executed checks

| Check | Actual result | Scope / limitation |
|---|---|---|
| First complete backend run | 3,639 passed, 2 failed, 1,255.13 s | 3,641 cases on pre-main-merge backend. Failures: old public API inventory; rollback shell fixture missing new capture/environment. Both repaired; 50 focused regression cases passed. |
| First backend coverage | lines 97.21%, branches 92.35% | Below immutable floors 98.47% / 95.61%; verification remains red. Pytest's separate 95% aggregate check is insufficient. |
| First complete web run | 1,658 tests / 71 files passed, 390.46 s | All existing and new unit tests passed. |
| First web coverage | statements 97.38%, branches 96.14%, functions 97.30%, lines 98.83% | Below repository floors; verification remains red. Additional failure/recovery coverage in progress. |
| Independent security review | initial changes requested; repaired Apple changes approved | Actual review files below. Three reproduced defects: relay delivery disable, revoked-state wire/reconnection, associated notice receipt erasure. Red tests reproduced all three; 44 focused tests and independent equal/newer-consent checks passed after repair. Whole-feature acceptance was not granted. |
| Provider return hydration regression | 1 failing regression / 3 old passing; then 4 passed | Actual browser found callback racing account hydration. Repair waits for settled hydration before owner assertion; timeout invalidates continuation. |
| Disabled-provider reconnection | 1 failing regression / 6 old passing; then 7 passed | Inactive connected methods offer Reconnect and fresh consent rather than ineffective Remove. |
| Worker real-app browser run | 9/9 passed, 59.4 s | Product base `5e5b01d`; synthetic Google/SMTP boundaries, actual signed RSA assertions, SQLite, app and UI. Three masked screenshots and sanitized Axe summaries retained. |
| Integrated real-app browser runner | 9/9 passed, 40.3 s | TLS runner against root candidate with current main. First failed attempt lacked Playwright's FFmpeg; installed recording dependency, then passed. |
| Worker keyboard timing | 22.4 ms, busy+disabled, 1 dispatch, retained focus | Chromium 151 headless, 1280×720. Headed candidate run is in progress; this is not physical iOS evidence. |
| Actual headed browser run | 9/9 passed, 1.3 min | Candidate product `9451af0`; Chromium 151 with Xvfb display, 1280×720 and 390×851 checks. Three masked screen images retained. |
| Headed keyboard timing | 28.1 ms, busy+disabled, 1 dispatch, retained focus | Measurement attachment confirms `headless:false`. Response held at real API boundary, completed by actual mail proof. |
| Headed accessibility | zero Axe violations on all three scanned surfaces | Login's moderate landmark findings were repaired by using the existing layout's semantic main landmark. This is web evidence, not native device evidence. |
| Repository meta gates | check-specs passed; validate-ci passed with local socket access | Default sandbox first blocked socket fixtures; rerun with approved local execution passed. |
| Previous native package run | 614 tests in 65 suites passed | Implementation worker's Linux Swift 6.2 run before final aggregate. Candidate-bound native/CI evidence still required. |

Independent reviews:
[initial](reviews/implementation-security-5fc4a6a.json),
[repair review](reviews/implementation-security-8f3adb83.json).

Log files remain in this execution workspace under `/tmp/modern-auth-*`.
Generated Allure and browser artifacts are ignored build evidence; fresh final
CI artifacts must bind to the frozen implementation SHA.

## Implementation locations and justified deviations

- The explicit migration orchestrator is `backend/app/services/auth_migration.py`;
  repositories own SQLite state. This keeps orchestration out of persistence.
- Apple grant cleanup has its own bounded service,
  `backend/app/services/auth_apple_lifecycle.py`; orchestration calls it from
  `modern_auth_service.py` and the existing account lifecycle.
- Privacy/cleanup tests use `test_auth_apple_lifecycle.py`,
  `test_auth_migration_integration.py`, `test_modern_auth_authority_edges.py`
  and `test_modern_auth_apple_integration.py` rather than duplicate test files
  suggested by T034. Assertions cover actual durable state and archive content.
- Web security controls live in `features/auth/AccountSecurity.tsx`, callback
  routing in `app/AppRoutes.tsx`; existing account/task behavior is reused.
- Provider/email operations are documented in
  [modern-auth-operations.md](../../docs/modern-auth-operations.md), rather than
  a second overlapping auth-setup guide.
- A separate TLS browser fixture is necessary because optional modern auth is
  intentionally disabled in the existing legacy Compose acceptance stack.
  Both suites remain required; the new runner does not replace legacy E2E.
- Gate integrity changed only for strengthened Makefile checks: migration guard
  tests and modern browser journeys. Coverage floors and validators unchanged.

## Remaining evidence

1. Finish coverage repairs, execute the complete required suite on the final
   SHA, and verify native CI really executes against that same candidate.
2. Complete synthetic Apple browser acceptance and headed web reference checks.
3. Physical iOS: ASWebAuthenticationSession/Apple cancellation and return,
   autofill, Dynamic Type, 44-pt controls, pending feedback and preserved outbox.
4. Real configured Google, Apple and SMTP smoke. Provider accounts existing
   does not supply OAuth IDs/private keys/sender configuration to this workspace;
   current runtime reports no configured secret bindings.
5. Actual controller/processor agreements and disclosures, stopped-writer
   migration, approved exact-SHA release and production smoke. No production
   mutation or claimed live success has occurred.

The full acceptance gate is not ready while T033/T041–T044 remain incomplete.
Do not turn missing device/live/production evidence into passing mock results.
