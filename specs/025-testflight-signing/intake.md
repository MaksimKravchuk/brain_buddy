# Intake: Reusable TestFlight signing identity

Owner: repository owner. Date: 2026-10-07.

The owner asked to fix iOS TestFlight run 37634408487/job 112836785239,
then explicitly asked the agent to perform certificate setup. The archive
failed because fresh runners exhausted Apple's development certificate quota.
The owner revoked the selected stale CI certificate and explicitly approved
saving the replacement private-key bundle and password in the repository's
`testflight` environment. No broader certificate revocation is authorized.

Outcome: repeated uploads reuse one owner-provided Apple Development identity
for app and widget; a signed archive and TestFlight upload succeed without
adding development certificates per run. Invalid signing input stops before
archive, and temporary signing material is cleaned up on failure as well as success.

Scope: `.github/workflows/ios.yml`, its bounded installation helper under
`ios/ci/`, existing delivery-validator tests, and `ios/README.md`.
Non-goals: app/domain/UI changes, distribution-signing changes, dependency
changes, new delivery authority, broader environment access, certificate
auto-revocation, or a manual Fly deploy. Capture/review/route remains unchanged.

Assessment skipped: this is an explicitly requested repair with an observed failure.
Delivery is ASK under ADR-0008; approval and audited landing controls remain binding.
