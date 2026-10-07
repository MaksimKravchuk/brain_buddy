# Shared native modern-auth contract

Preserve Workspace.signIn(serverURL:email:password:), SyncService.signInWithResult and BrainBuddyAPIClient.login signatures/behavior for Mac021. Preserve its additive client identity default/injection when integrating, separate iOS/Mac Keychain namespaces and pending logout. No macos/ writes or GTD rules.

## Additive API

Pure Sendable API models: NativeSignInAttempt(id:UUID, serverURL:URL, expectedAccountID:String?); NativeSignInCredential password/emailCode/browserGrant/apple variants; typed availability/start/code/recovery/completion DTOs. Sensitive values are not Codable log/debug descriptions or URL sessions.

Add beginSignIn(serverURL:) async throws(SignInFailure) -> NativeSignInAttempt; completeSignIn(_:credential:) async throws(SignInFailure) -> SignInResult; cancelSignIn(_:) async to SyncService, with fail-closed defaults for older implementations/fakes. Workspace exposes corresponding methods and preserves existing write flushing/event-handler setup. Metadata/code/provider request helpers use the current API module; no Apple-only imports in package targets.

## Attempt state machine

Choosing → requesting/provider waiting → verifying candidate → validating active attempt/owner → short committing phase → linked. Any failure/cancel/supersession returns to usable UI with live credential/local tasks preserved.

1. Begin captures immutable current account/server and generation. Linked device cannot change server in the form. Each new attempt supersedes earlier generation; explicit sign-out/cancel invalidates it.
2. Build candidate API client with InMemorySessionTokenStore, never live Keychain. Parse successful status/MeDTO and require candidate cookie before install. New password alternative also uses candidate path.
3. Recheck generation after every await. Validate captured owner/server and current document owner under store atomic update. Different B on linked A refuses even with no pending work. Same ID with changed email is same owner.
4. Stop sync only for final commit; flush/persist/link through existing document/merge mechanisms, then install validated credential and resume existing first-pull/push. A storage failure must restore prior durable binding/token without overwriting a newer generation.
5. On wrong owner, stale attempt/error or cancellation, revoke only known candidate session using isolated client; offline cleanup uses existing pending-logout store. Never revoke current accepted token. Lost completion response cannot retry consumed proof as if it succeeded; start fresh.

Existing legacy empty-outbox account-switch test remains meaningful for Mac API. New iOS flow tests assert stricter owner rule; do not silently change old shared semantics.

## Google browser

App generates secure random completion verifier with Security, S256 with CryptoKit; stays in active coordinator memory. POST start receives backend broker URL. ASWebAuthenticationSession uses existing BrainBuddy custom scheme. Validate exact scheme/host/path, no userinfo/fragment/duplicate params, active attempt and state. Callback requires unpredictable grant plus local verifier; neither alone can finish. POST over HTTPS, never session cookie in URL. Backend broker separately owns upstream Google S256 and fixed registered HTTPS callback.

Cancel ASWebAuthenticationSession and invalidate generation; unsolicited AppRouter URLs cannot attach accounts. No polling a ready attempt or general app deep link as authority.

## Apple native

ASAuthorizationAppleIDProvider/controller lives in iOS app target; start receives random state/nonce and passes unchanged in request. Locally check returned state; send UTF-8 authorization code and identity token with attempt/verifier over POST. Backend validates native audience/nonce/signature and exchanges code, comparing subjects. Apple credential.user is provider ID, never BrainBuddy owner. Returning email/name optional; no provider grant persisted on device. Entitlement/capability in ios/project.yml only, no widget sharing.

Cancel controller, ignore late delegate callbacks and preserve active session/outbox. App UI respects 44pt targets, Dynamic Type, Reduce Motion, code autofill and keyboard avoidance.

A provider verify_mailbox completion uses the same isolated candidate client and original verifier for its email challenge. Successful mailbox verification directly returns signed_in for that staged attempt; it uses the standard owner/generation finalizer and does not require the already-consumed 60-second callback grant.

## Email/recovery

Explicit request/resend/verify only; preserve challenge counters and actual server expiry/resend time. No automatic resend after timeout/resume. Recovery saves password then returns to sign-in; it cannot bypass owner finalizer or attach a different account. Code/staged secrets clear on terminal outcome; local capture continues offline/cancelled.

## M-07 web rights entry

Use configured safe frontend origin, not arbitrary API-suffix stripping. Links: /settings/account?expected_owner=ID and /settings/account/delete?expected_owner=ID. ID is nonsecret; no cookie/token/grant transfer. Preserve expected owner through allowlisted login redirect.

Browser absent/B shows same-account login and blocks account mutation. Backend compares cookie owner, expected owner and fresh purpose/session proof, including another-tab change. Opening/cancelling browser leaves native document/outbox untouched. Direct deletion page completes the process, not generic support/home.

## Verification

Linux tests cover all credential types, first local-task merge, same ID/new email, wrong ID/server with pending/empty outbox, malformed/error response cookie isolation, cancel/supersede/sign-out/late response, strict callback parsing and grant/verifier/replay, recovery/resend and candidate logout isolation. Run ios/scripts/swift-linux.sh test; native UI compile on macOS CI. Real Apple capability, browser return, autofill/Dynamic Type/device cancellation and Mac candidate integration require actual environments and recorded evidence.
