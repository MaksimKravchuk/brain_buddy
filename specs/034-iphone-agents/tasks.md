# Tasks: iPhone agents

**Input**: [spec.md](spec.md), [design.md](design.md), [plan.md](plan.md)

## Format: `[ID] [P?] Description`

## Phase 1 — Shared kit module (PR-01)

- [ ] T001 Write the 034 spec package (intake, spec, checklist, design, plan, tasks)
- [ ] T002 Move the 030 agent models into `ios/BrainBuddyKit/Sources/BrainBuddyAgents/` with public API, `AgentLogSink` and an explicit settings remote
- [ ] T003 Move `AgentRunBlock`, `AgentTimelineRow` and `AgentRunSectionModel` from the Mac app target into the module
- [ ] T004 Add `AgentsSession`, `AgentStepRef` and `WorkspaceStepCommands`, with `BrainBuddyAgentsTests` (034-FR-001 – 034-FR-004, 034-FR-006 – 034-FR-008)
- [ ] T005 Re-export the module from `BrainBuddyMacCore`, keep the Mac's log sink and settings remote

## Phase 2 — iPhone host and Waiting for (PR-02)

- [ ] T006 Link `BrainBuddyAgents` in `ios/project.yml`; create one `AgentsSession` per workspace and drive refresh, foreground and network state
- [ ] T007 Agents group in Waiting for with the run row and header (I-01)

## Phase 3 — Run sheet (PR-03)

- [ ] T008 Run sheet for Needs you, Result and every other state (I-02 – I-04), opened from a run row

## Phase 4 — Hand off (PR-04)

- [ ] T009 Hand to an agent sheet (I-05), Hand off… on the step's card and Hand off again in the run sheet

## Phase 5 — Account › Agents (PR-05)

- [ ] T010 Agents section (I-06) in Settings, agent details (I-07), Add new agent (I-08), Replace credential and Delete (I-09)

## Dependencies & Execution Order

PR-01 first. PR-02 depends on PR-01. PR-03 and PR-05 depend on PR-02 and run in parallel; PR-04
depends on PR-03 (Hand off again lives in the run sheet).

## PR-срезы

```json
{
  "schema_version": "brainbuddy-pr-slices/v2",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "The iPhone and the Mac share one agent model module in the kit, with the iPhone's session wiring tested on Linux and the Mac unchanged in behaviour",
      "tasks": ["T001", "T002", "T003", "T004", "T005"],
      "requirements": ["034-FR-001", "034-FR-002", "034-FR-003", "034-FR-004", "034-FR-006", "034-FR-007", "034-FR-008", "034-FR-014", "034-SC-001", "034-SC-003"],
      "paths": [
        "specs/034-iphone-agents",
        "ios/BrainBuddyKit/Package.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAgents",
        "ios/BrainBuddyKit/Tests/BrainBuddyAgentsTests",
        "macos/Package.swift",
        "macos/Sources/BrainBuddyMacCore",
        "macos/Sources/BrainBuddyMac/Agents/AgentRunSection.swift",
        "macos/Sources/BrainBuddyMac/Settings/AgentsSettingsTab.swift"
      ],
      "depends_on": [],
      "tests": [
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddyAgentsTests",
        "cd macos && swift test --filter Agent"
      ],
      "acceptance": [
        "BrainBuddyAgentsTests pass on Linux and macOS",
        "The Mac's 030 agent tests pass against the moved models"
      ],
      "budget": {"product_loc": 1900, "files": 18},
      "oversize_reason": "Moves 030's existing, already-reviewed models (about 1,700 lines) between modules without behaviour change; the new code is about 200 lines.",
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-02",
      "outcome": "The iPhone app holds one agents session and Waiting for lists the runs of open steps above People",
      "tasks": ["T006", "T007"],
      "requirements": ["034-FR-002", "034-FR-003", "034-FR-004", "034-FR-013"],
      "paths": [
        "ios/project.yml",
        "ios/BrainBuddy/App/BrainBuddyApp.swift",
        "ios/BrainBuddy/Screens/Agents/AgentsHost.swift",
        "ios/BrainBuddy/Screens/Agents/AgentRunRow.swift",
        "ios/BrainBuddy/Screens/Lists/TaskListScreen.swift"
      ],
      "depends_on": ["PR-01"],
      "tests": ["CI ios-app lane (xcodebuild)"],
      "acceptance": ["Waiting for shows the Agents group with the canvas row and header when runs are listed, and nothing when signed out"],
      "budget": {"product_loc": 220, "files": 4},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-03",
      "outcome": "Tapping a run opens its sheet with the question and Reply, the result and Mark step done, or its state",
      "tasks": ["T008"],
      "requirements": ["034-FR-005", "034-FR-006", "034-FR-007", "034-FR-008", "034-FR-013"],
      "paths": [
        "ios/BrainBuddy/Screens/Agents/AgentRunSheet.swift",
        "ios/BrainBuddy/Screens/Lists/TaskListScreen.swift"
      ],
      "depends_on": ["PR-02"],
      "tests": ["CI ios-app lane (xcodebuild)"],
      "acceptance": ["Each 030 label group renders its canvas block and only the controls the run allows"],
      "budget": {"product_loc": 380, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-04",
      "outcome": "A step's card hands it to a ready agent after showing what it will get",
      "tasks": ["T009"],
      "requirements": ["034-FR-009", "034-FR-013"],
      "paths": [
        "ios/BrainBuddy/Screens/Agents/HandoffSheet.swift",
        "ios/BrainBuddy/Screens/Detail/TaskDetailScreen.swift",
        "ios/BrainBuddy/Screens/Agents/AgentRunSheet.swift"
      ],
      "depends_on": ["PR-03"],
      "tests": ["CI ios-app lane (xcodebuild)"],
      "acceptance": ["Hand off… shows only with the flag on for a synced open step; Send to dispatches and the run appears in Waiting for"],
      "budget": {"product_loc": 300, "files": 3},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-05",
      "outcome": "Account lists the agents, shows their details and adds, tests, re-credentials and deletes them",
      "tasks": ["T010"],
      "requirements": ["034-FR-010", "034-FR-011", "034-FR-012", "034-FR-013"],
      "paths": [
        "ios/BrainBuddy/Screens/Agents/AgentsAccountSection.swift",
        "ios/BrainBuddy/Screens/Agents/AgentDetailsScreen.swift",
        "ios/BrainBuddy/Screens/Agents/AddAgentScreen.swift",
        "ios/BrainBuddy/Screens/Agents/AgentCredentialSheets.swift",
        "ios/BrainBuddy/Screens/Settings/SettingsScreen.swift"
      ],
      "depends_on": ["PR-02"],
      "tests": ["CI ios-app lane (xcodebuild)"],
      "acceptance": ["The Agents section, details and Add new agent match M25, M29 and M30 and call the shared editor"],
      "budget": {"product_loc": 400, "files": 5},
      "implementer": "feature-implementer"
    }
  ]
}
```
