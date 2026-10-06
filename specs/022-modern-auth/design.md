# Design: Google, Apple and email authentication

**Feature**: `specs/022-modern-auth/`
**Spec**: `spec.md` (Clarifications settled: 2026-10-06)
**Screens**: [design/auth.html](design/auth.html)
**Captured previews**: [six-screen overview](design/overview.png), [iPhone sign-in](design/iphone-sign-in.png)
**Human sign-off**: approved by the product owner on 2026-10-06. After the screen captures, interactive preview and explicit screen-approval request were presented, the owner replied "Да". This records UX approval only, not a future planning-review digest or release approval.

## Applicability

This feature changes sign-in and account security on web, plus native iOS sign-in/recovery. Six screen families have desktop and phone variants; M-07 shows the small addition to existing iOS Settings. The self-contained preview includes screen/state/surface selectors and a six-screen core overview; those selectors are review tools, not product controls. No provider is called and no email/account operation occurs in the preview.

Sensitive account management stays on the existing responsive web account page. M-04/M-05 are its phone presentation, accessible from iOS's account-settings link; they are not a new parallel native settings subsystem. Native M-01/M-02/M-03/M-06 cover iOS auth/recovery/link handoff; M-05's same-account confirmation semantics also govern native linking. Mac UI belongs to PR #265; preserve its shared native-library and password-session contract.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | desktop web | Sign in or create an account | Google/Apple/email choice with existing-password alternative | FR-001, FR-002, FR-003, FR-022 |
| M-01 | native iOS | Sign in / sign in again | Same methods; preserve linked owner/local work and advanced server setting | FR-001, FR-002, FR-003, FR-015, FR-016, FR-019, FR-022 |
| D-02 | desktop web | Email code | One accessible code field for login, recovery, verification or recent confirmation | FR-008, FR-009, FR-010, FR-011, FR-012, FR-014, FR-022 |
| M-02 | native iOS / phone web | Email code | Same code step with autofill, interruption and same-owner guards | FR-008, FR-009, FR-010, FR-014, FR-015, FR-016, FR-022 |
| D-03 | desktop web | Password recovery / new password | Neutral recovery request, then choose password after proof | FR-002, FR-011, FR-013, FR-014, FR-022 |
| M-03 | native iOS | Password recovery / new password | Restore access without dropping local work | FR-011, FR-014, FR-015, FR-016, FR-022 |
| D-04 | desktop web | Account security | Verify/change email; connect/remove methods; add password; export/delete | FR-002, FR-005, FR-006, FR-007, FR-012, FR-013, FR-014, FR-018, FR-019, FR-020, FR-022 |
| M-04 | phone web | Account security | Responsive existing account page, reachable from native account link | FR-002, FR-005, FR-006, FR-007, FR-012, FR-013, FR-014, FR-018, FR-019, FR-020, FR-022 |
| D-05 | desktop web | Confirm it's you | Recent, action-bound confirmation through already-connected methods | FR-006, FR-007, FR-012, FR-013, FR-022 |
| M-05 | phone web / native link semantics | Confirm it's you | Same-account confirmation; cancel without mutation | FR-006, FR-013, FR-015, FR-016, FR-022 |
| D-06 | desktop web | Connect to your existing account | Explain verified-provider collision and require existing-account login plus explicit link | FR-004, FR-005, FR-006, FR-007, FR-014, FR-022 |
| M-06 | native iOS | Connect to your existing account | Same collision rule; authenticate existing owner before continuing/linking | FR-004, FR-005, FR-006, FR-014, FR-015, FR-016, FR-022 |
| M-07 | native iOS | Existing Settings account section | Manage-account and direct deletion destinations for the linked account; leave other Settings unchanged | FR-013, FR-015, FR-016, FR-018, FR-019, FR-022 |

## State inventory

State names below apply separately to both paired screen IDs (for example `D-02.error` and `M-02.error`). A state marked N/A is deliberately not rendered; its reason is stated. The preview's selectors expose representative variants, while native lifecycle and actual remote success remain implementation acceptance work.

### D-01 / M-01 — sign in

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | configured methods loaded | Google, Apple, email field/CTA, password alternative; native cancel and Advanced | "Sign in or create an account" | FR-001/002/003/022, SC-001 |
| loading | method or password request in flight | initiated control busy; prevent duplicate submit; preserve field/focus | "Please wait…" | FR-022, SC-007 |
| empty (first run) | no account/local native account not linked | same entry screen; native explains merge/local preservation without inventing tasks | "Your local tasks are kept if sign-in fails" | FR-001/016, SC-006 |
| empty (filtered to nothing) | N/A | no searchable list on this screen | N/A | FR-003 |
| error | invalid password/provider proof or availability-load failure | safe message/reference, retry or password alternative; unknown availability hides unconfirmed remote choices | "Couldn't sign in. Try again or use another connected method." | FR-003/004/010/021, SC-003 |
| partial failure | Apple unavailable but Google/email/password work | hide unavailable method and retain other actions | "Apple sign-in isn't available right now" | FR-003/010/023, SC-001 |
| offline / interrupted | no network, app/browser interruption or cancellation | preserve local state; remote buttons disabled offline; cancellation leaves form usable | "Your local tasks are kept. Connect to the internet to sign in." | FR-015/016, SC-006 |
| password | password alternative chosen | email/password; password autofill; recovery link | "Use your password" / "Forgot password?" | FR-002/011/014, SC-002/004 |
| linked-owner mismatch | a different account attempted on a linked device | keep pending work and owner binding; return to same-account sign-in | "Sign out first to use another account. Your waiting changes are kept." | FR-015/016, SC-003/006 |
| deletion cancelled | successful login cancels in-grace deletion | disclose before leaving sign-in; explicit acknowledgement; past-due never reaches this state | "Your account deletion was cancelled. Your tasks are kept." | FR-019, SC-004 |

### D-02 / M-02 — code

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | neutral send response | address, single six-digit field, 10-minute expiry and resend countdown | "Check your email" | FR-008/009/010, SC-001 |
| loading | proof verification pending | input kept; Verify disabled, busy feedback | "Checking…" | FR-008/022, SC-007 |
| empty (first run) | code not typed yet | field focused; autofill/paste; no first-run empty illustration | "Email code" | FR-008/022 |
| empty (filtered to nothing) | N/A | no filter/list | N/A | FR-008 |
| error | wrong/expired/replayed code, attempt budget exhausted or delivery failed | generic invalid-proof message or bounded retry time; no session; retain method alternatives | "That code isn't valid or has expired" | FR-008/009/010, SC-003 |
| partial failure | delivery unavailable but other configured methods work | alternative-method action; no blind resend/auto retry | "Use another email or method" | FR-003/009/010/023 |
| offline / interrupted | lost network or app suspend | code/address kept in active UI; never auto-submit on resume; expiration checked by server | "Reconnect before starting another attempt. Your local tasks are kept." | FR-008/015/016, SC-006 |
| legacy unverified address | old password account not eligible for email-code authority | neutral eligibility copy and existing-password/verification guidance; no existence oracle from public request | "Use its existing password, then verify your email in account settings" | FR-010/014, SC-003 |
| intent variants | recovery, verify old/new email, recent confirmation | heading/CTA reflect actual intent; new address remains pending until both proofs | "Verify your new email" / "Confirm your recovery code" | FR-006/011/012/014, SC-004 |

| completion-unknown | verification submitted but response lost | preserve local tasks; check current same-account session/state; if absent get fresh proof, never replay a consumed code automatically | "We couldn't confirm whether this finished. Your local tasks are kept." | FR-008/015/016, SC-006 |

### D-03 / M-03 — recovery / password

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | recovery opened | address field and neutral request copy | "Reset your password" | FR-011/014, SC-004 |
| loading | recovery request or save pending | no duplicate email/send/save; preserve fields | "Please wait…" | FR-009/011/022 |
| empty (first run) | address/new password empty | labelled field and policy guidance; validation on submit | "At least 12 characters. Longer is better." | FR-011/013/022 |
| empty (filtered to nothing) | N/A | no filter/list | N/A | FR-011 |
| error | proof expired, weak/non-matching password, exhausted budget | show field issue or generic proof failure; retry proof if expired | "Couldn't request recovery. Try again in a moment." | FR-009/010/011, SC-003 |
| partial failure | N/A for atomic password save | save is all-or-nothing; delivery failure is error, not partial password rotation | N/A | FR-011 |
| offline / interrupted | offline before submission | reconnect before sending; preserve local native data | "Connect to the internet to continue" | FR-011/016, SC-006 |
| new password | valid recovery proof | new/repeated password and other-session revocation disclosure | "Your other sessions will end after the reset" | FR-011/013, SC-004 |

| completion-unknown | reset save sent but response lost | return to same-account sign-in and try intended new password; if it fails request fresh recovery, never promise old password remains | "We couldn't confirm the reset. Sign in again to check." | FR-011/016, SC-006 |
| reset-success | reset returned 204 | no session; return to D-01/M-01 preserving native expected owner/local work | "Password reset. Sign in with your new password." | FR-011/015/016, SC-004/006 |

### D-04 / M-04 — account security

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | current account/methods loaded | verified address, method status/actions and existing export/delete | "Ways to sign in" / "Your data" | FR-002/005/007/013/018/019, SC-004 |
| loading | method/profile/export action pending | busy on the affected action; unrelated safe content remains readable | "Updating…" | FR-022, SC-007 |
| empty (first run) | password unset/provider not connected | explicit "Not set" / "Not connected" with Add/Connect, not an empty list | "Add password" | FR-002/007/013 |
| empty (filtered to nothing) | N/A | no filter | N/A | FR-007 |
| error | conflict, stale proof or rejected action | previous account/method state retained; safe reference; re-confirm when needed | "Couldn't update your account. Your existing sign-in methods are kept." | FR-006/007/012/021, SC-003 |
| partial failure | methods unavailable while profile loads | show account/profile; disable method mutation and offer retry; never infer disconnected/last method | "Couldn't load all your sign-in methods" | FR-003/007/022 |
| offline / interrupted | offline before submission | show read metadata as stale; reconnect before starting a mutation | "Reconnect to manage your account" | FR-012/013/022 |
| unverified email | old password address not yet confirmed | Send code action; email-code/recovery unavailable until authenticated verification succeeds | "Enable email codes and password recovery" | FR-014, SC-004 |
| email-change editor | Change email | new address input; recent-confirmation step then new-address code; old email stays in effect | "Your current email stays in use until both steps succeed" | FR-006/012, SC-004 |
| add/change password | Add/change selected | existing policy; recent confirmation; no generated password; usable on password-only Mac | "Not set · also used for Mac sign-in" | FR-002/013, SC-002/004 |
| last method | authoritative server denies removal | explanation and add-method action; existing binding retained | "Add another way to sign in before removing this one" | FR-007, SC-003 |
| deletion confirmation | Delete selected after recent proof | grace/session consequences; Keep account default; explicit destructive confirmation | "Your sessions will end now … permanently removed after 14 days" | FR-013/018/019, SC-004/005 |

| unlink-confirmation | Remove chosen | name provider; lost-method and provider-session consequences; explicit Remove / Keep method; confirm recent ownership separately before mutation | "Remove Google? You won't be able to sign in with Google. Sessions started with it will end, including this one if you used Google here." | FR-006/007/013, SC-003 |
| completion-unknown | account action sent but response lost | refresh safe same-account metadata; session loss routes to same-account sign-in; then obtain fresh action proof if still needed | "We couldn't confirm whether this finished. Check your account after reconnecting." | FR-012/013/016/022, SC-006 |
| unlink-signed-out | successful unlink revoked acting session | remaining methods displayed safely; route to D-01/M-01 with expected owner and result notice; no claim local native sign-out | "Google was removed. Sign in again with a remaining method." | FR-007/015/016, SC-003/006 |
| apple-cleanup-pending | local Apple unlink or deletion scheduling committed; remote revoke pending | result notice on account screen or same-account sign-in when sessions ended | "BrainBuddy access was removed. Apple cleanup is being retried. Your account deletion date is unchanged." | FR-019/025, SC-005 |
| apple-cleanup-unconfirmed | local action succeeded; bounded remote revoke not confirmed | retain local-success disclosure; no retry claim after bound; sign-in result banner remains visible after cookie clear | "BrainBuddy access was removed. We couldn't confirm Apple cleanup. Your account deletion date is unchanged." | FR-019/025, SC-005 |

### D-05 / M-05 — recent confirmation

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | sensitive action requires recent proof | expected account and only its already-connected usable methods | "Confirm it's you" | FR-006/013/015, SC-003/004 |
| loading | proof pending | acting action fixed; duplicate controls disabled; Cancel preserves account | "Please wait…" | FR-006/022 |
| empty (first run) | N/A | no account creation within reauthentication; unset password is not offered | N/A | FR-006/013 |
| empty (filtered to nothing) | N/A | no filter/list; no usable proof becomes an actionable error | N/A | FR-006 |
| error | wrong account, invalid/expired proof | no sensitive action; keep pending form/action; retry same-account confirmation | "Couldn't sign in. Try again or use another connected method." | FR-006/015/021, SC-003 |
| partial failure | one connected provider unavailable | retain other already-connected methods; do not offer unbound Apple/Google as recovery | "Use another connected method" | FR-003/006/013 |
| offline / interrupted | cancel/offline | unchanged account/form; restore opening action's focus; explicit retry | "Your account and tasks stay unchanged if you cancel" | FR-006/016/022 |
| legacy password | address unverified, password exists | current-password form, no unavailable email-code authority | "Confirm with your existing password" | FR-002/013/014 |

### D-06 / M-06 — provider collision

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | verified provider address matches an unbound existing account | explain existing-account proof and separate explicit connection; no automatic merge | "Connect to your existing account" | FR-004/005/014, SC-003 |
| loading | existing-account login or fresh link pending | preserve intended provider/account; no duplicate linking | "Please wait…" | FR-005/006/022 |
| empty (first run) | N/A | truly new eligible identity creates an account through D-01/M-01, not this collision screen | N/A | FR-001/004 |
| empty (filtered to nothing) | N/A | no filter/list | N/A | FR-005 |
| error | identity bound elsewhere, fresh link expired or account mismatch | no merge or ownership change; retry authenticated linking; generic conflict wording | "Couldn't connect this method. Try again from your account." | FR-004/005/006, SC-003 |
| partial failure | existing login succeeds but connection fails | user can retain existing-account access; provider remains unconnected; explicit retry from settings/native link continuation | "Your account is signed in. This method wasn't connected." | FR-005/007 |
| offline / interrupted | cancellation or offline before link submission | no link submitted; preserve local ownership; continue with existing methods when online | "Linking was cancelled before submission. Your tasks are kept." | FR-005/015/016, SC-006 |
| completion-unknown | link submitted but response lost | reuse D-04/M-04 completion-unknown: refresh same-account method metadata, get fresh link proof only if still needed; never replay consumed proof | "We couldn't confirm whether linking finished. Reconnect and check your sign-in methods." | FR-005/006/015/016, SC-006 |

### M-07 — iOS account entry states

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | linked account | existing account identity/server plus two direct web destinations | "Manage account" / "Delete account" | FR-013/015/018, SC-004 |
| loading | external account destination opens | no native logout or mutation; normal browser transition | no added blocking UI | FR-013/016 |
| empty (first run) | no linked account | existing local-only Settings/Sign in; new management links absent | existing copy preserved | FR-002/016 |
| empty (filtered to nothing) | N/A | no filter | N/A | FR-013 |
| error | invalid/unavailable account destination or wrong web account | safe error/retry or same-account web login; never include a token in the link or act on a different web account by accident | "Use the account linked to this iPhone" | FR-013/015/021 |
| partial failure | N/A | opening a web destination changes no native records | N/A | FR-016 |
| offline / interrupted | browser fails/cancelled | return to unchanged native Settings/local workspace; account page can be retried later | no data removal | FR-013/016, SC-006 |

The direct deletion entry is necessary when the app now supports account creation. Apple's current guidance permits a direct link to the page where the deletion can be completed; a generic homepage/support link is insufficient. Source checked 2026-10-06: https://developer.apple.com/support/offering-account-deletion-in-your-app/. Provider revocation is a server invariant (FR-025), not an extra deletion button or another native settings system.

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01/M-01 | Google/Apple button | starts the chosen configured proof flow | FR-001, FR-003, FR-004 |
| D-01/M-01 | email + Continue | neutral code request; create/login only after valid proof | FR-001, FR-008, FR-009, FR-010 |
| D-01/M-01 | Use your password | existing password and account session | FR-002, FR-014 |
| M-01 | Cancel / Advanced | preserve local data; retain existing secure server selection/account binding | FR-002, FR-015, FR-016 |
| D-01/M-01 | safe error / retry / password alternative | recover unavailable configuration, no exposed secrets | FR-003, FR-010, FR-021, FR-023 |
| D-01/M-01 | deletion acknowledgement | disclose existing in-grace cancellation | FR-019 |
| D-01/M-01/D-04/M-04 | Privacy policy | explain identity/email processing without extra data access | FR-020 |
| D-02/M-02 | code field + Verify | purpose-bound one-use proof, no duplicate acceptance | FR-008, FR-011, FR-012, FR-014, FR-015 |
| D-02/M-02 | countdown + resend + Back | bounded user-controlled retry and alternative method | FR-009, FR-010, FR-016 |
| D-03/M-03 | recovery email request | neutral eligible-account recovery | FR-010, FR-011, FR-014 |
| D-03/M-03/D-04/M-04 | password form/policy | reset or establish password after intended proof | FR-002, FR-011, FR-013 |
| D-04/M-04 | Verify email / Change email | authenticated verification and pending new-address proof | FR-006, FR-012, FR-014 |
| D-04/M-04 | method status/Connect/Remove | same-account explicit link/unlink; block last method | FR-005, FR-006, FR-007, FR-013 |
| D-04/M-04 | Export / Delete / Keep account | existing data rights with passwordless-compatible proof and disclosure | FR-013, FR-018, FR-019 |
| D-05/M-05 | connected provider/code/password | recent confirmation of expected account and acting purpose | FR-006, FR-013, FR-015 |
| D-05/M-05 | Cancel | no mutation, restore previous action | FR-006, FR-016, FR-022 |
| D-06/M-06 | existing-account login / explicit Connect / another provider identity / Cancel | no email-only merge; confirm actual owner then fresh link | FR-004, FR-005, FR-006, FR-014, FR-016 |
| M-07 | Manage account / Delete account | direct same-account web destinations; no session secret in URL; keep native pending work | FR-013, FR-015, FR-016, FR-018, FR-019 |
| all | labelled fields, focus ring, busy feedback, safe reference | keyboard/touch accessibility and actionable failures | FR-021, FR-022 |

### Requirements with no affordance

- FR-004's assertion/browser-origin validation; FR-006's binding and expiry enforcement; FR-008/009 proof consumption/persistent budgets; FR-010 neutral eligibility, FR-011 session revocation; FR-012 atomic commit; FR-015 callback/session handling; FR-017 reserved operator policy; FR-018 purge/export secret filtering; FR-021 log filtering are server/native invariants behind the mapped actions. They intentionally have no additional user controls.
- FR-023's no-subscription constraint, provider setup and quota/rotation guide are operational documentation; a user receives a usable-method choice/error, not deployment settings.
- FR-024 preserves primary-loop semantics and concurrent Mac ownership. No task, voice, review or Mac screen is introduced by this design.
- FR-025 validates provider notices, revokes Apple grants and expires retry credentials without extending purge. It has no new UI control beyond the mapped Remove/Delete actions and their truthful result/error.

### Affordances with no requirement

None in product screens. Screen/state/surface preview selectors and the Overview option are review-only tooling and do not ship.

## Primary loop impact

Remote private access and sync become available through more proofs of the same account. Capture → atomic items → clarify/approve → route or CRT candidate → smart Weekly Review → evidence/results semantics are unchanged. Local iOS capture/outbox remains usable while authentication is unavailable. No canonical Task is created, reassigned or discarded by an auth failure.

## Mobile viability

- **Viewport**: 390×851 target; Chromium checked 84 screen/state/viewport combinations at widths 390 and 1440 with no horizontal overflow. Native screens use a scrollable sheet/form for keyboard and larger text, not a fixed-height card.
- **Tap targets**: 44 pt minimum for buttons, inputs and links. One whole code field supports paste/autofill; avoid six independently focused boxes.
- **One-handed reach**: full-width primary action follows its field; iOS cancel remains in the sheet header. A failed login keeps the local workspace available after cancel.
- **Destructive actions**: Keep account default; permanent deletion after 14 days and immediate session termination are stated. Existing device sign-out warnings/outbox cleanup from 021 are preserved and do not happen implicitly during this feature's sign-in.
- **Account management**: M-04/M-05 use the existing web page on phone; native account links open the relevant account/deletion destination directly. Reauthentication must be possible with the same methods there.

## Keyboard and focus

- **Tab order**: provider buttons → email → Continue → password alternative → Advanced (native external keyboard) → privacy. Code: field → Verify → enabled resend → alternate method. Security: email action → method actions → export → deletion. Confirmation: connected method controls → Cancel.
- **Focus on open**: email for first sign-in, code after request, current password for legacy confirmation; recover/edit form starts at its first field. Error announcements do not move focus. **Focus restored on close to**: the opening method/action, or sign-in email after Back. After native success, return to the existing workspace without changing selection.
- **Escape**: cancel provider/account-confirmation or inline editor; restore opener. It does not silently delete an account or discard local changes.
- **Accessible names**: text labels on every action; logo decorative with a visible Brain Buddy name; code field has expiry description and numeric/autofill hints.
- **State communicated by color alone**: none. Verification/connection/error states have words; no purely colored badge claims success.
- **Password managers**: current-password/username for existing login; new-password for reset/add; email and one-time-code for mail proofs. Labels remain visible after input.

## Design authority

- Tokens/type/radii from `brain-buddy-design`; source Sprout geometry copied from `assets/logo.svg`, not redesigned.
- Sky-700 filled controls/text links keep contrast on white; slate neutrals and double-ring focus. Native uses system type; offline static preview declares Inter with a system fallback and requests no remote font. Production uses existing font delivery.
- Provider buttons use approved provider/system assets in implementation. The static preview uses provider names in their slots; no invented provider mark or embedded third-party login script.
- Vocabulary check (ADR-0006, Tag vocabulary): zero forbidden-term hits in `design.md` and the HTML (2026-10-06).
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`: 6 passed on 2026-10-06.

## Preview verification evidence

Chromium/Playwright verification on 2026-10-06 is captured in [design/preview-check.json](design/preview-check.json), bound to HTML SHA-256 `3effd3cab53f1cc60223657956b578972e0e7c3de3ac5f24a347d897bf6fcd91`.

- 154 combinations: seven screens × eleven representative states × two viewport widths; zero horizontal overflow or visible controls shorter than 44 CSS pixels.
- Axe checked all seven default screens and the code-error and unlink-confirmation screens at both widths (18 checks); zero reported accessibility violations.
- No browser JavaScript errors. Mock interactions verified email request → focused code field → account, then email change → recent confirmation → new-address proof; unlink consequences → Keep/Remove → signed-out result; reset → sign-in success notice. Reviewer-correction captures: [unlink](design/unlink-confirmation.png), [uncertain completion](design/completion-unknown.png), [reset result](design/reset-success.png), [Apple cleanup](design/apple-cleanup-pending.png).
- The overview and iPhone captures above come from that source. Visual inspection confirmed readable single-column phone presentation and the six-screen desktop overview.

These are static prototype checks only. They establish no live provider, mail delivery, production authentication, native SwiftUI behavior or account mutation evidence. Implementation acceptance must test those separately, including dynamic type and native keyboard behavior.

## Open decisions for the human

No open product decision remains at this stage. The owner approved these actual screens: provider/email choice with a password alternative, one code field, and connected methods together with existing data rights in account settings. Technical planning may proceed. Reviewer corrections clarify consequences and uncertain outcomes within these approved screen families; they add no provider, account scope or product decision.
