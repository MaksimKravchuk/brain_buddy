# Business Intake: Google, Apple and email authentication

**Feature**: `specs/023-modern-auth/`
**Interviewed**: 2026-10-06
**Interviewee**: product owner, through the current conversation
**Status**: scope and non-goals confirmed by the owner; specification/design stage

Assessment was skipped: the owner explicitly requested this established product capability after discussing alternatives and asked for implementation. No matching authentication assessment or kill decision exists under `.specify/assessments/`. Existing password/session authentication ships already; this request extends it rather than replacing it with a separate identity service.

## The ask, as given

> Давай ты сделаешь тогда нормальную систему авторизации, ну, ты уже в принципе все описал, что нужно. Давай ее планировать и имплементировать.

Earlier owner statements establish three priorities:

> я хочу, чтобы там уже сейчас была авторизация через Google, через Apple и через email.

> я в Европе

> я не хочу за это платить.

OpenAI was mentioned as a possible additional method, not a required launch method. The owner described the current product as an early MVP and wanted less approval friction. This is recorded as a preference for low operational friction, not as approval of unseen design or review artifacts.

The owner added during preparation:

> Важно, что базовая авторизация в MacOS приложении сейчас подъедет из другого как бы чата. Я её через Cloud уже имплементирую.

The other chat owns baseline macOS authentication. This work must preserve compatible backend password/session contracts and coordinate any necessary native contract additions; it must not duplicate or overwrite that Mac implementation. The identity scope here remains web and iOS unless the owner changes it.

## 1. Problem

- **Whose problem**: new and existing BrainBuddy users, and the owner configuring authentication for the first time.
- **How it shows up today**: web signup requires an invite and a password; iOS signs in with email/password. There is no Google or Apple login, email verification or password recovery.
- **What it costs**: setup and onboarding friction; forgotten passwords have no self-service recovery. No measured abandonment baseline exists.
- **If we build nothing**: those limitations remain and the requested login methods are unavailable.

## 2. Customer and persona

- **Primary**: an individual using BrainBuddy's private workspace on web and iPhone.
- **Secondary**: the owner administering a small deployment, without specialist identity infrastructure experience.
- **Deployment shape**: multi-tenant application with isolated per-owner data, currently a small MVP. Actual user count is unknown; it must not be asserted to be zero.

## 3. Business objective and KPI

The numerical targets below are proposed release acceptance measures, not fabricated business measurements or owner-approved conversion targets.

| metric | baseline today | proposed target | by when |
|---|---|---|---|
| Supported primary login methods | 1: email/password | 3: Google, Apple, email code; existing password login retained | candidate release |
| Invite approvals required for ordinary onboarding | 1 invite required | 0 | candidate release |
| Existing account IDs and owned data preserved through rollout | current account/data fixtures | 100% of migration and regression fixtures | candidate release |
| Cross-account access granted by invalid login/link attempts | security invariant | 0 in the negative acceptance cases | candidate release |
| Mandatory new subscription for the authentication service | none today | €0/month | candidate release |

No adoption deadline or post-release conversion target was supplied by the owner.

## 4. Scope boundary

**In scope — confirmed playback**

- [ ] Google and Apple sign-in, on web and iOS, with provider identity verification.
- [ ] Email sign-in using a short-lived one-use code; successful verification creates an account or signs into the existing one. Existing email/password login continues to work.
- [ ] Ordinary onboarding without invites or manual account approval, with abuse controls and existing reserved operator-address protections.
- [ ] Self-service password recovery and verified email changes for existing users.
- [ ] Explicit linking/unlinking of login methods, after confirming account ownership; prevent removal of the last usable method and never merge accounts solely because provider emails match.
- [ ] Sensitive account actions remain available without a password through recent proof of account ownership. Data export and the existing deletion/grace/purge lifecycle include the new identity records safely.
- [ ] Web and iOS show configured login methods and actionable retry/cancellation/error states. iOS preserves local tasks, account binding and pending changes when login fails or a session expires.
- [ ] Configuration guide for the required provider applications and email delivery, plus an updated privacy/retention inventory and meaningful auth regression tests.

**Out of scope — explicitly confirmed by the human**

- [ ] OpenAI login for the first release; it was optional in the owner request.
- [ ] A paid authentication SaaS, billing changes, team accounts, enterprise SSO, new roles or access to another user's content.
- [ ] Passkeys and mandatory MFA in this slice; these require a separate accepted scope.
- [ ] Implementing baseline macOS authentication in this branch: the owner is implementing it in another chat. Adding the new social/email-code UI to Mac, redesigning tasks/voice/Weekly Review or changing AI processing consent is also outside this proposed slice.
- [ ] Purchasing an Apple Developer membership, an email plan or a domain; no new paid service may be silently required or provisioned.
- [ ] Claiming legal GDPR certification, signing processor agreements or publishing a release before the required release approval.

**Confirmed by**: product owner on 2026-10-06, after the numbered scope/non-goals playback and Google/Apple setup explanation: "Да. Все есть". This confirms the described scope and provider-account availability; it is not represented as approval of a future unseen design or planning-review digest.

The owner first asked what Google and Apple setup requires. After the explanation and the membership question, "Да. Все есть" confirmed scope and availability of the accounts, including Apple membership. Exact credentials and mail sender settings must still be configured through secret storage.

## 5. Constraints

- **Deadline**: none supplied; implement now after required repository gates.
- **Platform**: web and iOS proposed because both currently use the same account backend.
- **Offline behavior**: retain offline iOS task capture and queued sync. Remote authentication requires connectivity; failure must never erase local work or upload it to a different account.
- **Must not break**: existing account IDs, password sessions, owner isolation, seeded operator protections, admin account lifecycle, account export/deletion and feature-flag resolution. Keep the baseline macOS auth work from the other chat compatible with backend password login and cookie sessions; do not edit its files or introduce an uncoordinated breaking native API change.
- **Budget / provider cost limits**: no mandatory new auth-service subscription. Reuse the deployed backend. Email delivery requires a configured mail service and sender; a free tier has quotas. Apple provider setup depends on the owner's developer account. Existing infrastructure costs remain unknown. Stop before introducing any new unavoidable paid dependency.
- **Setup friction**: implement the flows and provide a bounded setup checklist. Provider registration and credentials cannot be replaced by code or silently created using another identity.

### Provider setup facts checked during the interview

- **Google**: an owner-controlled Google Cloud project, app name/contact/privacy information, an OAuth web client, Client ID/Client Secret and registered HTTPS callback addresses. OAuth setup itself does not require a paid authentication subscription. Do not enable unrelated billable Cloud services. Native implementation details are deferred to the technical plan; do not embed a server secret in a native binary.
- **Apple native**: an App ID with Sign in with Apple enabled and the app's matching signing capability. Existing app identifiers come from project configuration, not invented constants.
- **Apple web**: a Services ID associated with a primary App ID that has Sign in with Apple enabled, configured domain/return URLs, and an owner-controlled private key with its Key ID and Team ID for the server exchange. Apple's current documentation explicitly says domain registration does not require uploading a verification file to the server; do not add obsolete hosting work for that purpose.
- **Apple cost**: Apple Developer Program is 99 USD per membership year, with region-specific local-currency pricing and certain fee-waiver categories. The owner's "Все есть" confirms existing membership, so no new membership purchase is needed or authorized and Sign in with Apple has no separate fee.
- **Secrets**: owner adds credentials through deployment secret storage. Private keys and client secrets must not be sent in chat, committed to the repository or copied into a client bundle. Credentials are needed for live activation, not for preparing and testing the implementation.

Official references read on 2026-10-06:

- https://developers.google.com/identity/protocols/oauth2
- https://support.google.com/cloud/answer/15549257?hl=en
- https://developer.apple.com/help/account/capabilities/configure-sign-in-with-apple-for-the-web/
- https://developer.apple.com/programs/enroll/

## 6. Compliance obligation

`AccountService` already provides self-serve profile/email/password, ZIP export, a 14-day deletion grace period and purge. Extend that baseline to identities without passwords.

- **New durable records**: verified identity provider and subject, email verification metadata, consumed/expiring login challenges, account-linked authentication methods and bounded abuse-protection records. Exact fields and retention belong in the later technical plan.
- **Consent**: the user explicitly chooses a login method. Request only identity scopes required for login; do not request contacts, mail access or AI consent as part of sign-in.
- **Retention**: identity bindings last until unlink or account purge; short-lived challenges expire and are cleaned up. Bound retention for abuse/security metadata, documenting the purpose and cleanup mechanism.
- **Export**: include safe account and linked-provider metadata as personal data; exclude password hashes, session credentials, challenge secrets and provider tokens. Confirm existing ZIP handling never accidentally exports new secrets.
- **Purge**: delete new account-owned identity/challenge records when the account is purged; make cleanup retryable and idempotent. Preserve the existing deletion behavior unless separately agreed.
- **Apple grant cleanup**: unlink/deletion must revoke the provider grant with bounded retry and validate provider revocation notices. Protect the minimum cleanup credentials at rest; exclude them from logs/exports and expire them even if Apple is unavailable. Provider failure does not extend BrainBuddy's purge deadline. Notices end affected provider authority, never automatically erase BrainBuddy content. This implements the confirmed safe unlink/deletion scope and Apple's published account-deletion requirements.
- **Residency / other obligations**: owner is in Europe; country and legal controller details were not supplied. Fly configuration selects Amsterdam. Google/Apple/email processing and possible international transfers must be disclosed; hosting region alone does not establish GDPR compliance. Actual processor agreements must be verified by the owner rather than asserted by the implementation.
- **Security**: no authentication secrets or unnecessary email/identity payloads in logs, browser URLs, exports or committed fixtures; generic public responses and bounded attempts; verify OAuth callback context and provider assertions.

## 7. Existing-system dependencies

- **Backend surfaces**: Identity's existing user/session/invite repositories, authentication service/routes, account service/routes, configuration, rate limiting and safe audit logging; admin lifecycle/export/purge integration where new records require it.
- **Frontend surfaces**: sign-in/signup, auth store and route guard, account settings, recovery/verification screens and privacy policy.
- **Mobile**: iOS sign-in sheet, API/session/sync/workspace integration and generated-project source configuration. Keep third-party dependencies out of the native app and Swift package per `ios/AGENTS.md`.
- **macOS / concurrent work**: baseline authentication is being implemented by another chat (owner statement, 2026-10-06). Preserve its backend contract and avoid overlapping Mac edits. PR #265's specification has now been inspected at the exact head below; it is not a completed implementation and no runtime integration pass is claimed.

Repository investigation found `specs/021-mac-sync/spec.md` on remote `origin/claude/mac-sync-spec` (head `e50b144f15fd9a6a60d6f5f26de7798d1b8700e1` at fetch). Its sign-in story uses the existing email/password account and cookie-session model. This supports additive backend compatibility; it does not establish that this is the owner's exact active implementation or that Mac integration passes. Feature 021 is already reserved across git refs; the next available sequential spec number at preparation time is 022.

After the owner specifically requested checking the current Mac PR before continuing, the branch was fetched again and [PR #265](https://github.com/MaksimKravchuk/brain_buddy/pull/265) was inspected at head `b83d367b30434d1d2448eefdef7043e95dbd9ff6` (open, not merged; documentation artifacts). Read 021's auth requirements, assumptions, native-host contract, shared-kit client contract, session/keychain model and research. The integration baseline is now the PR, not just the earlier branch snapshot:

- 021-FR-001/005 and `contracts/mac-app-host.md` §7 use existing email/password, `Workspace.signIn(serverURL:email:password:)`, session cookies, queued logout and the separate Keychain service `app.brainbuddy.mac.session`.
- Mac adopts `ios/BrainBuddyKit` directly and removes its parallel API/sync stack (021 research R1). Add new native auth methods alongside existing signatures; never replace that shared baseline or create another sync engine.
- 021-FR-004/029 protect pending data and send nothing before sign-in. New iOS auth must preserve the same immutable-account checks, abandoned-session cleanup and offline outbox semantics.
- 021 §kit client identity adds an optional identity argument defaulting to iOS, plus `Workspace.live`/`SyncEngine` device identity. This feature must retain those additions after integration and avoid hard-coded iPhone identity in shared code.
- Mac's first slice is password-only. A new social/email user can establish a password in web account settings after recent confirmation, then use the same account on that Mac. No password is auto-generated or exposed.
- Mac X-03 currently locks the remembered email when a session ended. Account identity is the immutable id/server, not that email. Verify the eventual Mac candidate handles the new-address reauthentication case without asking the user to discard unsent work; any required Mac UI adjustment belongs to the concurrent 021 writer. A document review is not a passing Mac integration test.
- Task/archive changes and compact sync status belong to 021. This feature does not touch those rules or 021's plan/design files.
- **AI providers**: not used by authentication. Existing voice/AI consent is unaffected.
- **Primary loop impact**: authentication gates remote private data access and sync. Capture → clarify/approve → route → review semantics remain unchanged; local capture continues offline.
- **Architecture authority**: ADR-0001 Identity ownership/session reuse, ADR-0017 and ADR-0021 reserved operator identities/content isolation, ADR-0008/0012 ASK security changes and ADR-0023 full-path eligibility. An authentication-assumption change requires a new prospective decision record, not rewriting accepted history.

## 8. Definition of done

- [ ] A new user can use each configured provider or an email code, without an invite, and reaches their own workspace on web and iOS.
- [ ] An existing password user signs into the same account and sees the same data; linking another method requires proof of existing-account ownership.
- [ ] Expired, repeated, invalid and brute-forced email codes and invalid provider assertions cannot create sessions. Callback substitution and cross-account linking are rejected.
- [ ] Password recovery and email change require control of the correct email address; reserved operator identities cannot be claimed through any new path.
- [ ] A user without a password can export and request deletion; secrets stay out of exports and new identity records disappear at purge.
- [ ] Cancellation, unavailable email delivery, expired sessions, provider errors and offline iOS login preserve existing data and offer clear recovery.
- [ ] Required tests, independent planning/implementation review and exact-commit CI pass. Actual provider credentials and test accounts are needed to claim live-provider acceptance; mocked tests are labelled as such.
- [ ] Provider setup instructions name every manual input and free-tier limit. Production activation follows the required explicit release approval and real smoke evidence.

## Deferred to /speckit-clarify

- [x] Confirm scope boundary/non-goals before creating a specification: "Да. Все есть" on 2026-10-06.
- [x] Confirm provider accounts including Apple Developer membership are available: "Все есть". Actual IDs, credentials and sender configuration are deployment inputs, not copied into this intake.
- [ ] Owner's European country/controller details and actual processor agreements are needed for final legal disclosures; avoid delaying generic auth code on those facts.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| Wants the setup to be one button | Google/Apple/mail require owner-controlled registration and credentials | Implement the product flows and minimize/document remaining provider setup; do not promise zero configuration | technical finding, presented for scope confirmation |
| Wants no payment | Email delivery quotas and Apple account eligibility may impose external costs | No auth SaaS subscription or silently purchased service; use existing membership and mail accounts/free quotas | owner confirmed "Все есть"; exact quota and sender settings are deployment inputs |

## Preparation evidence (not implementation acceptance)

- Isolated worktree `/workspace/brain_buddy-auth`, branch `feat/modern-auth`, based on fetched `origin/main` at `35bb95a1e76c1282c2a51a908a933eb4ced3fcbb`.
- Official Spec Kit CLI v1.0.11 verified in an isolated tool environment; no application dependency changed.
- Existing Spec Kit artifact checker passes; staged intake is deliberately not represented as a completed feature package.
- Existing backend auth/account regression subset: **73 passed** (auth service/routes, account service/API, deletion and export). Its Allure taxonomy check passes for all 73 results. This is a focused baseline run with full-suite coverage collection disabled for the selection; it is not a full coverage/CI pass or evidence that any new flow exists.
- `git diff --check` passes. Product source, native project configuration and production deployment are unchanged at this stage.
- Scope/non-goals and provider-account availability are now confirmed. UX sign-off, planning review, implementation and deployment are subsequent gates and are not claimed by this intake.
