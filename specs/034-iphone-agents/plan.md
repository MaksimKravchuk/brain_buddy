# Implementation Plan: iPhone agents

**Branch**: `034-iphone-agents` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md) |
**Design**: [design.md](design.md)

## Summary

Move the Mac's Foundation-only agent models (030) into a new shared kit module,
`BrainBuddyAgents`, so the iPhone and the Mac run one implementation (034-FR-001); add
`AgentsSession`, the window-level wiring the Mac keeps in `BrainBuddyModel`, for the iPhone; then
build the iPhone screens of [design.md](design.md) (I-01 – I-09) over it.

## Technical Context

Swift 6 language mode, iOS 26 / macOS 26, SwiftUI, Swift Testing. No new dependency. The kit
builds and tests on Linux (`sh ios/scripts/swift-linux.sh test --filter BrainBuddyAgentsTests`);
the app targets compile only in CI (`ios-app` and the Mac lane).

## Constitution Check

- Principle II (tested delivery): every rule is in the kit and tested there on Linux and macOS; the
  Mac's 030 tests keep running against the moved models; SwiftUI screens hold no rule.
- No backend change (034-FR-014); no new endpoint.
- Privacy: memory-only content and secrets, owner-scoped cache, logs without content (030-FR-026,
  030-FR-039) — unchanged code, now shared.

## Architecture

### Shared kit (`ios/BrainBuddyKit/Sources/BrainBuddyAgents/`)

Moved unchanged in behaviour from `macos/Sources/BrainBuddyMacCore/` with `package` → `public`:
`AgentsCopy`, `AgentAvailability`, `AgentMemoryCache`, `AgentRunGroup` (+ `AgentRunItem`),
`AgentRunsStore`, `AgentRunActions`, `HandoffFlow`, `AgentSettingsModel`, `AgentConnectionEditor`;
from the Mac app target: `AgentRunBlock`, `AgentTimelineRow`, `AgentRunSectionModel`.
Two seams replace Mac-only types: `AgentLogSink` (default `SystemAgentLog`, `os.Logger` category
`agents`) instead of `MacLogSink`, and `AgentSettingsModel` takes its remote explicitly (no
`WorkspaceHost` default). New: `AgentsSession` and `AgentStepRef` (the open steps, the listed
runs, the account lifecycle; port of `BrainBuddyModel`'s agent wiring) and
`WorkspaceStepCommands` (port of the Mac's `InspectorStepCommands`).

### Mac (`macos/`)

`BrainBuddyMacCore/AgentsKit.swift` re-exports `BrainBuddyAgents`, makes `SystemMacLog` and
`CapturingMacLog` agent log sinks (lines keep category `sync`), and keeps
`AgentSettingsModel.liveRemote` and the two-argument initializer. Production call sites pass
`SystemMacLog()` so the Mac's log subsystem is unchanged. No behaviour change.

### iPhone (`ios/BrainBuddy/`)

- `App/`: one `AgentsSession` per workspace, injected with `.environment`, refreshed at launch,
  sign-in/out and foreground; foreground and network state drive polling; `run()` runs while the
  scene is active.
- `Screens/Agents/`: `AgentRunRow` (I-01 row), `AgentRunSheet` (I-02 – I-04), `HandoffSheet`
  (I-05), `AgentsAccountSection` (I-06), `AgentDetailsScreen` (I-07), `AddAgentScreen` (I-08),
  `AgentCredentialSheets` (I-09).
- Edits: Waiting for (`Screens/Lists/TaskListScreen.swift`) gains the Agents group; the step's
  card (`Screens/Detail/TaskDetailScreen.swift`) gains Hand off…; Settings
  (`Screens/Settings/SettingsScreen.swift`) hosts the Agents section until 033's Account screen
  does.

## Verification

- `sh ios/scripts/swift-linux.sh test --filter BrainBuddyAgentsTests` (Linux), the kit lane on
  macOS, the Mac lane (030 tests against the moved models), the `ios-app` lane (compile).
- `python3 scripts/check_spec_kit_specs.py`, `python3 scripts/check_requirement_coverage.py
  specs/034-iphone-agents`.

## Risks

- The Mac and iPhone app targets compile only in CI: keep each slice small and mirror the Mac's
  compiled code.
- 033 builds the Account screen in parallel: the Agents section is a self-contained view so it
  moves with one line.
