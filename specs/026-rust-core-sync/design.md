# Design: Rust core and custom sync

**Feature**: `specs/026-rust-core-sync/`
**Spec**: `spec.md`; this design specifies requirements FR-001–FR-026 for explicit owner sign-off.
**Screens**: [design/sync-states.html](design/sync-states.html), one self-contained static HTML file without external resources.
**Human sign-off**: **pending**. Production implementation has not started; the next architecture stage requires explicit design approval under `.specify/agent-commands/speckit-design/SKILL.md`.

## Applicability

Agreed direction: a shared Rust core and custom synchronization. iOS and macOS already use `BrainBuddyKit`: this replaces the internal implementation while preserving existing behavior, rather than creating a second independent task engine. This design covers only states of the existing sync row, Sync settings / popover, existing resolution card, and AI settings. A new task workspace, navigation, a fifth GTD list, autonomous agents, and new onboarding are outside the design.

Explanatory notes and all product copy are in English. D- denotes desktop/macOS; M- denotes iPhone. Web preserves existing online workflows (FR-024); the desktop mock introduces neither offline web nor a new web sync panel. AI consent also applies to the existing web flow, without a new page.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| M-01 | iPhone, existing row and Settings › Sync | Sync status | Local work, queue, and diagnostics without interrupting capture | FR-001, FR-003, FR-004, FR-005, FR-010, FR-011, FR-012, FR-023, FR-026 |
| D-01 | Mac, existing row and popover | Sync status | Same semantics, full last-sync timestamp, and safe reference ID | FR-001, FR-003, FR-004, FR-005, FR-010, FR-011, FR-012, FR-023, FR-026 |
| M-02 | iPhone, Sync issues detail | Resolve conflict | Preserve the user's edit; explicitly choose the result | FR-007, FR-008 |
| D-02 | Mac, detail sheet from Sync issues | Resolve conflict | Compare conflicting versions and confirm the resolution | FR-007, FR-008 |
| M-03 | iPhone, existing Sync settings / sheets | Recover sync | Resume/reset, upgrade, migration, and account switching without losing pending edits | FR-010, FR-011, FR-012, FR-013, FR-022 |
| D-03 | Mac, existing popover / sheets | Recover sync | Same behavior; migration file and safe recovery | FR-010, FR-011, FR-012, FR-013, FR-022 |
| M-04 | iPhone, existing review card / AI settings | AI choice, consent and proposal | On-device policy, separate cloud consent, and explicit apply only | FR-016, FR-018, FR-019, FR-020, FR-022 |
| D-04 | Mac, existing review card / AI settings | AI choice, consent and proposal | Same authority/privacy sequence; existing web consent is equivalent | FR-016, FR-018, FR-019, FR-020, FR-022, FR-024 |

All eight screens are represented in HTML. The paired tables below define the same states for **each** listed ID: 45 shared rows, 90 screen-state combinations, including explicitly justified N/A states. A state key combines the screen ID and suffix, for example `M-02.04`. Do not renumber IDs after approval. HTML shows key compositions and static variants; it is not a working sync simulator.

## State inventory

### M-01 / D-01 — Sync status (11 states per screen)

Preserve the approved quiet status text and timings from `specs/021-mac-sync/design.md`: indicator after 1 s, minimum duration 0.5 s; online waiting suffix after 10 s; persistent transport failure after 60 s. The failure indicator measures persistent transport failure; it is separate from the ≤30-second active polling interval and SC-004's ≤60-second commit-to-visible deadline. Immediate auth/version errors are not hidden by this delay. Sync never blocks an allowed local command. Priority: unsupported version → session ended → issues → persistent failure → offline → waiting → synced. All reasons are available in details.

| suffix / state | trigger | visible result and English copy | FR refs |
|---|---|---|---|
| .01 default | queue empty, sync complete | Quiet row: “Synced just now”; details: “Last synced today at 14:31” | FR-004, FR-023 |
| .02 loading | first upload/pull or long-running sync | “Not synced yet” until the first full sync; then the previous row + reserved indicator “Syncing”; tasks remain available | FR-001, FR-004, FR-026 |
| .03 empty, first run | no account; tasks may be empty or already exist | “On this iPhone · Sign in to sync” / “On this Mac · Sign in to sync”; sign-in is optional | FR-001, FR-003 |
| .04 empty, filtered | list filtered to zero results | Status unchanged; existing list empty state. Sync details have no filter | FR-001, FR-023 |
| .05 offline / interrupted | no network or relaunch with pending changes | “Offline · 3 changes waiting”; “Your changes are saved on this device.”; automatic reconnect/resume | FR-001, FR-010 |
| .06 waiting | acknowledgment not yet received | “Synced 3 min ago · 3 changes waiting”; retry/replay does not increase the number of local commands | FR-005, FR-023 |
| .07 error | persistent timeout/server failure | “Couldn't sync · Retry”; details: reason, “Reference ID: demo-026-sync-01”, Copy reference ID | FR-005, FR-023 |
| .08 partial failure | independent transaction groups synced; one not accepted | “1 change couldn't sync”; “Other changes synced. This change is saved here.”; Open sync issues | FR-006, FR-007, FR-023 |
| .09 authentication | server rejected authorization | “Sign in again to sync”; account identity and “Your waiting changes stay with this account.”; local editing continues | FR-011 |
| .10 unsupported version | protocol/store version unknown | “Update needed to sync”; Open recovery. Stop incompatible exchange; store is read-only only if its format cannot be opened safely | FR-012 |
| .11 recovery complete | replay/pull/reset completed successfully | “Synced just now”; no success modal or repeated Task/receipt | FR-004, FR-005, FR-010 |

### M-02 / D-02 — Resolve conflict (9 states per screen)

| suffix / state | trigger | visible result and English copy | FR refs |
|---|---|---|---|
| .01 default | concurrent edit to one field not merged automatically | “Choose a title”; options “Your saved edit” and “Current account version”; radio choice without a default; “Apply choice” disabled until a selection | FR-007 |
| .02 loading | resolution being written atomically | “Saving your choice…”; resubmission does not create a second resolution; Back does not erase the conflict | FR-005, FR-006, FR-007 |
| .03 empty, first run | no conflicts have ever occurred | Existing issues view: “No sync issues” | FR-007 |
| .04 empty, filtered | N/A: screen introduces no filter | No new empty affordance | FR-007 |
| .05 error | chosen result not saved locally | “Your choice wasn't saved. Try again.”; original versions and selection preserved | FR-001, FR-007, FR-023 |
| .06 partial failure | other tasks synced; this one remains unresolved | “Other changes synced. Both versions are saved.”; unrelated tasks remain available | FR-006, FR-007 |
| .07 offline / interrupted | choice made offline or app closed | Choice is stored durably and shown as waiting; both originals remain until the resolution is acknowledged | FR-001, FR-007, FR-010 |
| .08 changed again | version changed after the card opened | “This task changed again. Review both versions.”; refresh the account side, preserve the user's draft; require explicit apply again | FR-007 |
| .09 deleted elsewhere | server deletion of an existing deletable entity conflicts with a local edit | “This item was deleted on another device. Your edit is saved in this issue.”; Copy saved edit, “Keep item deleted”; **no automatic reopen/create** | FR-007, FR-008 |

The title example's resolution creates a normal title command against the displayed current version; other fields are not replaced with an old snapshot. Under FR-007/contract v1, a conservative whole-entity conflict is allowed: the preview must show all differing fields rather than promise automatic field merging. Choosing the account version explicitly discards the intent and requires a decision on dependent actions. Manual text rewriting has not been added: comparison, Copy saved edit, and two explicit versions provide minimally sufficient recovery. “Keep item deleted” closes the issue only after the resolution is stored durably; the saved edit remains available in recovery/export under the retention contract and does not disappear when the sheet is simply closed. The deletion example concerns an existing deletable record, such as a Tag; no new Task deletion/restoration interface is introduced. The former suffix `.10` is reserved and unused: FR-009 preserves current ordering/moves; manual reorder API and UI are outside scope.

### M-03 / D-03 — Recover sync (13 states per screen)

| suffix / state | trigger | visible result and English copy | FR refs |
|---|---|---|---|
| .01 default | user opened recovery | “Recover sync”; pending count; explanation: “Rebuild the synced copy. Your waiting changes and saved conflicts will be kept.”; Rebuild synced copy | FR-010 |
| .02 loading | resume/reset in progress | “Rebuilding synced copy…”; count remains; do not mix a snapshot with a partial transaction; no numerical percentage promised | FR-006, FR-010 |
| .03 empty, first run | no account sync history | “Not synced yet”; first sync without a reset dialog | FR-003, FR-010 |
| .04 empty, filtered | N/A: no filter | — | FR-010 |
| .05 error | reset/download interrupted | “Couldn't rebuild the synced copy. Your waiting changes are saved.”; Try again and safe reference ID | FR-010, FR-023 |
| .06 partial failure | at least one migration field/record/relationship fails validation | “Couldn't import earlier data”; “Your earlier data file is unchanged. The new store hasn't been activated.”; original backup and import report preserved; partially imported store does not become active | FR-013 |
| .07 offline / interrupted | reset or migration interrupted | “Connect to finish recovery”; local pending changes preserved; resume from a durable checkpoint | FR-010, FR-013 |
| .08 unsupported protocol | new server protocol | “Update needed to sync. Your saved tasks and waiting changes stay on this device.”; Update app through the platform mechanism | FR-012 |
| .09 unsupported store | file created by a newer version | “Update needed to open tasks”; Try again, Export saved data when safely possible; no writes or background sync | FR-012, FR-022 |
| .10 migration uncertain | old outbox acknowledgment unknown | “Earlier changes need verification”; “Your earlier store and waiting changes are kept while sync checks what reached your account.”; retry without blind duplicate replay | FR-005, FR-013 |
| .11 account switch | sign-out requested before switching accounts with pending changes/issues | Existing “Sign out?” warning: current count, account, and precise explanation of local copy/unsynced work/issues removal; Cancel, Export saved data, confirmed “Sign out and remove”; sync/resolve can be chosen instead of signing out; network not required for confirmed sign-out | FR-003, FR-011, FR-022 |
| .12 export / deletion | user uses existing data controls | Export includes local pending/conflict material; Delete account remains the existing confirmed workflow; local copies/AI data follow the same privacy policy | FR-022 |
| .13 complete | reset/migration complete | Return to status without new onboarding; issues remain separate; “Earlier data imported” only after fully verified migration | FR-010, FR-013 |

Account switching uses the existing sign-out warning: the user can cancel sign-out and sync/resolve, export safely readable local data, or explicitly confirm removal of the local copy/unsynced work/issues with the exact current count. Network availability is not a condition for this confirmed sign-out; pending changes are never transferred to another owner. Export is not server acknowledgment and does not itself dismiss the warning. An account-less workspace is not implicitly assigned to another owner. Reset is not “Start fresh” and does not remove user intent; destructive sign-out is not offered as a sync remedy. Migration validates all fields, IDs, relationships, review/local-only data, and outbox in staging: activation follows full validation only; otherwise the original store remains intact and active. If the snapshot/state is incompatible, read-only recovery means saved data is available only in a safely decodable form, without inventing a promised export of an unknown binary format.

### M-04 / D-04 — AI choice, consent and proposal (12 states per screen)

| suffix / state | trigger | visible result and English copy | FR refs |
|---|---|---|---|
| .01 default | compatible local model available | “On-device suggestions”; “Task content stays on this device.”; request only on user action | FR-018, FR-020 |
| .02 loading | local/cloud request already authorized | “Preparing suggestions…”; Cancel/Continue without AI; canonical Task unchanged | FR-018, FR-019, FR-020 |
| .03 empty, first run | cloud consent absent | “Use cloud suggestions?”; specific configured provider name and exact field list; Allow cloud suggestions / Continue without AI | FR-019 |
| .04 empty, no proposal | valid response produced no suitable suggestion | “No suggestion this time”; Continue without AI; manual decision remains available | FR-020 |
| .05 error | local unavailable / cloud timeout/cost cap | “Suggestions aren't available. You can continue without AI.”; safe reference ID for cloud; no silent cloud fallback | FR-018, FR-019, FR-023 |
| .06 partial input | notes reduced under the existing limit | “Part of the notes was not considered”; disclose before apply; do not expand the cloud payload | FR-016, FR-019, FR-020 |
| .07 offline / interrupted | no network | Local works when a model is available; cloud: “Connect to request cloud suggestions”; completed local draft not erased | FR-018, FR-019, FR-020 |
| .08 local unsupported | device/language/model policy incompatible | “On-device suggestions aren't available for this task”; existing compatible local download choice if supported; cloud only through consent | FR-018, FR-019 |
| .09 consent denied/revoked | decline, revoke, provider/input-version change | “Cloud suggestions are off”; new requests prohibited; stale response not inserted after revocation/account switch | FR-011, FR-019, FR-022 |
| .10 proposal ready | validated suggestion received | “Review suggestion”; editable field; “Nothing changes until you apply”; Apply suggestion / Keep current wording | FR-020 |
| .11 proposal stale | Task revision changed | “This task changed. Review it before applying a suggestion.”; preserve draft, reread Task, repeat explicit confirmation | FR-007, FR-020 |
| .12 applied | explicit command committed | Card shows new text; durable Task command and existing review receipt; no automatic Task completion or AgentRun badge | FR-016, FR-020, FR-021 |

The mock's cloud example is labeled **illustrative provider: OpenAI**; this neither selects a provider nor enables a new AI flow. In implementation, the name must come from the current provider configuration, and consent is stored per owner/provider/input version. For the existing review navigator, the data list comes exactly from 020-FR-019: title, notes, optional stall reason, project name, up to 20 other open task titles in that project, requested suggestion kind. Copy: “Notes are sent as written, including any names in them.” Any other AI action must show its own approved payload rather than reuse this consent by default. This design does not expand the approved AI model policy or downloadable model availability.

## Affordance → requirement map

| screens | affordance | behavior | FR refs |
|---|---|---|---|
| M-01, D-01 | existing status row / Show details | Last acknowledged sync, waiting counts, reason; a locally saved result is not presented as server acknowledgment | FR-001, FR-004, FR-023 |
| M-01, D-01 | Sign in to sync / Sign in again | Existing auth, account-less use optional; owner-specific pending changes | FR-003, FR-011 |
| M-01, D-01 | Retry / Sync now | Existing single-flight retry; disabled for offline/auth/version reasons with an explanation; running sync does not disable the button | FR-005, FR-010 |
| M-01, D-01, M-03, D-03, M-04, D-04 | Copy reference ID | Opaque correlation ID only, without Task/AI/auth payload; copy failure reports an error | FR-023 |
| M-01, D-01 | Open sync issues | Independent failed group; successful transactions remain available | FR-006, FR-007 |
| M-02, D-02 | version radio choice + Apply choice | Explicit durable resolution against the displayed current version; discarding dependent actions requires an explicit decision | FR-007 |
| M-02, D-02 | Copy saved edit / Keep item deleted | Edit preserved; tombstone of an existing deletable entity not revived by replay; no new Task delete UI | FR-007, FR-008 |
| M-03, D-03 | Rebuild synced copy / Try again | Confirmed non-destructive reset preserving pending changes/conflicts | FR-010 |
| M-03, D-03 | Update app | Platform update route; incompatible sync/store writes stopped | FR-012 |
| M-03, D-03 | Open import report / Export saved data | Existing recovery/export route; backup and uncertainty visible | FR-013, FR-022 |
| M-03, D-03 | existing Cancel / Export saved data / Sign out and remove | Sign-out warning with current count; cancel stays in the current workspace; confirmed removal requires no network; pending changes not transferred to another owner | FR-003, FR-011, FR-022 |
| M-03, D-03, M-04, D-04 | existing Export / Delete account / Revoke consent | Full privacy lifecycle; deletion requires existing confirmation | FR-022, FR-019 |
| M-04, D-04 | on-device choice / supported model download | Approved existing availability policy | FR-018 |
| M-04, D-04 | Allow cloud suggestions / Continue without AI | Per-owner/provider consent; declining leaves manual review available | FR-019 |
| M-04, D-04 | Request suggestions / Cancel | Bounded proposal request, no Task command | FR-018, FR-019, FR-020 |
| M-04, D-04 | edit proposal / Apply suggestion / Keep current wording | Explicit Task command only; existing review semantics preserved | FR-016, FR-020 |

### Requirements with no additional affordance

| FR | reason / observable invariant |
|---|---|
| FR-002 | Shared domain rules and cross-language parity; client shows no engine selector |
| FR-009 | Existing ordering, moves, and completed placement preserved; no new manual reorder API/control |
| FR-014 | Older-client adapter preserves existing API/workflow; no separate compatibility button needed |
| FR-015 | Durable jobs and dedup scheduler; user sees existing result/status, not the internal job queue |
| FR-017 | Calendar dates, instants, stored review timezone, and local notification timezone preserve the current contract; no new date control |
| FR-021 | Task and AgentRun remain separate; no new run UI introduced; successful run does not complete Task |
| FR-024 | Web preserves current workflows and online affordances; no new offline mode added |
| FR-025 | App/widget multiprocess storage arbitration and atomic reads; no UI lock/engine controls needed |
| FR-026 | Local latency/scale and non-blocking sync; benchmark evidence, no new performance dashboard |

FR-001/004/005/006/008/009/010/011/012/013 also have invisible durability, convergence, dedup, transaction, tombstone, ordering, reset, isolation, and migration invariants. Displayed status alone is **not** evidence of these invariants: the plan and quickstart assign contract/storage/replay checks. FR-016 includes exact formulation clocks, auto-park floors, yield/idempotency, receipts/Undo, and feature-flag behavior from ADR-0027; no new review controls are introduced here. The tables above cover all FRs in both directions; affordances without a requirement: **none**. Back/Cancel/navigation close only the presentation and do not remove durable intent.

## Primary loop impact

Capture → durable atomic Task commands remains an immediate local action. Clarify/approve and routing preserve existing shared rules; sync transfers the result rather than repeating the action. Review/formulation/auto-park preserve exact ADR-0027 authority and date semantics. AI produces a proposal that enters the loop only after explicit apply. Evidence/results, Task completion, and AgentRun are not combined. Conflict/recovery does not require a new task app layout.

## Mobile viability

- **Target viewport**: 390×851 and narrow 320 px; responsive CSS, wrapping text, no fixed-height content clipping. Runtime overflow verification **not performed**; no “verified” claim is made.
- **Tap targets**: CSS sets 44 px min-height for controls and radio labels; native implementation requires 44 pt, including Copy/Back.
- **One-handed reach**: existing status row and sheet with full-width stacked actions on mobile; long comparison table is vertical.
- **Dynamic Type / zoom**: copy is not truncated; preview values wrap; buttons wrap without ellipsis. Large type needs device verification.
- **Destructive actions**: reset does not remove pending changes. “Keep item deleted” leaves the existing deletable record deleted and preserves the edit in recovery. The existing sign-out warning precisely names the pending changes/issues and local copy that will be removed, with a Cancel/export route; confirmed removal is available offline. Export/Delete account use existing confirmations without new hidden destructive gestures.

## Keyboard and focus

- Tab order: existing opener → details actions; conflict radio group → Apply choice → Copy saved edit → Back; recovery explanation → primary recovery → Cancel; AI disclosure → Allow → Continue without AI.
- When a sheet opens, native focus moves to the heading for VoiceOver, then to the first safe control; conflicts have no preselected version. Escape/Back closes the presentation; focus returns to the opener. When an issue disappears, focus moves to the Sync issues heading.
- An error receives one alert announcement; waiting/time refresh does not cause repeated announcements. Async status uses a polite live region only for actionable transitions.
- “Copy reference ID”, “Copy saved edit”, radio labels, and headings have textual accessible names. No icon-only controls or states conveyed by color alone.
- HTML is a static review sheet, not a simulated focus trap or live backend: links/details/radios work natively; product action buttons are illustrative. Keyboard dialog/retry/clipboard behavior requires separate runtime verification during implementation.

## Design authority and evidence

Sources: accepted ADR-0006/0020/0027; `.claude/skills/brain-buddy-design/SKILL.md`, `README.md`, `colors_and_type.css`; existing `specs/021-mac-sync/design.md`. System font for the native surface; slate/sky tokens, sky-700 action text/filled controls under the existing native deviation, amber warning, and double-ring focus. Self-contained CSS without font import, CDN, script, or asset dependency. Flat slate-50 background, 4 pt spacing, 8 px buttons, 12 px cards, 20 px panels. No new branding.

| check | actual evidence |
|---|---|
| design-skill contract unittest | **pass**, 2026-10-08: `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`, 6 tests. Checks the existing shared design reference, not rendering of these screens |
| ADR-0006 vocabulary static scan | **pass**, 2026-10-08: case-insensitive `rg` over design.md/design, 0 retired-vocabulary matches |
| HTML structure / local links / 44 px CSS static inspection | **pass**, repeated 2026-10-08 after alignment with spec/contract: Python HTMLParser, balanced tags, unique ids, 5 local anchors, 56 buttons with explicit type, no scripts/external resources, 44 px CSS, 8 screen IDs, FR-001–FR-026 coverage, and 45 shared rows / 90 screen-state combinations. Checked absence of a new manual reorder/delete Task flow and updated warning/migration copy. Runtime geometry/contrast/focus not checked |
| Screenshots, browser/device rendering, runtime accessibility | **not performed**; static artifacts only |
| Product/CI/deployment acceptance | **not performed**, outside spec-only scope |
| Human approval | **pending**, not implementation authorization |

## Open decisions for the human

1. **Concurrent edit resolution**: confirm the minimal explicit choice between two saved versions (and copy), without automatically choosing the latest by timestamp. For a whole-entity conflict, the preview shows all differing fields and dependent actions. For delete/edit, the existing deletable record remains deleted; the edit is saved separately; no new Task delete/reorder UI.
2. **Account switch warning**: preserve the existing sign-out warning with an exact count, Cancel/export/explicit confirmed removal, and no transfer of pending changes to another owner. This is not a network gate. Reset always preserves pending changes/conflicts.
3. **Recovery visibility**: confirm quiet status with existing 021 timings and a separate recovery sheet only for persistent/semantic errors; migration uncertainty is shown explicitly. Migration is fully validated before activation or fails with the original intact; ordinary verified migration proceeds quietly.

These decisions are draft recommendations for the shared specification. Approval of Rust + custom sync does not constitute human sign-off for these screens.

On 2026-10-09 the unchanged static mock was offered for review again. Browser rendering was attempted but the default sandbox blocked Chromium startup; no new rendered-layout or native-accessibility result is asserted by that attempt. The authoritative pending decisions are consolidated in [approval.md](approval.md).
