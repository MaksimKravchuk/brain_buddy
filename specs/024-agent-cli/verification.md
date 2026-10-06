# Implementation evidence — in progress

Writer: current agent, isolated `feat/agent-cli` worktree. Owner approved isolated implementation on 2026-10-06 with “Делай”; this is not landing or publication approval. The approved planning digest remains `2496d4980e0dce7dd51c305a552043f295a5997d10afd30c1b4368f5826186ca`. See namespace-migration.md for the unchanged-byte move to feature 024 after published modern-auth reserved 023.

## Current observed checks

- Rust 1.99.0, locked dependencies, formatting and Clippy with `-D warnings` pass.
- Rust contract/transport/discovery/output/auth fixtures pass: JSON exits, bounded input/response, offline discovery/preview, no redirects/retries, revision/key mapping, safe rate-limit/correlation errors, confirmed-write processing failures, minimal cursor-preserving task output and merged nested projections.
- Real disposable backend HTTP journey passes: create and replay return one task ID, search finds one task, edit advances revision, stale edit returns conflict without overwriting, complete and final GET preserve the edited title and completed state.
- Headless device-protocol fixture passes explicit approval exchange, file protection/read-back, independent-process task read and separate logout. Denial and unsafe-file-path failures are exercised. These are client protocol fixtures; the device endpoints and browser journey are not deployed or implemented by this evidence.
- Ubuntu 22.04 container (glibc 2.35), native x86_64 Rust build and real GNOME Secret Service: separate-process login/status/logout passes; locked collection remains locked and bb fails with exit10 before HTTP. An initial native fixture failed because its existing temp directory was 0755; the fixture now explicitly creates the required private 0700 configuration directory. No mock keyring was used.
- Unix installer fixtures pass selected version installation and previous-binary preservation for checksum corruption, traversal archive, wrong binary version, duplicate checksum and unsupported machine. Release packager tests validate archive membership and reject mismatched or missing native identity/checks.
- Requirement scanner tests and gate-integrity tests pass after adding the dedicated Rust test tree, lowercase Rust marker support and unfiltered feature024 gate. Full feature traceability remains incomplete until documentation/released-installer checks exist.

## Remaining before freeze

Finish auth cancellation/replacement/cleanup/isolation evidence, PowerShell installer/native matrices and reviewed release publication helper. Integrate the device/backend/browser flow only against landed shared Identity authority. At this checkpoint main remains `21f08d26698a434f7b1d16b991b2b43d4e0ea0f2`; published modern-auth is `4439c003f63ef501df8c5ae6e582e95531be239e`, not landed or deployed. Its completed SQLite import/release and compatible rollback floor are prerequisites.

Full required suites, five-platform CI, independent exact-SHA code review/QA, pre-freeze receipt, recorded exact-SHA ASK landing/release decision, binary publication and actual released installers/production auth journey remain outstanding. Ignored native/released tests are not passing evidence unless run explicitly in their supported environment. Nothing in this ledger certifies macOS/Windows execution or a published release.
