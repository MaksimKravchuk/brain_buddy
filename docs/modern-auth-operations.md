# Modern authentication operations

This guide covers spec 023's direct Google, Apple and email-code setup and the
Identity storage transition. It supplements [auth.md](auth.md), whose older
JSON/invite-only limitations do not describe the modern implementation. The
settings below come from `ModernAuthSettings`; migration and image checks come
from the implemented CLI and release guard. Examples contain placeholders.
Configuration is not evidence of working providers, legal compliance or an
accepted release. Use the [release runbook](autonomous-delivery-runbook.md) for
the existing ASK approval, exact-SHA CI, landing and deployment procedure.

## Backend configuration and origins

Use [.env.example](../.env.example) for names and disabled defaults. Inject real
values through the backend's approved secret storage, separate from its data
volume. Never put these values in frontend `VITE_*` configuration, a URL, command
history, logs or review artifacts. Local `compose.yaml` passes `.env` to both
containers: keep that shared file free of real auth secrets and use a private
backend-only Compose override for an authorized provider rehearsal.

| Environment variable | Required value |
| --- | --- |
| `BRAIN_BUDDY_AUTH_PUBLIC_ORIGIN` | Browser application origin, such as `https://app.your-domain.com` |
| `BRAIN_BUDDY_AUTH_API_ORIGIN` | Browser-reachable provider callback origin, without `/api` |
| `BRAIN_BUDDY_API_PREFIX` | Existing API prefix; default `/api` |
| `BRAIN_BUDDY_AUTH_CURRENT_KEY_ID` | Current key ID in the keyring |
| `BRAIN_BUDDY_AUTH_KEYRING` | JSON object of versioned, base64-encoded 32-byte master keys |

Both auth origins must be explicit public HTTPS origins, with no credentials,
path, query, fragment, wildcard or private/loopback address. Plain HTTP and
localhost disable modern methods even in development. These settings are
separate from the relay's `BRAIN_BUDDY_PUBLIC_BASE_URL`.

For the current web deployment, set **both auth origins to the same browser
origin** and proxy `/api` there. Web start/completion requests use that origin;
the host-only binder cookie must reach the provider callback on the same host.
A direct Fly backend hostname is not an interchangeable web callback origin.
Check the external HTTPS/proxy routing before registering these exact URLs:

| Provider registration or return | With default API prefix |
| --- | --- |
| Google authorized redirect | `https://app.your-domain.com/api/auth/providers/google/callback` (GET) |
| Apple web return URL | `https://app.your-domain.com/api/auth/providers/apple/callback` (form POST) |
| Apple server-to-server notifications | `https://app.your-domain.com/api/auth/providers/apple/notifications` (POST) |
| BrainBuddy web handoff | `https://app.your-domain.com/auth/complete#attempt=...&state=...&grant=...` |
| Fixed iOS browser handoff | `brainbuddy://auth/callback?attempt=...&state=...&grant=...` |

Register the HTTPS provider redirect, not the web fragment page or app scheme,
with Google/Apple. There is no user-supplied redirect destination. Keep query
strings, OAuth assertions/codes, handoff grants and bodies out of proxy/access
logs; a fragment is not sent in an HTTP request. Preserve authentication
responses' `Cache-Control: no-store` and `Referrer-Policy: no-referrer` headers.

## Direct providers and existing mail service

No paid auth SaaS is introduced. Google OAuth uses the existing Google project;
Sign in with Apple uses the existing developer membership; email uses an
existing authenticated SMTP service. Their terms, membership renewal and mail
usage/quota limits still apply. Record the current quotas and any existing
usage charges before rollout; this guide does not purchase or guarantee a free
mail allowance.

**Google:** configure an OAuth consent screen for the intended audience and a
**Web application** OAuth client. Register the exact Google redirect above;
keep the consent screen's authorized domains, test-user restrictions and
publishing/verification status consistent with the launch audience. Set
`BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_ID` to its `…apps.googleusercontent.com` ID and
`BRAIN_BUDDY_AUTH_GOOGLE_CLIENT_SECRET` to its backend secret. Web and iOS use
this same server-exchanged browser flow (`openid email`, Google S256 PKCE).
There is no additional native Google client setting or client secret in iOS.
An email matching an existing account does not automatically connect it.

**Apple:** enable Sign in with Apple on the actual iOS App ID and provisioning
profile. `BRAIN_BUDDY_AUTH_APPLE_NATIVE_APP_ID` must equal the signed app's
`PRODUCT_BUNDLE_IDENTIFIER` (`$(BB_BUNDLE_ID_PREFIX).ios` in `ios/project.yml`),
not its App Group entitlement. Associate the web **Services ID** with that
primary App ID; register the callback domain and exact HTTPS Apple return URL,
and keep any grouped App IDs in the same intended identity group. Set:

- `BRAIN_BUDDY_AUTH_APPLE_SERVICES_ID`: the web Services ID.
- `BRAIN_BUDDY_AUTH_APPLE_TEAM_ID` and `BRAIN_BUDDY_AUTH_APPLE_KEY_ID`: the
  corresponding ten-character uppercase alphanumeric identifiers.
- `BRAIN_BUDDY_AUTH_APPLE_PRIVATE_KEY`: the full P-256 PEM Sign in with Apple
  `.p8` key, with actual newlines. A filename or literal `\n` text is invalid.

The server signs short-lived Apple client-secret JWTs and exchanges every code;
native Apple uses the server's raw state and nonce unchanged in the system
authorization request, then sends the original identity token, code, state and
client verifier to the backend. Apple has no invented PKCE setting.
Configure the **server-to-server notification URI** above in Apple's portal
before launch and verify actual signed events, replay handling and revocation.
The current verifier expects the Services ID audience when it is configured,
otherwise the native App ID; confirm the portal's actual signed audience agrees.
Register the mail sender/domain with Apple's Private Email Relay and verify
delivery to a Hide My Email address as well as a normal mailbox.

**SMTP:** set `BRAIN_BUDDY_AUTH_SMTP_HOST`, `SMTP_PORT`, `SMTP_SENDER`,
`SMTP_USERNAME`, `SMTP_PASSWORD` and `SMTP_TLS`, each with the full
`BRAIN_BUDDY_AUTH_` prefix. Sender is a bare verified email address, not a
display-name header. Use `starttls` with the sender's STARTTLS port (normally
587), or `tls` with implicit TLS (normally 465). Both modes verify certificates;
plaintext SMTP and unauthenticated delivery are unavailable. Configure the
sender's required SPF/DKIM/DMARC and approved sending limits. SMTP acceptance
activates the code, but is not proof of inbox delivery; rehearse normal, spam,
private-relay and failed-delivery outcomes. A failed/uncertain dispatch does
not refund the send budget or silently replay the same leased payload.

## Availability, sessions and operating limits

`GET {API_PREFIX}/auth/methods?client=web` and `?client=ios` report `password`,
`google`, `apple`, `email` and `web_account_origin`. Discovery checks configuration,
not live provider reachability. Every modern method needs both valid origins
and a usable keyring. Google also needs its client ID/secret; Apple web needs
the Services ID and valid Team/Key/P-256 key, while native needs the native App
ID and those same credentials. Email additionally needs every SMTP field and
a supported TLS mode. One unavailable method does not disable the others or
existing password access. Configured operators retain the password-only path;
ordinary verified onboarding does not require a legacy invite.

| Limit | Implemented behavior |
| --- | --- |
| Email code | Six decimal digits; challenge lifetime at most 10 minutes; at most five failed guesses across resends |
| Resend | At least 60 seconds; a resend replaces the previous code without resetting failures |
| Persistent send budget | Per one-hour window: 5/address, 20/client challenge, 50/network |
| Persistent failed-guess budget | Per one-hour window: 10/address, 30/client challenge, 100/network |
| Provider attempt / handoff | Attempt at most 10 minutes; one-use callback handoff at most 60 seconds, plus initiating client verifier |
| Recent confirmation | At most 5 minutes, bound to account, session, action and client |
| Provider/SMTP I/O | 10-second calls; provider JWKS cache at most one hour, refresh throttled to once/minute |
| Session | Existing opaque `brainbuddy_session`; 30-day maximum; `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` in production |
| Web provider binder | `brainbuddy_auth_binder`, 600 seconds, host-only, `HttpOnly`, `Secure`, `SameSite=None`, path `{API_PREFIX}/auth/providers`; removed on callback |

These code counters survive restart and are not refunded by SMTP failures. Budgets use
keyed fingerprints; the current hourly records expire within one hour, inside
the published 24-hour maximum. The binder is not an authenticated session.
Missing configuration, failed providers and absent old decryption keys fail
closed; never create a replacement key to make unreadable data work. Monitor
coarse delivery/provider errors and correlation IDs, not emails or proof data.

## Key installation and rotation

Key IDs contain 1–64 ASCII letters/digits, `_` or `-`. Values use standard
base64 decoding to **exactly 32 random bytes**. Example syntax only:

```dotenv
BRAIN_BUDDY_AUTH_CURRENT_KEY_ID=auth-2026-10
BRAIN_BUDDY_AUTH_KEYRING='{"auth-2026-10":"<base64-of-32-random-bytes>"}'
```

The placeholder is deliberately unusable. Generate each independent key in the
approved secret manager; do not reuse a password, provider credential or data
encryption key. Settings are loaded at process startup, so apply secret changes
through the approved restart/release procedure and verify discovery afterward.

To rotate, install the new key **alongside** all still-needed old keys, select
the new ID as `CURRENT_KEY_ID`, and restart all writers consistently. New HMACs
and encrypted records use the new key; existing envelopes identify their old
key. Budget checks include retained keys, so rotation does not reset limits.
Remove an old key only after its challenges, budgets, mail jobs, migration
backup and Apple cleanup records have expired/been erased **and** no active
Apple revocation grant still depends on it. Active grants can outlive 24 hours;
elapsed time alone is not retirement evidence. There is no automatic re-keying
command. Record a scoped review of remaining key-ID references without printing
payloads before removal; lost keys cannot be reconstructed from SQLite.

## Explicit migration and rollback containment

An empty root initializes `auth.sqlite3` directly. A nonempty legacy
`users/`/`sessions/` root requires a maintenance window and the explicit CLI;
ordinary startup cannot silently import it. There is no second legacy storage
mode, dual write or JSON fallback. An initialized epoch-1 database already
requires a SQLite-capable image even without a legacy import.

1. Rehearse the migration/parity and release-failure guard against synthetic
   storage at the exact candidate SHA. Record the approved target volume,
   image, key availability and recovery loss boundary.
2. Drain ingress, disable automatic restart/autostart and stop **every** old
   API, worker, CLI and other authentication writer against that volume.
   Verify they remain stopped. `--writers-stopped` acknowledges this external
   prerequisite; it does not stop processes or make rolling overlap safe.
3. In the candidate's pinned backend environment, mounted to that stopped
   volume and with auth keys supplied only through secret storage, run:

   ```sh
   cd backend
   BRAIN_BUDDY_DATA_DIR=/path/to/stopped-data-root \
     uv run --frozen python -m app.cli migrate-auth --writers-stopped
   ```

4. Require `schema_epoch: 1`, `import_committed: true` and
   `cleanup_complete: true` in its coarse JSON result; inspect import/revoked
   counts against the rehearsal. Invalid journals, indexes, duplicates, paths
   or changed source bytes abort. IDs, password hashes, valid session hashes
   and ownership remain; expired/orphan legacy sessions are revoked, while
   malformed session payloads abort the import.
5. Keep writers stopped on failure. Before commit, validated original authority
   remains; after commit, retry this same CLI to finish cleanup, without
   reimporting JSON. Startup can resume committed cleanup but readiness stays
   blocked until it completes. Start only the approved SQLite-capable code
   through the release procedure, then prove readiness, parity and smoke.

The migration writes `.auth-migration-backup.enc` on the volume, mode `0600`,
using authenticated encryption and a verified manifest. Its deadline is at
most 24 hours from creation. Any account purge erases the **whole aggregate
backup**, not only that account's part; startup/maintenance enforce expiry
without needing a decryption key. Do not make permanent plaintext archives or
copy this backup into longer-lived snapshots. SQLite `secure_delete` and WAL
checkpointing reduce local remnants; they do not establish forensic erasure
of platform/device backups. The owner must govern those external copies.

The existing release workflow captures the actual previous backend image and
its storage capability, checks the fresh ledger before deploy mutation, and
checks again before changing rollback flags or either image. These are the
implemented guard commands, **not deployment commands**:

```sh
python3 scripts/auth_migration_guard.py capture --app '<backend-app>' \
  --image '<actual-captured-registry.fly.io-image>' --output '<private-capture.json>'
python3 scripts/auth_migration_guard.py forward --app '<backend-app>' \
  --capture '<private-capture.json>'
python3 scripts/auth_migration_guard.py restore --app '<backend-app>' \
  --capture '<private-capture.json>'
```

The first capture verifies every running machine matches the recorded image;
later checks re-read every volume's coarse schema/checkpoint. Unknown,
unreachable, malformed or mismatched evidence forbids restoration. An import
committing after capture cannot authorize a JSON image. Epoch 1 refuses an
epoch-0/unknown target even for a fresh database. Never override the guard,
delete SQLite or restore old JSON to make an image start.

If no compatible previous image exists, preserve the volume and checkpoint,
drain/stop backend writers and prevent restart under the incident's recorded
target authority. Keep the deployment **failed**. Repair forward from code
that reads the committed epoch, obtain green exact-SHA CI and the recorded ASK
landing, then use the normal release workflow. Native documents/outboxes stay
on device. Restoring the short-lived backup is a separately approved data
recovery with explicit loss/resurrection analysis, never ordinary rollback.

## EU/GDPR launch owner checklist

The owner must record the actual controller/contact, provider roles and
contracts before launch. The repository does not prove a signed DPA, EU-only
residency, transfer safeguard, certification or legal basis. Use the existing
[retention/rights disclosure](data-retention.md) and the current public privacy
page; record the following concrete checks rather than claiming compliance:

- [ ] Name the release/privacy owner and controller/contact. Review purposes,
  legal bases, ROPA, rights response process and any applicable EU representative
  requirement for the actual audience/entity. Authentication is not AI consent.
- [ ] Inventory Google/Apple identity services, the actual SMTP operator and
  Fly hosting/logs/backups: which data each receives, contractual role, region,
  subprocessors and retention. OAuth sends identity scope/context, not tasks or
  trees; SMTP receives the recipient and short-lived code. Providers and inbox
  operators can keep external copies the application cannot erase.
- [ ] Obtain/apply each required DPA or other applicable terms; assess actual
  international transfers and safeguards. Review the user's provider privacy
  notices and any extra configured AI/content processors separately. An EU
  hosting region does not establish EU-only Google/Apple/mail processing.
- [ ] Verify temporary retention at the release SHA: proofs/codes at most
  10 minutes, recent confirmation 5 minutes, handoff 60 seconds, dispatch
  payload erased after send/failure/expiry, budget fingerprints at most
  24 hours, Apple signed-notice replay records at most 8 days. Apple cleanup
  must stop after five attempts or 24 hours, capped by purge; a provider outage
  never extends local deletion. Check the integrated lifecycle worker evidence.
- [ ] Verify 14-day deletion grace (or the actual configured grace), immediate
  session revocation, due-account purge and aggregate-backup erasure. A valid
  login during grace cancels deletion; past-due accounts cannot reappear.
  Rehearse Apple unconfirmed cleanup and notification-driven method disabling
  without deleting member content.
- [ ] Verify proof-bound modern export/delete and legacy password endpoints
  against the same owner. Export includes safe personal identity metadata;
  exclude password/session hashes, tokens, codes, proofs, revocation grants,
  fingerprints and cleanup/notification security internals. Server export
  cannot include unsent native work or erase remote device/browser backups.
- [ ] Confirm log redaction, actual platform log/snapshot retention and the
  privacy page's cookie/provider/processor/rights disclosures. Record residual
  external copies and the owner-controlled erasure process without promising
  physical removal the application cannot perform.
- [ ] Record real Google/Apple/SMTP smoke, signed notification/private-relay
  evidence, quota review, compatible-rollback rehearsal and required native
  exact-SHA CI/device checks. Configuration flags or synthetic tests alone do
  not satisfy provider/device/release acceptance.

## Mac compatibility checkpoint

Read-only GitHub inspection on 2026-10-06 found Mac PR
[#265](https://github.com/MaksimKravchuk/brain_buddy/pull/265) open at
`10923345745dd38e6c176ea79e91bfff6c2a7885`, with only 021 planning files changed.
Against integrated auth `1c3957b83e9a9abdef76ae02cf2fcd8fd3d04f2b`, the existing
Mac password wire and shared legacy API/default identity/Keychain namespaces
were unchanged; the visible Mac app still used its local workspace. This is
compatibility evidence, not acceptance of an implemented 021 sync feature.
Future 021's throwing removal-closure `SyncService.signOut` must preserve
022's attempt invalidation/commit serialization; its proposed client identity
must preserve existing `clientVersion:` callers and logout/retry behavior.
The future Mac namespace is explicitly `app.brainbuddy.mac.session`; iOS keeps
`app.brainbuddy.session`. Recheck aggregate Mac/iOS CI and device evidence after
021 source integration; do not substitute the planning PR's older build checks.

## Password access before optional setup

Without usable modern origins and the auth keyring, discovery advertises no
web account origin. Existing password accounts retain password changes, safe
exports and password-confirmed deletion through the compatible account routes.
The web UI keeps connected-method metadata and binds these requests to its
displayed owner. A failed discovery request is a retry state, not a downgrade
to this mode. Passwordless accounts continue to use the proof-bound actions;
missing operational keys must be restored rather than bypassing ownership proof.

Local authentication expiry runs at startup and in the regular privacy sweep,
independently of provider delivery and authentication keys. Losing a key or a
provider outage must not retain disconnected identity mappings past their
cleanup deadline. A transient store failure is logged and retried on the next
sweep without stopping the other privacy duties.
