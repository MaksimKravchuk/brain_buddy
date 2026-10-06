# Data model

## Existing domain data

Task, Project, Tag and CRT tree remain owned by their current repositories. bb persists no business-content cache. Its request maps an explicit body, expected_revision and Idempotency-Key into the existing API; the server remains authoritative.

## DeviceAuthorization (Identity)

One atomic JSON record at data/device_authorizations/{device_code_hash}.json:

- device_code_hash: SHA-256 of a random 256-bit private proof; filename is validated lowercase hex.
- user_code_hash: SHA-256 of normalized eight-character unambiguous Base32 code; uniqueness among live records checked under authorization guard. Raw codes are never persisted.
- created_at, expires_at: UTC; fixed ten-minute lifetime, never extended by polling.
- state: pending, approved, denied or consumed. Expired is derived from expires_at and takes precedence.
- next_poll_at, poll_interval_seconds: five-second initial interval; early polling adds five seconds and moves the deadline.
- approved_user_id and approver_session_hash: only for approved/consumed/denied account decisions. No email, provider token, IP or arbitrary device name is persisted.

Transitions: pending → approved/denied on the first authenticated browser decision; approved → consumed before session issuance. Terminal decisions cannot be changed. Only a fresh approving session for the same active non-deleting account may exchange approved. Source revoke, account marker, flag OFF or expiry prevents exchange. Consumed replay never returns or mints a secret. All states become unusable after ten minutes and are physically removed by the next existing privacy sweep (default60s, configured1–3600s) or startup after downtime; admission is capped at 1,024 live records. Unknown private codes allocate no record/counter.

Corrupt records fail closed and are deleted under the guard without payload logging; no persistent quarantine is created. They count against admission until safely removed. Atomic-write failures propagate with correlation information. The lock file remains stable across pruning.

Device grants and their verifiers are excluded from server account exports as transient authorization security material, explicitly named in the export manifest/docs/data-retention.md. Local CLI store/configuration bytes are outside server export and cleared by the owner locally.

## CLI connection metadata

User-local JSON configuration contains canonical HTTPS server origin, API prefix, account ID, selected credential-store kind, opaque store locator and expiry. It contains no credential, email or business content. Default has one connection per server/prefix; changing account requires explicit bb auth login --replace. Origins reject userinfo, query, fragments and unsafe prefixes. Loopback HTTP is allowed for development; remote HTTP is rejected.

Credential namespace includes canonical origin, API prefix and account ID. Secret value is the cookie token plus cookie-name/expiry metadata, kept only in the native store or selected private file. Cookie name is validated as an HTTP token; never accept Set-Cookie for a different host/path or a non-session cookie. No automatic refresh is promised; expiry requires explicit login.

The explicit BB_SESSION_TOKEN environment source takes precedence for that invocation; BB_SESSION_COOKIE_NAME defaults to brainbuddy_session and is validated. It is never persisted. auth status marks this source; auth logout cannot erase an external secret from its manager and reports external_source:true. No credential appears in process arguments or discovery.

## Command result

Success is one JSON document with data and optional page metadata. A server task cursor is opaque, preserved byte-for-byte and not followed automatically. Locally bounded unpaginated arrays report truncated:true with no fabricated cursor. Errors expose a stable code and selected safe status/detail/correlation/retry fields; mutation transport uncertainty is explicit. The exact envelope is contracts/cli.md.

## Release identity

Archive names identify bb version and target. SOURCE.json binds version, source SHA, toolchain and build-run evidence; SHA256SUMS binds exact filenames/bytes. Installers trust HTTPS repository releases and verify archive hashes from that same resolved release. This detects corruption, not compromise of the release account; signature provenance is outside first-release claims.
