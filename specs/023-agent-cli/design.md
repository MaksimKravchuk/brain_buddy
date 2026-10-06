# Design: Agent-friendly BrainBuddy CLI

Feature: specs/023-agent-cli/. Spec: spec.md; scope clarified 2026-10-06.
Screens: design/terminal.html and design/authorize.html.
Human sign-off: Maksim Kravchuk, 2026-10-06, current conversation: “Да. Отлично” in response to the auth-inclusive interface approval request. This approves the UX; implementation still requires the separate planning-review gate.

## Applicability

Terminal input/output, installation and explicit browser/headless login are user-visible. The static preview illustrates commands; shared provider-login UI is owned by the parallel auth work.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | terminal | Agent workflow | Discovery, task commands, projection, recovery | FR-001–FR-008, FR-012 |
| D-02 | terminal | Installation | Versioned native install and integrity failure | FR-009–FR-012 |
| D-03 | terminal + shared browser auth | Connect an account | Device approval, protected credential reuse, status/logout | FR-007–FR-008, FR-012–FR-014 |

## State inventory

### D-01 — Agent workflow

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| S01 default | Offline discovery | Scoped JSON command metadata | Required inputs and options | FR-004, FR-008 |
| S02 loading | Request in progress | Quiet stdout; bounded wait | No spinner or prompt | FR-003, FR-008 |
| S03 success | Operation completed | One compact JSON document, exit 0 | data; page only for lists | FR-001–FR-005, SC-001 |
| S04 first-run empty | No tasks | Empty data array and page metadata | No invented tasks | FR-003 |
| S05 filtered empty | No matches | Same empty success shape | No extra setup prompt | FR-001, FR-003 |
| S06 invalid input | Invalid args/JSON/missing revision/key | JSON stderr and nonzero exit; no request | invalid_input | FR-004–FR-008, SC-003 |
| S07 access failure | Session/404/403/disabled capability | Status/reference when supplied | authentication/not_found/forbidden | FR-002, FR-006–FR-007 |
| S08 conflict | Stale revision | Server conflict detail and reference | conflict; reread before deliberate retry | FR-005–FR-006, SC-003 |
| S09 server/rate limit | 429/5xx | Error, reference, available Retry-After | rate_limited/server_error | FR-006, SC-003 |
| S10 offline/interrupted | Transport failure during write | Uncertain delivery and supplied key | delivery_unknown:true | FR-005–FR-008, SC-003 |
| S11 partial/truncated | Local list bound | Explicit truncated metadata | Task cursor unchanged | FR-003, FR-008 |
| S12 preview | dry-run | Method, relative path, query, redacted input | No credentials; no network work | FR-004, FR-007 |

### D-02 — Installation

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| S01 default | Installer command | Platform/version selection | Matching archive | FR-009–FR-010 |
| S02 loading | Download | Brief stderr progress | Downloading bb | FR-010 |
| S03 success | Checksum/installation pass | Version, destination, required PATH step | Installed bb | FR-010, SC-005 |
| S04 unsupported | Unknown machine | Nonzero exit before replacement | Unsupported platform | FR-009–FR-010, SC-004 |
| S05 integrity error | Checksum mismatch | Existing binary preserved | Checksum verification failed | FR-010, SC-004 |
| S06 offline/interrupted | Download failure | Nonzero exit; existing binary preserved | Download failed | FR-010 |
| S07 destination error | Cannot install | Failing step and recovery hint | Choose a user-writable directory | FR-010 |

Installer empty/partial business-result states are N/A: one binary is installed. Client business commands execute one request at a time; no new batch protocol.

### D-03 — Connect an account

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| S01 signed out | auth status | Server and signed-out status; no browser opens | Run bb auth login | FR-014 |
| S02 login waiting | Explicit auth login | Browser opened; trusted BrainBuddy verification link and short code on stderr | Confirm this connection in your browser | FR-013, SC-006 |
| S03 headless waiting | login --no-browser or failed browser launch | Same verification link/code usable from another device | Open the link on a device with a browser | FR-013, SC-006 |
| S04 browser approval | User signs in with a configured shared provider | Shared-auth account identity and specific CLI connection to approve | Connect this CLI to the displayed account | FR-013 |
| S05 connected | Approval and credential save succeed | Compact identity/status JSON; secret stays in OS credential store | authenticated:true | FR-007, FR-013–FR-014, SC-006 |
| S06 denied/expired/cancelled | Approval refused, grant times out or Ctrl-C | Explicit outcome; no working session replaced | authorization_denied / authorization_expired | FR-013, SC-006 |
| S07 storage unavailable | Keychain unavailable/locked or save fails | Failure and explicit protected-file/external-secret options; no silent plaintext storage | credential_store_unavailable | FR-007, FR-014 |
| S08 expired connection | Business command gets 401 | Structured auth-required error; no login UI started | Run bb auth login | FR-008, FR-014 |
| S09 server/account mismatch | Credential belongs to another server or identity replacement requested | Refuse credential reuse or implicit account replacement | Confirm the intended server/account | FR-014 |
| S10 logout success | Server revoke and local removal succeed | Compact logged-out result; browser session unaffected | server_revoked:true | FR-014, SC-006 |
| S11 offline logout | Server revoke cannot be confirmed | Local credential removed; remote-revocation failure remains visible | local_cleared:true, server_revoked:false | FR-014 |
| S12 unsupported server | CLI authorization capability absent | Explicit unsupported result and server-upgrade hint | cli_auth_unavailable | FR-013 |

One-time verification codes are intentionally shown to the owner during explicit login, not ordinary business output or telemetry. Polling follows server interval/expiry; pending approval is not a failure or a task-write retry. The narrow approval page is specified below; provider availability comes from the deployed shared-auth system.

### D-03 — Browser approval detail

The new approval page delegates sign-in to the existing shared login route. Provider availability comes from deployed shared auth. This narrow approval surface belongs to this feature; contracts/device-auth.md supplies its exchange and safety rules.

| state | visible content and controls | recovery/accessibility |
|---|---|---|
| B01 signed out | Shared login with safe local approval return destination | Existing login methods; no duplicate provider picker |
| B02 code input | Labelled one-time code input and Continue | Manual entry when fragment missing; no approval on navigation |
| B03 loading | Request loading; Approve disabled | aria-live polite; bounded wait/retry |
| B04 awaiting decision | Signed-in account, BrainBuddy CLI label, matching code/expiry; Approve/Deny | Approve only a code from your own CLI; keyboard buttons/visible focus |
| B05 approved | Connection approved; return to terminal | Success announced; decision cannot be issued again |
| B06 denied | Connection declined; return to terminal | Explicit denial; changing decision requires new login |
| B07 expired/invalid | Code expired/unavailable; start new login/manual code input | No identity/existence leak or extended expiry |
| B08 unavailable | CLI unavailable for this account | Server enforces flag/auth boundary |
| B09 request/decision error | Safe error/reference and Retry | Retain code locally; uncertain decision retries same explicit choice |

Focus policy: B02 focuses the labelled code input on entry. B03 preserves the initiating control focus while disabled and announces immediate Checking this code…; decision sends announce Sending your decision…. B04 focuses the approval heading (tabindex=-1), then normal tab order reaches Approve/Deny. B05/B06/B07/B08 focus their named outcome heading. B09 focuses an error-summary heading, with Retry next in tab order; retry restores the same request/choice and returns focus to the resulting heading. Every browser fetch has AbortController30s timeout.

Concrete recovery copy: B06 Connection declined. Run bb auth login to start again. B08 CLI connections are unavailable for this account. B09 lookup: Could not check this code. Retry. B09 decision: Your decision could not be confirmed. Retry the same choice or check your terminal. Include a safe reference when available; never show success before confirmed approval. No background auto-approval/polling.

Read and validate the code fragment before any authentication redirect, then clear history immediately; never send it in query URLs/analytics. Retain only normalized short user code and <=600s deadline in tab-scoped sessionStorage through password/email/Google/Apple return to allowlisted /cli/authorize. No private device proof enters browser storage. Terminal outcome/expiry/cancel clears retained state; unavailable/stale storage falls back to B02 manual entry. JSON POST lookup keeps codes out of access-log URLs. Identity from /auth/me, deliberate approval only. Stack at390px, no horizontal scroll, accessible labels/visible focus/≥44px controls; screenshots/keyboard/axe checks required. Static preview illustrates B04/B05/B07; tests cover all states.

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01 | bb task add/list/get/update/transition | Task work | FR-001, FR-005 |
| D-01 | bb project/tag/tree/api | Existing named/generic operations | FR-002 |
| D-01 | fields/full/limit/cursor | Explicit output and paging bounds | FR-003, FR-008 |
| D-01 | JSON stdin/file | Noninteractive input | FR-004 |
| D-01 | commands/schema | Offline discovery/scoped live schema | FR-004 |
| D-01 | dry-run | Redacted nonexecuting preview | FR-004, FR-007 |
| D-01 | revision/idempotency key | Existing concurrency/replay controls | FR-005 |
| D-01 | Saved CLI credential or explicit external credential | Shared account authority, isolated by server/account | FR-007, FR-014 |
| D-02 | Unix/PowerShell installer, version/destination | Verified native binary install | FR-009–FR-010 |
| D-03 | bb auth login / --no-browser | Explicit owner authorization through shared browser login | FR-013 |
| D-03 | bb auth status / logout | Inspect identity and remove/revoke CLI access | FR-014 |

### Requirements with no affordance

FR-006 governs output/error behavior. FR-011 governs release authority. FR-012 accompanies controls as documentation.

### Affordances with no requirement

None.

## Primary loop impact

Adds capture, clarification, explicit action and inspection from a terminal. Review/delegation use deployed JSON contracts and consent. An agent-run result never automatically completes a Task.

## Mobile viability

CLI viewport/touch/one-handed navigation are N/A: no native mobile app changes. Headless approval uses the responsive CLI approval page and existing shared login; changed approval states require mobile and keyboard verification in this feature. Terminal output requires no colors, mouse or animation.

## Keyboard and focus

Commands/arguments are keyboard accessible. No terminal GUI tab order, focus restoration or Escape control. Ctrl-C cancels waiting login and interrupts ordinary processes; write recovery remains explicit. The verification link/code supports manual navigation if browser launch fails. Existing shared sign-in accessibility remains owned by shared auth; this feature verifies approval accessibility. Plain help and named arguments provide labels.

## Design authority

Quiet light palette and system fonts from the repository design reference; no external assets. Production terminal output remains plain JSON/text. GTD and Tag vocabulary preserved. Automated design-reference and vocabulary checks are recorded below after the revised design is verified.

2026-10-06 revised-design checks: design-reference validator tests passed (6 tests); forbidden-vocabulary search found zero matches; git diff --check passed. These are documentation checks, not implementation, shared-auth or production acceptance.

## Open decisions for the human

The owner approved the revised terminal interface and browser/headless login on 2026-10-06. No open UX decision remains. Protocol/library/parser/build choices remain technical decisions; see auth-integration.md for the observed shared-auth dependency.
