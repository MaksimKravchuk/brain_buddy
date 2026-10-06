# CLI authentication integration notes

Status: proposed UX and integration requirements, not an accepted or implemented server API contract.
Inspected on 2026-10-06 at main commit afaa820ae8f5edcac99764c386ed748d6dca037c.

## What is observed

The current backend has POST /api/auth/login accepting email/password and setting a brainbuddy_session cookie, POST /api/auth/logout revoking the supplied session, and GET /api/auth/me reporting identity. It has no inspected CLI device-authorization or provider-login endpoint. Searches of fetched remote branch names, commit messages and published PRs did not identify the parallel Google/Apple login contract. This does not establish that the parallel session has no work; its artifacts may be unpushed.

## Recommended owner journey

1. Install bb and explicitly run bb auth login.
2. CLI starts a short-lived authorization request against the configured BrainBuddy server, shows its verification link and one-time code, and opens the link in a browser.
3. The owner uses whichever login methods the shared-auth system currently offers, verifies the account/code/CLI connection and explicitly approves it.
4. BrainBuddy issues an expiring, independently revocable CLI credential for that account. The CLI stores it in the OS credential store and reports the account without printing the secret.
5. Later task/API commands use the stored credential without prompts. A 401 reports that login is required; it never opens a browser during agent execution.

For SSH/remote/container use, bb auth login --no-browser leaves approval to a browser on another device. CI and unattended agents can use an explicitly injected credential from their existing secret management.

## Boundary with shared authentication

Prefer a BrainBuddy device-authorization flow following the [OAuth device authorization model, RFC 8628](https://www.rfc-editor.org/rfc/rfc8628). This is a flow supported by BrainBuddy itself; it does not require Google or Apple to expose device authorization to this CLI. Provider verification, immutable account mapping, invite policy and account linking stay server-owned in the parallel auth feature. The CLI does not implement Google/Apple SDK login, accept provider passwords or ship an embedded client secret.

The shared-auth work must supply or explicitly agree the following capabilities before CLI authentication implementation:

- Start a bounded authorization grant: private device proof, short user code, trusted verification URI, expiry and polling interval.
- Browser approval tied to the displayed device request and authenticated existing account, with CSRF/session protections from shared auth; no identity inferred just from an email address.
- A polling/exchange contract distinguishing pending approval, slow-down, denial, expiry and successful credential issuance; consumption/replay behavior must be explicit.
- A BrainBuddy API credential transport accepted by member endpoints. Whether this reuses an opaque server session or another reviewed credential shape is deliberately not asserted as an existing contract.
- Status, expiry and separate CLI revocation, including account-deletion/session-revocation obligations. No promise of refresh tokens until the shared-auth contract actually includes renewal.
- An authenticated authorization boundary for CLI access. Existing owner scoping, operator rules, flags and external-processing consent remain enforced; this document does not invent restricted scopes the server cannot enforce.
- Capability-unavailable behavior for older servers. The CLI must not silently fall back to asking for a provider password or exporting browser cookies.

No messages were sent to another session. This file is the reviewable coordination input; shared-auth source artifacts still need to be read when published.

## Credential storage and recovery requirements

Prefer macOS Keychain, Windows Credential Manager and Linux Secret Service. Credentials are keyed by trusted server/API identity and account, never reused for an unrelated origin or silently replaced with another account. A missing/locked credential service is an explicit error. A protected local-file fallback is opt-in and requires enforced owner-only protection; external secret input remains usable on unattended hosts. Credentials and provider tokens never enter command discovery, dry-run, logs, evidence or normal stdout.

Only report successful login after the credential is saved. A failed save must preserve the previous working credential and invoke the agreed cleanup/revocation behavior for the newly issued one. Denial/expiry/Ctrl-C do not report connected status. Logout removes local saved access and reports whether server revocation succeeded; offline local removal is not represented as successful server revocation.

## Acceptance dependency

FR-013/FR-014 and SC-006 in spec.md are required outcomes. Shared provider sign-in and CLI authorization must be deployed and verified together before calling this feature complete. Auth/privacy work is ASK-class under ADR-0008; planning-review and release approvals remain applicable. No product implementation or authentication approval is claimed by this design amendment.
