# Shared Apple Rust bridge cache intake

Owner: Max. Agreed in the current chat on 2026-10-16.
Problem/persona: the repository owner waits about 22 minutes for iOS queue checks; about 12 minutes rebuild an unchanged bridge.
Objective: let real merge-queue runs reuse a matching main-scoped bridge, while keeping all checks.
Scope: populate the existing two Apple bridge cache variants from trusted main pushes; document and verify reuse in a follow-up iOS documentation PR.
Non-goals: Swift build caches, test selection, platform removal, test/coverage changes, queue settings, release authority, secrets, product behavior.
Constraints/dependencies: existing key algorithm, Xcode selection, Rust pin and bridge script; GitHub cache isolation. Cold/missing cache must still build normally.
Compliance/data: build outputs only, no credentials or user data. No changes to capture, review, routing, consent, retention or account rights.
Done: required CI green, main-scoped cache read-back, real merge-group cache hit, unchanged checks and measured iOS timing. No guaranteed fixed timing threshold.
Assessment skipped: bounded owner-requested correction supported by measured logs.
