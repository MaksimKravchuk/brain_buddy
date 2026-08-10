# Design: Lean external-agent relay

**Feature**: `specs/006-external-agent-relay/`  
**Spec**: `spec.md` (clarifications settled and exact bytes ratified 2026-08-09)  
**Screens**: Responsive product surfaces listed below; no versioned HTML prototype is stored in this repository  
**Human sign-off**: Product/state contract ratified by Max on 2026-08-09; this portable design record was added retrospectively after the design-stage requirement landed on `main`

## Applicability

This feature has user-visible web and iOS surfaces. The design preserves existing BrainBuddy settings, Task detail, Task list, and History patterns. BrainBuddy presents server-known relay facts and agent-reported text without implying that external work was verified or that the canonical Task was completed.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | desktop | Connected agents | Add, test, inspect, rotate/recover, and disconnect owner-scoped connections | FR-001–FR-004, FR-016–FR-018 |
| D-02 | desktop | Task agent panel | Review one hand-off and monitor each external run from the canonical Task | FR-005–FR-015, FR-017–FR-018 |
| M-01 | mobile | Connected agents | Native-width connection management with the same safety gates | FR-001–FR-004, FR-016–FR-018 |
| M-02 | mobile | Task agent panel and compact Task rows | Review, monitor, answer, cancel when supported, and reopen a saved timeline | FR-005–FR-015, FR-017–FR-018 |

## State inventory

### D-01 — Connected agents

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | one or more saved connections | Name, endpoint, tested condition, capabilities, last contact, safe actions | Ready, stale, invalid credentials, unreachable, or disconnected | FR-001–FR-004 |
| loading | first server fetch | Existing settings frame with bounded loading treatment | Loading connected agents | FR-017 |
| empty (first run) | no saved connection | One explanation and add-agent action | Connect an agent you operate | FR-001 |
| empty (filtered to nothing) | not applicable | No filtering is introduced in v1 | Not applicable | Scope boundary |
| error | fetch/test/mutation fails | Existing data remains where safe; category, retry, and correlation ID are shown | Actionable server-owned error copy | FR-002, FR-017 |
| partial failure | cached list exists but refresh fails | Cached rows remain visible and explicitly stale | Showing potentially stale saved data | FR-018 |
| offline / interrupted | browser is offline | Saved status may remain visible; secret-bearing mutations are disabled and nothing is queued | Offline — reconnect to manage agents | FR-018 |

### D-02 — Task agent panel

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| default | Task has no run | Hand-off action when a tested connection is eligible | Hand to agent | FR-005 |
| review | user selects an eligible connection | Exact immutable Task fields, selected supporting items, destination, reporting contract, external-copy warning | Review what will leave BrainBuddy | FR-005–FR-006 |
| sent / running | dispatch reserved or authenticated report received | Agent identity, state, last contact, inert progress and timeline | Sent; Running | FR-006, FR-008–FR-011 |
| blocked | authenticated question arrives | Question plus reply only when capability and live revision permit it | Agent needs your answer | FR-007–FR-011 |
| terminal | completed, failed, or cancelled report accepted | Terminal agent report without changing Task completion | Agent reported complete; Failed; Cancelled | FR-008, FR-011–FR-012 |
| stopped reporting | reporting window elapses | Overlay plus last authenticated contact; prior non-terminal state remains | Stopped reporting | FR-008, FR-011, FR-013 |
| expired | content retention deadline passes | Coarse metadata and expiry marker, no relayed text or reply control | Content expired under retention policy | FR-010, FR-015 |
| offline / interrupted | network unavailable or refresh fails | Cached run remains explicitly potentially stale; reply/cancel are disabled | Cached status may be stale | FR-018 |

### M-01 — Connected agents

The states and copy semantics match D-01. Forms use sheets, preserve one intent key across ambiguous retries, never redisplay a saved credential, and clear owner-private cache state on session/server change.

### M-02 — Task agent panel and compact Task rows

The detail states match D-02. Compact rows show only the latest run’s agent, honest primary state, needs-user indicator, and last contact. Selecting a row opens the saved Task timeline rather than creating or reopening work implicitly.

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01 / M-01 | Add agent | Creates one owner-scoped connection after recent password verification | FR-001, FR-003 |
| D-01 / M-01 | Test connection | Performs bounded authenticated capability discovery without stale-snapshot overwrite | FR-002, FR-004 |
| D-01 / M-01 | Replace credential / signing secret | Uses one stable intent and one-time secret display after verification | FR-003, FR-006 |
| D-01 / M-01 | Disconnect | Explains that external work is not cancelled, then destroys active secret material | FR-016 |
| D-02 / M-02 | Hand to agent | Opens immutable disclosure/consent review | FR-005 |
| D-02 / M-02 | Confirm hand-off | Dispatches the reviewed manifest with stable run/idempotency identity | FR-005–FR-006 |
| D-02 / M-02 | Reply | Sends the answer only for the displayed blocked run revision and reply-capable connector | FR-007–FR-009 |
| D-02 / M-02 | Request cancellation | Records one stable request; terminal state waits for authenticated connector report | FR-007–FR-011 |
| D-02 / M-02 | Open timeline | Loads all owner-scoped runs for the existing Task | FR-010, FR-018 |

### Requirements with no affordance

- FR-004, FR-006, FR-009, FR-013, FR-015, and FR-017 are primarily server enforcement/projection contracts; their effects and errors are visible but users do not control the security rule.
- FR-012 is an intentional absence: no control allows an external report to complete the canonical Task.

### Affordances with no requirement

- None. Existing navigation/back/close controls are host-product behavior rather than feature scope.

## Primary loop impact

The feature starts only after a canonical Task exists. A hand-off creates a separate external-run evidence lane linked to that Task. Capture, atomic Task creation, clarification/approval, routing, Weekly Review, and Task completion remain unchanged. Agent reports can inform the user but never become authoritative Task completion.

## Mobile viability

- **Viewport**: Designed for the repository’s iPhone-width Expo surface; no horizontal scrolling is required.
- **Tap targets**: Existing mobile controls retain the project’s 44pt minimum.
- **One-handed reach**: Primary sheet actions remain in the bottom action area; destructive disconnect is not promoted as a primary action.
- **Destructive actions**: Disconnect confirmation says credentials are destroyed, new commands stop, and already-running external work is not cancelled.

## Keyboard and focus

- **Tab order**: Web follows heading → connection/run content → primary action → secondary/destructive actions.
- **Focus on open**: Dialog/sheet heading or first required field. **Focus restored on close to**: the control that opened it.
- **Escape**: Closes a non-pending dialog without submitting or minting a new intent.
- **Accessible names**: Icon-only close controls are named; state/actions use text labels.
- **State communicated by color alone**: None; every state has text.

## Design authority

- Tokens, colors, type, and components reuse the existing BrainBuddy design system and host-product patterns.
- Vocabulary check (ADR-0006, `Tag` terminology): pass; this feature introduces no alternate Task taxonomy.
- Design-skill validator: not applicable to this retrospective record because it changes no design skill artifact.

## Open decisions for the human

1. None for the minimum implementation. ASK landing, production rollout, EAS account linkage, TestFlight, and App Store submission remain explicit release-authority gates rather than unresolved design choices.
