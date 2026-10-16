# Tasks: iPhone account screens and invite step

**Input**: [spec.md](spec.md), [plan.md](plan.md), [design.md](design.md),
[intake.md](intake.md).

**Delivery gates**: isolated worktree and branch per slice; Constitution Principle II;
tests name the feature-qualified id (`033-FR-###` / `033-SC-###`, `033_FR_###` in Swift
function names). Each slice runs
`python3 scripts/check_slice_budget.py specs/033-ios-account/tasks.md PR-NN` before review.

**Tests (Principle II)**: test-first applies to the kit model and client (T001–T003):
`AccountSecurityModelTests`, `AccountSecurityAPITests`. Views are thin; the `ios-app` CI
lane compiles them and 033-SC-001 is checked against the boards.

## Format: `[ID] [P?] [Story] Description`

## Phase 1 — Foundation (PR-01)

- [ ] T001 [US1] [US2] [US3] Add account-change calls (`AccountAction`, `RecentProof`,
  profile, confirm password, email code, provider completion, unlink, password, export,
  delete) in `ios/BrainBuddyKit/Sources/BrainBuddyAPI/AccountSecurityAPI.swift` and
  `Endpoint.headers`, with `AccountSecurityAPITests`. 033-FR-002, 033-FR-004..010. PR-01.
- [ ] T002 [US1] [US2] [US3] Add `AccountSecurityModel` (rows, confirmation options,
  password rule, failures, every action, proof checks) in
  `ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/AccountSecurityModel.swift`, with
  `AccountSecurityModelTests`. 033-FR-001..010, 033-FR-012, 033-SC-002. PR-01.
- [ ] T003 [P] Add the `layout.code-box` token and regenerate. 033-SC-001. PR-01.
- [ ] T004 [US2] App: `CodeBoxesField`, `AccountConfirmSheet`, `AccountModels`, routes
  `.account` / `.signInMethods`. 033-FR-004, 033-FR-005. PR-01.

## Phase 2 — Account screen (PR-02)

- [ ] T005 [US1] [US3] `AccountScreen` (board 25 without Agents), `AccountNameSheet`,
  `DeleteAccountSheet` (board 28), export share sheet, `AccountSignOut`; Settings opens
  Account and loses the web hand-off rows. 033-FR-001, 033-FR-002, 033-FR-009,
  033-FR-010, 033-FR-012, 033-FR-013. PR-02.

## Phase 3 — Sign in screen (PR-03)

- [ ] T006 [US2] `SignInMethodsScreen` (board 26), `ChangeEmailSheet` (board 27, change
  and verify), `PasswordSheet`. 033-FR-003, 033-FR-005..008, 033-FR-012, 033-FR-013. PR-03.

## Phase 4 — Invite step (PR-04)

- [ ] T007 [US4] Restyle the invite step in `SignInSheet.swift` to board 06 with one code
  field. 033-FR-011. PR-04.

## PR-срезы

```json
{
  "schema_version": "brainbuddy-pr-slices/v2",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "The kit can make every account change with a fresh proof, and the app has the shared confirm sheet, code field and routes",
      "tasks": ["T001", "T002", "T003", "T004"],
      "requirements": [
        "033-FR-001", "033-FR-002", "033-FR-003", "033-FR-004", "033-FR-005",
        "033-FR-006", "033-FR-007", "033-FR-008", "033-FR-009", "033-FR-010",
        "033-FR-012", "033-SC-002"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/AccountSecurityAPI.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPIClient.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/AccountSecurityModel.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AccountSecurityAPITests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/AccountSecurityModelTests.swift",
        "ios/BrainBuddyKit/DesignTokens/carry-on.tokens.json",
        "ios/BrainBuddyKit/Sources/BrainBuddyDesign/Generated/CarryOnTokens.swift",
        "ios/BrainBuddy/Components/CodeBoxesField.swift",
        "ios/BrainBuddy/Screens/Account/AccountConfirmSheet.swift",
        "ios/BrainBuddy/Screens/Account/AccountModels.swift",
        "ios/BrainBuddy/App/AppRouter.swift",
        "ios/BrainBuddy/App/AppRouteView.swift"
      ],
      "depends_on": [],
      "tests": [
        "sh ios/scripts/swift-linux.sh test --filter AccountSecurity"
      ],
      "acceptance": [
        "No change request is built without an unexpired proof for that action",
        "A response for another account is refused"
      ],
      "budget": {"product_loc": 1000, "files": 17},
      "oversize_reason": "The account model is one contract shared by both screens; splitting it would ship half the actions with no caller",
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-02",
      "outcome": "Settings opens the Account screen with name, export, delete and sign out",
      "tasks": ["T005"],
      "requirements": ["033-FR-001", "033-FR-002", "033-FR-009", "033-FR-010", "033-FR-013"],
      "paths": [
        "ios/BrainBuddy/Screens/Account/AccountScreen.swift",
        "ios/BrainBuddy/Screens/Account/AccountNameSheet.swift",
        "ios/BrainBuddy/Screens/Account/AccountSignOut.swift",
        "ios/BrainBuddy/Screens/Account/DeleteAccountSheet.swift",
        "ios/BrainBuddy/Screens/Settings/SettingsScreen.swift"
      ],
      "depends_on": ["PR-01"],
      "tests": ["CI ios-app lane builds the app"],
      "acceptance": ["Board 25 (without Agents) and board 28 match in light and dark"],
      "budget": {"product_loc": 600, "files": 5},
      "oversize_reason": "About 130 lines are the sign-out section moved unchanged out of Settings",
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-03",
      "outcome": "The Sign in screen changes and verifies email, connects and removes Apple and Google, and sets the password",
      "tasks": ["T006"],
      "requirements": ["033-FR-003", "033-FR-005", "033-FR-006", "033-FR-007", "033-FR-008"],
      "paths": [
        "ios/BrainBuddy/Screens/Account/SignInMethodsScreen.swift",
        "ios/BrainBuddy/Screens/Account/ChangeEmailSheet.swift",
        "ios/BrainBuddy/Screens/Account/PasswordSheet.swift"
      ],
      "depends_on": ["PR-01"],
      "tests": ["CI ios-app lane builds the app"],
      "acceptance": ["Boards 26 and 27 match in light and dark"],
      "budget": {"product_loc": 620, "files": 3},
      "oversize_reason": "One screen with three sheets that share one confirmation chain; splitting leaves rows with no action",
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-04",
      "outcome": "The invite step looks like board 06 with one code field",
      "tasks": ["T007"],
      "requirements": ["033-FR-011"],
      "paths": ["ios/BrainBuddy/Screens/Settings/SignInSheet.swift"],
      "depends_on": [],
      "tests": ["CI ios-app lane builds the app"],
      "acceptance": ["Board 06 matches in light and dark; wrong, used, throttled and expired states keep their words"],
      "budget": {"product_loc": 100, "files": 1},
      "implementer": "feature-implementer"
    }
  ]
}
```
