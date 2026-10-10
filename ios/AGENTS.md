# Brain Buddy iOS — agent guide

SwiftUI for iOS 26, Swift 6 language mode with complete strict concurrency, an
XcodeGen project and one local Swift package. The design and the rules the app
mirrors are in `../docs/native-ios-app.md`; the runbook (signing, TestFlight,
offline QA) is `README.md`.

## Commands

```bash
sh ios/scripts/build-rust-bridge.sh        # once, and after any change under rust/: see "Rust bridge"
sh ios/scripts/swift-linux.sh test         # package on Linux via Docker (builds the bridge first); no Xcode needed
sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests
(cd ios/BrainBuddyKit && swift test)       # package on macOS
(cd ios && xcodegen generate)              # after adding, moving or deleting any file
xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

The SwiftUI targets compile only on macOS. On Linux, verify with the package
tests and leave the app build to CI (the `ios-app` lane of
`.github/workflows/ci.yml`).

## Rust bridge

`BrainBuddyCore` links the shared Rust core (spec 026, ADR-0031) through the UniFFI
crate `rust/bindings/swift` (`bb-swift`). Nothing generated is committed: the build
script writes the static library (an XCFramework on Apple, `Artifacts/linux/` on Linux),
the generated C header and the generated Swift (`Sources/BrainBuddyRust{FFI,Bindings}`)
into ignored paths, from `rust/Cargo.lock` and the toolchain pinned in
`rust/rust-toolchain.toml`. `Package.swift` stops with that instruction when they are
missing. CI runs the script before every Swift lane; `swift-linux.sh` does it in the
official Rust image (`BB_SKIP_RUST_BUILD=1` reuses the last build).

- Only `Sources/BrainBuddyCore/BrainBuddyRustBridge.swift` imports the generated module;
  its `RustBridgeRuntime` takes and returns owned values, throws `RustBridgeError`
  (`code`, `retryable`, `field`, never payload text), runs off the caller's actor and
  honours task cancellation. Change the Rust interface and the facade together.
- `RustDomainFacade` (Core) is the bounded mapping of `GTDCommand`, `GTDState` and the
  catalog queries onto the core's `decide` / `query` (the Python counterpart is
  `rust_task_facade.py`). `RuleEpoch` selects the rules for a workspace: `.legacy` is the
  Swift reducer and read model for a file written before the cutover, `.rust(facade)` is the
  shared core and never reaches the Swift handlers. `GTDReducer.apply(…rules:)`,
  `GTDQueries.list/counts/projects/tags/projectDisplay(…rules:)` and `CapturePlanner.preview/capture(…rules:)`
  dispatch on it; no mutation runs both. Comparing the two images belongs in tests
  (`RustDomainParityTests`). Change the Rust payloads and `RustDomain{Commands,Changes,Wire}.swift`
  together; `rust/bindings/swift/tests/apple_wire.rs` runs the same wire shapes from the Rust side.
- `BrainBuddyPersistence/RustStoreImporter` is the one caller of
  `RustBridgeRuntime.importLegacyStore`: it lets `StoreDocumentCoding` judge the legacy
  `store.json` first (damaged, or saved by a newer app: nothing is attempted), passes the core its
  own counts of the file to be cross-checked, and maps the core's `IMPORT_*`/`STORE_*` codes to
  `RustStoreImportError`. The core (`bb-client` `import.rs`) backs the file up with a schema
  manifest, stages and validates under the migration lock, and switches the store in one
  transaction or changes nothing; the legacy file is never modified. Its outbox entries and issues
  are carried whole but not converted (`legacy_outbox`), so nothing may run on the Rust store
  before that import has consumed them. Change the import's counts or errors in Rust, the facade
  and the importer together.
- The Apple XCFramework has one library per platform variant: iOS device (arm64), iOS
  simulator (arm64 + x86_64) and macOS (arm64 + x86_64), the two-architecture ones joined
  with `lipo`, because Xcode links the simulator and Mac builds for both architectures.
  `BB_APPLE_TARGETS` narrows the Rust targets (a Mac-only lane passes the two darwin ones).
- The Rust crate stays under the workspace's `unsafe_code = "forbid"`; the UniFFI
  macros need no exception. Do not add `unsafe` to hand-written Rust.

## Where code goes

| Path | Holds | Must not |
|---|---|---|
| `BrainBuddyKit/Sources/BrainBuddyCore` | Models, `GTDCommand`, `GTDReducer`, replay, queries, Smart Add | Import SwiftUI, UIKit, WidgetKit or anything Apple-only |
| `BrainBuddyKit/Sources/BrainBuddy{Persistence,API,Sync}` | Store file, REST client, sync engine | Hold GTD rules |
| `BrainBuddyKit/Sources/BrainBuddyWorkspace` | The `@Observable` model the UI binds to | Hold GTD rules |
| `BrainBuddyKit/Sources/BrainBuddyDiagnostics` | Beta performance diagnostics: the bounded log, CPU arithmetic, summary, export (`README.md`, "Performance diagnostics") | Depend on the rest of the kit, or record user content |
| `BrainBuddy/` | App: `App/`, `DesignSystem/`, `Components/`, `Screens/`, `Intents/`, `Resources/` | Hold GTD rules |
| `BrainBuddyWidgets/` | Widgets and Control Center controls | Sync, or hold GTD rules |
| `Shared/` | Code and resources for **both** the app and the widget extension | Use app-only API (`UIApplication.shared`, …) |

## Non-negotiable rules

- **Rules live in `BrainBuddyCore`.** `GTDReducer` is the only place a GTD
  rule is decided (which transition is legal, Waiting's `waiting_for`, name
  uniqueness, limits). The UI, widgets and intents dispatch a `GTDCommand`
  through the workspace and render queries; they never re-check or
  re-implement a rule, and never offer an action the reducer would reject —
  ask the reducer or a query instead.
- **Every package target builds and tests on Linux.** Put Apple-only API
  (Security, file protection, `NWPathMonitor`, `BGTaskScheduler`) behind
  `#if canImport(...)` or in the app target. Run
  `sh ios/scripts/swift-linux.sh test` before calling package work done.
- **No third-party dependencies**, in the package or the app. `Package.swift`
  has no Swift dependency; keep it that way. The one exception (ADR-0031, spec 026): the shared
  Rust domain/runtime and its audited, pinned generated Swift bindings (UniFFI 0.32.2,
  MPL-2.0, built from `rust/Cargo.lock`). Their build
  inputs, licenses, lockfile, reproducible packaging, supported targets and the
  Foundation-only Linux test boundary must be reviewed before they land. This does
  not permit arbitrary Swift packages, bundled model weights or any other native
  dependency.
- **`project.yml` is the source of truth.** The `.xcodeproj`, both
  Info.plists and both `.entitlements` files are generated and git-ignored.
  A new Info.plist key, entitlement, capability, build setting or target goes
  into `project.yml`; a new source file needs only `xcodegen generate`.
- **Never hard-code identifiers.** Read the App Group from the
  `BBAppGroupIdentifier` Info.plist key; register the background refresh task
  as `Bundle.main.bundleIdentifier + ".refresh"`. The URL scheme is
  `brainbuddy`. Everything derives from `BB_BUNDLE_ID_PREFIX` so the owner can
  sign under their own team (`README.md`, "Signing and identifiers").
- **Declare required-reason APIs.** Using UserDefaults, file timestamps,
  system boot time, disk space or active keyboards means a matching entry in
  `Shared/PrivacyInfo.xcprivacy`; App Store Connect rejects the TestFlight
  upload otherwise.
- **Concurrency is checked, not suppressed.** No `@unchecked Sendable`,
  `nonisolated(unsafe)` or `@preconcurrency` to silence a diagnostic without a
  comment saying why it is safe.

## Tests

- Swift Testing (`import Testing`, `@Test`, `#expect`, `#require`), not XCTest.
- One test target per package module (`BrainBuddyCoreTests`, …), files named
  after the type under test (`GTDReducerTests.swift`).
- Deterministic: pass dates, ids and clocks in (commands already carry their
  ids and issue time); no sleeps, no network, no real App Group container.
- Rules and sync are tested in the package, where they run on Linux and in
  CI; a SwiftUI view is not the place to test a rule.

## Design and copy

- Tokens come from `.claude/skills/brain-buddy-design/` (the
  `/brain-buddy-design` skill): sky `#0EA5E9` accent (`AccentColor`), slate
  neutrals, the brand curve `cubic-bezier(0.22, 1, 0.36, 1)` for our own
  animations, 44 pt hit targets, Reduce Motion respected.
- Glass on chrome only (tab bar, toolbars, sheets, the capture accessory,
  floating clusters); content stays flat.
- Pending product sign-off (`docs/native-ios-app.md`): SF Symbols instead of
  Lucide (use the documented mapping), dark mode derived from the slate/sky
  scale, SF Pro instead of Inter, system glass motion, and sky-700
  (`BBColor.brandText` / `brandFill`) for text and filled controls because
  white on sky-500 is 2.8:1 (sky-500 stays for large accents). Do not add more
  deviations without flagging them.
- Copy: English, sentence case everywhere ("Move to next actions", not "Move
  To Next Actions"), calm second person, short imperatives. List names are
  "Inbox", "Next actions", "Waiting for", "Someday / maybe". Use `·` between
  inline metadata. Sync state is always words ("Offline — 3 changes
  waiting"), never a colour alone. No emoji. Weekly review is flag-gated: a
  non-interactive `coming later` entry while the `weekly_review` flag is off
  (account-less: while its release switch is off; ADR-0027).

## Style

Swift API Design Guidelines, four-space indent, one primary type per file.
Conventional commits scoped to the app: `feat(ios): …`, `fix(ios): …`,
`ci(ios): …`.
