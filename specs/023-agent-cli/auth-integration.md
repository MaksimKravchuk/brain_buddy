# CLI authentication integration notes

Status: owner-approved browser/headless UX; proposed technical contract under planning review, not implemented. The authoritative proposed interface is contracts/device-auth.md.
Inspected2026-10-06: main21f08d26698a434f7b1d16b991b2b43d4e0ea0f2 and published origin/feat/modern-auth@bc7fc72c35b7bf794eff912c07bdd38a1d1f0816.

## What is observed

Main retains opaque-cookie login/logout/me and now includes task_mcp, giving six required runtime flags. The published modern-auth branch adds Google/Apple/email shared web/iOS login and accepted ADR-0028 transactional auth.sqlite3 authority; existing cookie/Me wire remains compatible. No inspected branch supplies device endpoints. The branch is not claimed landed or deployed. Its authFlow.safeAuthDestination currently rejects /cli/authorize, and ProtectedRoute/LoginPage omit fragments; CLI captures the short code before redirect and adds only the exact approval destination to the shared allowlist. Device rows/issuance use AuthStore, preserving source version/provider lineage. No JSON sidecar or duplicate shared Identity implementation.

## Recommended owner journey

1. Install bb and explicitly run bb auth login.
2. CLI starts a short-lived authorization request against the configured BrainBuddy server, shows its verification link and one-time code, and opens the link in a browser.
3. The owner uses whichever login methods the shared-auth system currently offers, verifies the account/code/CLI connection and explicitly approves it.
4. BrainBuddy issues an expiring, independently revocable CLI credential for that account. The CLI stores it in the OS credential store and reports the account without printing the secret.
5. Later task/API commands use the stored credential without prompts. A 401 reports that login is required; it never opens a browser during agent execution.

For SSH/remote/container use, bb auth login --no-browser leaves approval to a browser on another device. CI and unattended agents can use an explicitly injected credential from their existing secret management.

## Boundary with shared authentication

Prefer a BrainBuddy device-authorization flow following the [OAuth device authorization model, RFC 8628](https://www.rfc-editor.org/rfc/rfc8628). This is a flow supported by BrainBuddy itself; it does not require Google or Apple to expose device authorization to this CLI. Provider verification, immutable account mapping, invite policy and account linking stay server-owned in the parallel auth feature. The CLI does not implement Google/Apple SDK login, accept provider passwords or ship an embedded client secret.

This feature supplies the following additive capabilities through the existing Identity services; published shared-auth changes must be reconciled before freezing the implementation candidate:

- Start a bounded authorization grant: private device proof, short user code, trusted verification URI, expiry and polling interval.
- Browser approval tied to the displayed device request and authenticated existing account, with CSRF/session protections from shared auth; no identity inferred just from an email address.
- A polling/exchange contract distinguishing pending approval, slow-down, denial, expiry and successful credential issuance; consumption/replay behavior must be explicit.
- A distinct opaque BrainBuddy session using the existing cookie transport accepted by member endpoints. No bearer-token or provider-token migration is introduced.
- Status, expiry and separate CLI revocation, including account-deletion/session-revocation obligations. No promise of refresh tokens until the shared-auth contract actually includes renewal.
- An authenticated authorization boundary for CLI access. Existing owner scoping, operator rules, flags and external-processing consent remain enforced; this document does not invent restricted scopes the server cannot enforce.
- Capability-unavailable behavior for older servers. The CLI must not silently fall back to asking for a provider password or exporting browser cookies.

No messages were sent to another session. The source contract is now published and inspected. Backend integration requires the landed modern-auth authority; the CLI release additionally requires its completed import and SQLite-capable rollback baseline. Provider configuration and real-provider smoke remain owned by that feature. No unreviewed auth branch is silently merged into the CLI delivery candidate.

## Credential storage and recovery requirements

Prefer macOS Keychain, Windows Credential Manager and Linux Secret Service. Credentials are keyed by trusted server/API identity and account, never reused for an unrelated origin or silently replaced with another account. A missing/locked credential service is an explicit error. A protected local-file fallback is opt-in and requires enforced owner-only protection; external secret input remains usable on unattended hosts. Credentials and provider tokens never enter command discovery, dry-run, logs, evidence or normal stdout.

Only report successful login after the credential is saved. A failed save must preserve the previous working credential and invoke the agreed cleanup/revocation behavior for the newly issued one. Denial/expiry/Ctrl-C do not report connected status. Logout removes local saved access and reports whether server revocation succeeded; offline local removal is not represented as successful server revocation.

## Acceptance dependency

FR-013/FR-014 and SC-006 in spec.md are required outcomes. CLI authorization and its approval page must be deployed and verified against the shared login methods available at release before calling this feature complete. Google/Apple implementation remains owned by the parallel feature. Auth/privacy work is ASK-class under ADR-0008; planning-review and release approvals remain applicable. No product implementation or release approval is claimed by the UX sign-off.
