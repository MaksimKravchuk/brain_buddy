# Feature Specification: Google, Apple and email authentication

**Feature Branch**: `feat/modern-auth`
**Created**: 2026-10-06
**Status**: UX approved; technical planning in progress
**Input**: User description: "Давай ты сделаешь тогда нормальную систему авторизации ... Давай ее планировать и имплементировать." Scope and provider-account availability confirmed by the owner: "Да. Все есть".

## Clarifications

### Session 2026-10-06

- Q: Is the proposed scope and its exclusions accepted? → A: "Да. Все есть". Google, Apple, email code, existing password compatibility, open onboarding, recovery and linking on web/iOS are in scope; OpenAI, mandatory MFA, teams/SSO and additional Mac UI are out.
- Q: Are the provider accounts available, including active Apple Developer membership? → A: "Все есть". Provider accounts are available; credentials must still be configured through secret storage and live-provider evidence must be collected before release completion.
- Owner correction: baseline macOS sign-in is being implemented in another chat. Before continuing, examined PR #265 / 021 at `b83d367b30434d1d2448eefdef7043e95dbd9ff6`: Mac adopts the shared native library and existing password/session flow. Preserve its sign-in interfaces, account switch protection, Keychain/queued logout and client identity additions; do not duplicate or overwrite Mac changes.
- UX approval: after reviewing the concrete screen captures and prototype, the owner answered "Да" to the explicit screen-approval request on 2026-10-06; proceed to technical planning.
- Clarification scan: no remaining product ambiguity prevents UX design. Security lifetimes and throttling are bounded defaults below. Provider setup values, storage implementation and reviewer execution are technical-plan concerns. Controller-country details and signed processor agreements remain release disclosure inputs, not invented facts or design questions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start with Google, Apple or email (Priority: P1)

A new user opens BrainBuddy and chooses Google, Apple or email. An email user receives a code and enters it; the same journey creates an account or signs into an existing verified one. No invite or manual approval is required for ordinary onboarding. An existing password user still signs into the same account with their password.

**Why this priority**: delivers the requested usable login methods without a new auth-service subscription.

**Independent Test**: complete a new-user and returning-user login for each configured method on web and iOS; confirm an existing password account retains its ID and data.

**Acceptance Scenarios**:

1. **Given** a configured Google or Apple method and no existing identity binding, **When** the user completes a valid provider login with a verified address not claimed by another account, **Then** one private account and an application session are created, without an invite.
2. **Given** a verified provider binding, **When** the same provider identity returns, **Then** the same immutable BrainBuddy account is used even if the provider's displayed email changes.
3. **Given** an email address and working delivery, **When** the user requests and verifies a valid code, **Then** the address is verified and the user enters the new or existing account under the legacy-address transition rules in FR-014.
4. **Given** an existing password account, **When** its user submits valid existing credentials, **Then** the same session behavior, account ID, feature flags and owned data remain available, including from the baseline Mac client.
5. **Given** an unavailable method or a delivery/provider failure, **When** the user attempts login, **Then** no session is created and a clear retry/alternative action is available without exposing account existence or setup secrets.

### User Story 2 - Recover access and confirm account changes (Priority: P1)

A password user who forgot their password can recover access through their account email. An account holder can confirm a new email before switching it. A person without a password can confirm ownership with a linked login method before sensitive account actions; they can still export and delete their account.

**Why this priority**: adding identities without passwords must not remove access to existing privacy rights or leave users without recovery.

**Independent Test**: reset a password with a one-use email proof, verify a new address before an email change, and export/delete a social-only account after recent confirmation.

**Acceptance Scenarios**:

1. **Given** an existing eligible account email, **When** the user requests password recovery, **Then** the public response is neutral and a time-limited proof is delivered; valid confirmation lets them choose a password and revokes existing sessions.
2. **Given** an unknown, reserved or ineligible address, **When** recovery is requested, **Then** the public response has the same status and wording, without creating an account or revealing eligibility.
3. **Given** a signed-in user, **When** they propose a new email, **Then** the old address stays in effect until recent ownership proof and confirmation of the new address succeed. Conflicts and reserved addresses fail generically.
4. **Given** a social/email-only user, **When** they recently confirm through a method bound to that same account, **Then** setting/changing credentials or requesting deletion is possible without inventing a password requirement. They may add a password and use the existing password-only Mac login for the same account.
5. **Given** an account being purged, **When** a stale recovery, login or link proof is submitted, **Then** it cannot resurrect the account, create orphaned credentials or grant a session.

### User Story 3 - Add a login method to the same account (Priority: P1)

An account holder connects Google or Apple from account settings. They can remove a connected method after confirming ownership, provided another usable method remains. Matching emails alone do not authorize a link or merge.

**Why this priority**: protects existing data from account confusion, provider email changes and pre-hijacking.

**Independent Test**: link a provider after confirming the existing account; then sign in with it and read the same workspace. Try linking an identity already owned by another account and removing the last usable method.

**Acceptance Scenarios**:

1. **Given** a recently confirmed account, **When** a fresh valid provider proof is completed in a link flow bound to that account, **Then** the provider is connected to that account, not a new one.
2. **Given** a provider login whose address matches an existing account but has no binding, **When** the provider proof succeeds, **Then** the user is asked to sign into that existing account before connecting; no automatic merge or session for the existing account occurs.
3. **Given** a provider identity already bound to another account, **When** linking is attempted, **Then** the identity and both accounts remain unchanged and the rejection is generic.
4. **Given** only one usable method remains, **When** its removal is requested, **Then** removal is blocked with an explanation and an action to add another method.
5. **Given** a cancelled provider dialog, **When** the user returns, **Then** account settings and existing sessions remain unchanged and can be used again.

### User Story 4 - Sign in on iPhone without losing local work (Priority: P1)

An iPhone user can choose any configured method while keeping local tasks. A linked device with an ended session signs back into the same immutable account; a different account requires the existing explicit sign-out flow. Authentication failure does not change local ownership or erase pending work.

**Why this priority**: iOS is offline first; login is an access boundary, not permission to reassign the device's data.

**Independent Test**: keep unsent tasks, expire the session, attempt another account and interrupt provider/email login. Confirm tasks remain local and only the correct account resumes sync.

**Acceptance Scenarios**:

1. **Given** an unlinked device with local tasks, **When** valid login completes, **Then** the existing merge/sync workflow runs for the authenticated account and retains those tasks.
2. **Given** an iOS device linked to account A, **When** account B completes a modern login attempt (including its password alternative), **Then** no task is uploaded to B and account A's pending work remains available; explain the sign-out requirement. The existing shared legacy password interface remains compatible for Mac 021.
3. **Given** a linked account whose email changed, **When** the same immutable account signs in again through a bound method, **Then** sync resumes without treating it as a different owner.
4. **Given** no network, expired proof or cancelled browser/native dialog, **When** login cannot finish, **Then** local capture remains available and no local data or valid current credential is discarded.

### User Story 5 - Understand and exercise privacy rights (Priority: P2)

The user can see connected methods and a verified address, obtain an export without auth secrets, and request deletion regardless of whether a password exists. Provider processing and retention are described accurately.

**Why this priority**: these are existing account rights and apply to the new identity records.

**Independent Test**: export and purge an account with linked methods and pending proofs; inspect the archive, deleted records and content-free audit events.

**Acceptance Scenarios**:

1. **Given** linked methods, **When** account data is exported, **Then** safe linked-method metadata is included and no usable credential, proof, token or password hash is included.
2. **Given** a valid deletion request, **When** the existing grace period expires and purge completes, **Then** new account-owned identity/proof records are removed together with the existing owned data.
3. **Given** a successful login inside the existing cancellable deletion grace period, **Then** the existing cancellation behavior is preserved and clearly disclosed; a past-due account cannot be restored.
4. **Given** a login method, **When** the user reviews privacy information, **Then** identity scopes, processors and retention are stated without claiming unverified processor agreements or legal certification.
5. **Given** an Apple binding, **When** it is removed or its account is deleted, **Then** the provider grant is revoked with bounded retry and the account purge deadline remains unchanged if Apple is unavailable.
6. **Given** an authentic, non-replayed Apple revocation notice, **When** the affected binding is resolved, **Then** its authority and affected sessions end without erasing BrainBuddy content or authorizing a different account.

### Edge Cases

- Invalid, expired, wrong-purpose, replayed, concurrently consumed and brute-forced email proofs never grant access; resend does not reset the account-wide attempt budget.
- Email delivery timeout/failure leaves no usable undelivered proof. A timed-out browser request must not automatically send another email; the user controls retries.
- Returning provider identity without an email uses its existing binding; a new identity without a verified usable email receives an actionable rejection. Apple's one-time name disclosure is optional profile metadata, never identity authority.
- Apple relay addresses are valid addresses. Sending to them requires the configured sender to meet Apple's relay requirements; delivery failure offers another connected method.
- Unverified provider email, wrong intended audience/issuer, unsupported assertion algorithm, stale proof, mismatched browser request or substituted native callback is rejected before creating an account/session/binding.
- Password-only legacy email addresses were never verified. A provider collision requires proof of the existing account; no migration marks such addresses as verified without proof. Recovery and email-code eligibility follow FR-014 rather than blindly trusting a stored address.
- Concurrent signup, linking, email change, last-method removal and purge preserve uniqueness and prevent dangling bindings. A failed operation leaves either the prior state or a recoverable committed state, without partial authorization.
- Configured operator addresses cannot be claimed through signup, provider login, linking, recovery or email change; new methods do not weaken seeded operator authentication.
- Browser back/refresh and app termination never replay a proof or put a raw session token in a URL. Login redirects accept only allowed application destinations.
- Provider or mail-service quotas do not trigger a new paid plan. Other configured methods and existing password login remain available when a provider is unavailable.
- Account methods are not gated by member rollout flags: export/deletion rights remain accessible. Availability of public login methods is determined safely by actual deployment configuration.
- Invalid, replayed or unrelated provider notices cannot alter a binding, account or session. Provider revocation failures do not postpone local account erasure or retain cleanup credentials indefinitely.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Ordinary new users MUST be able to create an account and sign in with configured Google, Apple or email-code methods without an invite or manual account approval.
- **FR-002**: Existing password login, opaque application sessions, logout, account IDs, owned data and native password/session compatibility MUST remain usable. New methods MUST use the same account/session authority, not a second task owner system. Preserve existing native sign-in interfaces and 021's Keychain/queued logout/client identity integration; additions MUST NOT replace the Mac password flow. A new user MUST be able to add a password after recent confirmation to use the password-only Mac slice.
- **FR-003**: The application MUST advertise only configured usable methods. If availability cannot be loaded, show a retry action and the existing password alternative; configuration values and secrets MUST NOT enter the public availability response.
- **FR-004**: Provider login MUST prove the intended provider identity and the originating login attempt. A stable provider identity, not a mutable email/name, MUST identify a returning binding; reject unverified or mismatched proofs before state mutation.
- **FR-005**: A provider address matching an existing account MUST NOT authorize automatic linking or merging. The user MUST authenticate the existing account and explicitly complete a fresh link flow bound to that account.
- **FR-006**: A provider identity MUST bind to at most one BrainBuddy account. Linking/unlinking and sensitive account changes MUST require confirmation of the same account within the preceding five minutes, bound to the acting session and intended purpose.
- **FR-007**: Users MUST see safe connected-method and email-verification metadata and be able to add/remove supported methods. Removing the last usable method MUST fail with an action to establish an alternative; a transient availability response MUST NOT rewrite bindings.
- **FR-008**: Email login codes MUST be six digits, single use, expire within the ten-minute outer challenge lifetime, be bound to their address/intent and initiating client, and have at most five verification attempts per challenge. Resend MUST NOT extend that outer lifetime; display the actual remaining expiry. No proof may be accepted twice under concurrent requests.
- **FR-009**: Email delivery and verification MUST have persistent per-address and per-client abuse budgets, a minimum 60-second resend interval and bounded challenge cleanup. Creating/resending a challenge MUST NOT reset a shared verification budget; restart MUST NOT erase it.
- **FR-010**: Public email login/recovery responses MUST use neutral status/wording independent of account eligibility. Deliver only the proof relevant to the accepted operation; do not log, export or publicly return codes or usable credentials. Delivery errors MUST be actionable without exposing provider internals.
- **FR-011**: Password recovery MUST prove control of an eligible account address with a one-use, intent-bound proof, expire it after at most ten minutes, enforce the existing password policy and revoke all previous sessions after a successful reset. It MUST NOT silently create an account, bind a provider or cancel a due purge.
- **FR-012**: The modern email-change flow MUST require recent proof of the current account plus verification of the new address. Keep the old address until both succeed; reject conflicts/reserved addresses generically and preserve atomic account/index consistency. Existing legacy password-protected email-management API semantics remain compatible, but changing through that path MUST clear mailbox verification and invalidate old-address proofs; it MUST NOT establish email-code/recovery authority without subsequent authenticated verification.
- **FR-013**: Passwordless users MUST retain sensitive account and privacy actions by recent confirmation through a method already bound to the same account. A freshly verified credential MAY satisfy recent confirmation; existing password rechecks remain supported for compatible clients. Set/change password only through the existing password policy; do not count an unset password as a usable method. iOS account settings MUST expose account management and a direct account-deletion destination for the linked account, without placing a usable session credential in a URL or silently signing out/discarding its local work.
- **FR-014**: Legacy unverified addresses MUST NOT be relabelled verified by migration or by a social email match. First email-code access to such an account MUST require proof of the existing account before establishing the verified email method. Recovery for such an account MUST fail neutrally until its address has been verified from an authenticated account; existing password access and operator support remain available. This prevents adding an email recovery authority to previously unverified/possibly mistyped addresses.
- **FR-015**: Modern native sign-in MUST bind the result to the initiating app attempt and its expected immutable account, keep usable application-session/provider credentials out of URLs and server secrets out of client bundles, and reject a different owner before starting sync or altering linked ownership. A short-lived one-use authorization handoff code MAY use the fixed callback only when it also requires the initiating client's secret verifier; it MUST NOT be a session or a poll-retrievable result. Preserve the existing shared legacy password interface for Mac 021. Native app dependencies MUST follow the existing platform constraints.
- **FR-016**: Offline/interrupted/failed login and provider cancellation MUST preserve local tasks, pending changes and existing owner binding. Remote authentication requires a connection; local capture remains available without sign-in.
- **FR-017**: New methods MUST preserve the reserved-operator boundary: ordinary public methods cannot provision or take over a configured operator identity. New external/email methods MUST NOT become a recovery shortcut for the seeded operator account.
- **FR-018**: Account export MUST include safe new personal metadata and exclude all auth secrets. Unlink/purge MUST remove the relevant bindings and account-owned proofs, with idempotent retry after partial purge failure; stale proofs MUST NOT resurrect deleted accounts.
- **FR-019**: The existing 14-day account-deletion grace period, session revocation and in-grace login cancellation behavior MUST be preserved and disclosed. Past-due accounts MUST remain inaccessible through every new method.
- **FR-020**: Privacy/retention documentation MUST identify the new identity/email processing, minimum identity scopes, durable versus short-lived records and cleanup triggers. No consent for AI/content processing is implied by sign-in; actual controller/processor arrangements MUST not be fabricated.
- **FR-021**: Critical authentication actions MUST emit bounded, content-free outcome metadata through existing safe logging with a correlation identifier where available. Logs/telemetry MUST exclude passwords, codes, tokens, provider assertions, unnecessary email/subject payloads and user content; actionable server errors expose only a safe reference.
- **FR-022**: A user action MUST show loading/disabled feedback within 200 ms on the supported reference device, prevent duplicate submission and preserve keyboard focus. Web controls MUST have accessible names, visible focus and keyboard operation; touch targets MUST be at least 44 pt.
- **FR-023**: The implementation MUST require no new paid authentication-service subscription and MUST document the remaining Google/Apple/mail setup, quota limits and secret rotation. Provider/account purchases or production deployment require their existing explicit authorization; unavailable configuration is not a successful live flow.
- **FR-024**: The primary capture → atomic items → clarify/approve → route or CRT candidate → review → evidence semantics MUST remain unchanged. This feature changes private remote access/sync, not task rules, AI consent or Mac UI owned by the concurrent chat.
- **FR-025**: Apple disconnection/account deletion MUST revoke the relevant provider grant with bounded retry; only revocation-required provider credentials may be retained, protected at rest and excluded from logs/exports. A verified provider revocation notice MUST end the affected provider authority/sessions without automatically deleting BrainBuddy content or granting another account access. Provider failure MUST NOT extend the existing account-purge deadline or prevent local erasure; documentation MUST state credential cleanup and notification validation.

### Key Entities *(include if feature involves data)*

- **Account**: the existing immutable owner identity; address verification and optional password status augment it without reassigning owned data.
- **Connected identity**: one verified provider and its stable identity linked to one account; optional safe profile metadata, creation time and unlink lifecycle.
- **Authentication challenge**: a short-lived, purpose-bound attempt with an initiating client, expiration, attempt budget and one terminal outcome; its usable secret is not personal export data.
- **Application session**: the existing revocable credential resolving the current account, with bounded recent-confirmation authority for sensitive operations.
- **Abuse budget**: bounded security metadata limiting challenge delivery/verification across requests and restarts, with documented expiry/cleanup.
- **Provider grant/revocation**: minimum secret authority needed to revoke Apple's connection, plus a bounded retry/verified-notice lifecycle; secret credentials are not returned or exported, and account purge removes them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: New and returning users complete all three configured methods on web and iOS; email login uses two application steps, and ordinary onboarding requires zero invites.
- **SC-002**: Every legacy password/session regression fixture preserves its account ID and owned data; the baseline Mac password/session contract remains compatible.
- **SC-003**: All defined negative proof, replay, collision, owner-mismatch, reserved-operator and concurrency acceptance cases grant zero unauthorized sessions/bindings or cross-owner uploads.
- **SC-004**: A verified password user completes recovery, an authenticated user changes email only after verification, and a passwordless user exports/requests deletion without adding a password first.
- **SC-005**: Export inspections find zero usable auth secrets; completed account purge leaves zero new account-owned bindings/proofs and remains safe under retry.
- **SC-006**: All interrupted/offline/wrong-owner native acceptance cases retain local tasks and pending operations unchanged until the correct account resumes sync.
- **SC-007**: Changed screens pass keyboard/focus and 44-pt checks at desktop and 390×851 mobile sizes with no horizontal overflow; pending feedback appears within 200 ms in the controlled UI acceptance run.
- **SC-008**: Required affected automated suites and independent review pass on the candidate commit; real configured-provider smoke proves each promised live method before production is claimed complete. Mandatory additional auth SaaS subscription cost is €0/month.

## Assumptions

- The owner confirmed that provider accounts exist; exact credentials and sender settings are not present in this workspace. Implement/test flows with deterministic adapters, then configure secrets and collect separate live evidence; do not substitute mock evidence for real provider acceptance.
- Email delivery uses an owner-controlled existing/free service, with its real quotas. No paid upgrade is authorized or automatic. Apple membership already exists per the owner confirmation.
- This is the current small deployment, not a horizontal-scaling redesign. Security invariants and bounded persistent attempt budgets apply regardless of current user count.
- Existing unverified password accounts need a one-time authenticated email verification before email recovery/code login becomes an alternate authority (FR-014). This is a safe compatibility default, not a claim that their historical email was verified.
- Native Mac auth comes from PR #265 in the other chat; its planning artifacts were read before continuing. Coordinate additive shared native API changes against its current candidate; no Mac UI edit or cross-chat implementation duplication is part of this feature. Mac's remembered-email lock needs an integration check when an account address changes; never solve reauthentication by silently discarding its outbox.
- OpenAI login, passkeys, mandatory MFA, team/SSO/role changes, session-management UI, new billing and unrelated task/voice/review work are out of scope.
- Legal controller details and actual processor agreements are supplied/verified by the owner for final disclosures; this feature does not certify GDPR compliance.
