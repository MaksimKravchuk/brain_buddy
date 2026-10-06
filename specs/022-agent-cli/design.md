# Design: Agent-friendly BrainBuddy CLI

Feature: specs/022-agent-cli/. Spec: spec.md; scope clarified 2026-10-06.
Screens: design/terminal.html.
Human sign-off: pending. Planning and implementation have not started.

## Applicability

Terminal input/output and installation are user-visible. The static preview illustrates commands, not a new graphical app.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | terminal | Agent workflow | Discovery, task commands, projection, recovery | FR-001–FR-008, FR-012 |
| D-02 | terminal | Installation | Versioned native install and integrity failure | FR-009–FR-012 |

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
| D-01 | Protected session input/environment | Existing account authority | FR-007 |
| D-02 | Unix/PowerShell installer, version/destination | Verified native binary install | FR-009–FR-010 |

### Requirements with no affordance

FR-006 governs output/error behavior. FR-011 governs release authority. FR-012 accompanies controls as documentation.

### Affordances with no requirement

None.

## Primary loop impact

Adds capture, clarification, explicit action and inspection from a terminal. Review/delegation use deployed JSON contracts and consent. An agent-run result never automatically completes a Task.

## Mobile viability

Viewport/touch/one-handed navigation are N/A: no mobile surface changes. Terminal output requires no colors, mouse or animation.

## Keyboard and focus

Commands/arguments are keyboard accessible. No GUI tab order, focus restoration or Escape control. Ctrl-C is normal process interruption; write recovery remains explicit. Plain help and named arguments provide labels.

## Design authority

Quiet light palette and system fonts from the repository design reference; no external assets. Production terminal output remains plain JSON/text. GTD and Tag vocabulary preserved. Automated design/vocabulary validation is pending because the managed environment became offline before verification completed.

## Open decisions for the human

Approve the displayed terminal interface before planning, as explicitly required by speckit-design. Library/parser/build choices remain technical decisions.
