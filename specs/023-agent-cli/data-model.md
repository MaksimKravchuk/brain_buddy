# Data model

## Existing domain data

Task, Project, Tag and CRT tree remain owned by their current repositories. bb persists no business-content cache. Its request maps an explicit body, expected_revision and Idempotency-Key into the existing API; the server remains authoritative.

## DeviceAuthorization (Identity)

One bounded device_authorizations table in Identity auth.sqlite3, using the existing AuthStore transaction and an additive validated schema migration. No JSON grants or second authentication authority. Existing Identity epoch/import remain owned by modern-auth.

- device_code_hash PRIMARY KEY: SHA-256 of random256-bit private proof; user_code_hash UNIQUE: normalized eight-character unambiguous Base32 code hash. Never persist raw codes.
- created_at/expires_at/next_poll_at/poll_interval_seconds; indexed expiry, fixed600s lifetime and initial5s poll interval.
- state constrained to pending/approved/denied/consumed; expiry always takes precedence.
- user_id/source_session_hash/auth_version/auth_method/provider_binding_id/provider_generation captured on the first decision. Foreign keys bind immutable owner, exact source session and applicable provider binding with delete cascades. Pending rows have no owner/provenance. No email/IP/device name/provider secret.

Transitions: pending → approved/denied; approved → consumed in the same transaction as the distinct CLI session insertion. Fresh source-session/account/version/provider-generation checks, conditional consumption, mint and final checks commit together. Rollback leaves no session and no consumed grant; a committed lost response cannot replay or recover a secret. The resulting CLI session inherits source method/binding and current auth_version, so provider unlink/revocation and bulk credential changes apply. Ordinary source logout prevents unconsumed issuance; already issued separate sessions follow existing authority revocation rules.

SQL constraints and BEGIN IMMEDIATE cover independent connections/processes. A bounded startup/periodic sweep physically removes every expired grant (max1024) by the next sweep even with cli_auth OFF; startup handles downtime, admission also prunes. Source/owner/provider erase cascades grants, and hard account purge invokes explicit cleanup after existing flag scrub. Invalid schema/rows fail closed with coarse logs, never quarantine. Unknown proofs allocate nothing. Device proof/provenance data is excluded from export as transient authorization security material, explicitly named in manifest/docs. Local CLI files are outside server export.

Browser-only return state contains the normalized short user code and <=600s deadline in tab-scoped sessionStorage after immediate fragment removal. It contains no private device proof/session/provider token or account content. Terminal outcome/expiry/cancel erases it; missing or blocked storage means manual entry. The server remains the approval authority.

## CLI connection metadata

User-local JSON configuration contains canonical HTTPS server origin, API prefix, account ID, selected credential-store kind, opaque store locator and expiry. It contains no credential, email or business content. Default has one connection per server/prefix; changing account requires explicit bb auth login --replace. Origins reject userinfo, query, fragments and unsafe prefixes. Loopback HTTP is allowed for development; remote HTTP is rejected.

Credential namespace includes canonical origin, API prefix and account ID. Secret value is the cookie token plus cookie-name/expiry metadata, kept only in the native store or selected private file. Cookie name is validated as an HTTP token; never accept Set-Cookie for a different host/path or a non-session cookie. No automatic refresh is promised; expiry requires explicit login.

The explicit BB_SESSION_TOKEN environment source takes precedence for that invocation; BB_SESSION_COOKIE_NAME defaults to brainbuddy_session and is validated. It is never persisted. auth status marks this source; auth logout cannot erase an external secret from its manager and reports external_source:true. No credential appears in process arguments or discovery.

## Command result

Success is one JSON document with data and optional page metadata. A server task cursor is opaque, preserved byte-for-byte and not followed automatically. Locally bounded unpaginated arrays report truncated:true with no fabricated cursor. Errors expose a stable code and selected safe status/detail/correlation/retry fields; mutation transport uncertainty is explicit. The exact envelope is contracts/cli.md.

## Release identity

Archive names identify bb version and target. SOURCE.json binds version, source SHA, toolchain and build-run evidence; SHA256SUMS binds exact filenames/bytes. Installers trust HTTPS repository releases and verify archive hashes from that same resolved release. This detects corruption, not compromise of the release account; signature provenance is outside first-release claims.
