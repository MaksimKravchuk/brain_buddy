# Validation quickstart

These are planned validation commands after implementation, not claims of an existing binary/release. Use synthetic disposable accounts/content and never commit credentials.

Prerequisites: isolated feat/agent-cli worktree; pinned Rust; existing uv backend/npm frontend dev dependencies; server with new endpoints, explicit trusted frontend origin and runtime cli_auth enabled for fixture account. Shared frontend serves /cli/authorize and proxies /api. Provider availability comes from deployed shared login; current email/password can validate the provider-neutral connection.

Build/check cargo test --locked --manifest-path cli/Cargo.toml, cargo fmt --manifest-path cli/Cargo.toml --check, cargo clippy --locked --manifest-path cli/Cargo.toml --all-targets -- -D warnings. Run focused backend/tests/test_cli_auth.py and frontend approval/return tests with Allure helpers, then complete required make verify-all/CI.

## Owner/agent journey

1. Install fixed released version using distribution.md; check bb --version. Pre-release local compilation is implementation evidence only.
2. bb auth login --server https://brain-buddy-frontend.fly.dev. Sign in through shared login, verify displayed account/code, approve. Protected save/read-back succeeds before authenticated JSON; no token output.
3. bb commands task works offline; bb auth status proves identity through /auth/me.
4. bb task add --title 'CLI fixture' --key cli-fixture-create. Identical replay returns one task/same ID.
5. bb task list --query q=CLI; bb task get ID returns revision. bb task update ID --json @fixture-update.json --key cli-fixture-edit uses synthetic title/expected_revision.
6. bb task transition ID complete --revision CURRENT --key cli-fixture-complete; read completed state. Old revision edit fails exit6 without overwriting.
7. bb api GET /auth/me; bb schema POST /tasks; project/tag/tree reads. No routine full schema dump.
8. bb auth logout returns local_cleared/server_revoked true; later CLI access fails while browser original session remains valid. Approved fixture cleanup/readback.

Also bb auth login --no-browser from a headless machine with approval on another device. Linux without Secret Service explicitly uses --store file or existing secret manager injection; Windows native Credential Manager. No token in arguments/history/evidence.

## Failure/size/native evidence

Unauthorized/foreign-owner404, malformed JSON/key/revision,429, grant denial/expiry, locked store/save failure, concurrent exchange, source revoke/deletion, offline logout; accepted-write/lost-response fixture returns delivery_unknown without replay. Redirect/chunked oversized/non-JSON failures redact secret sentinels. Twenty synthetic rich tasks: default≤40% full UTF-8 bytes, id/title/state/revision/cursor intact; actual tokenizer named if additionally measured.

All five native jobs execute binary and store persistence/refusal checks. Installer fixed-version/corrupt/interrupted/unsupported/unsafe archive/replacement fixtures preserve old binary. Actual published Unix/Windows installs require neither compiler nor admin. Production browser states recorded at mobile/desktop with keyboard/focus/accessibility and exact SHA/flag stage. Standard authenticated production_smoke.sh plus CLI separate-session revoke and cleanup readback remain required.
