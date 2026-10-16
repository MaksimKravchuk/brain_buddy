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

- Only `Sources/BrainBuddyCore/BrainBuddyRustBridge.swift` and `BrainBuddyRustSyncBridge.swift`
  import the generated module;
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
  `RustStoreImportError`. The core (`bb-client` `import.rs`) takes the document's writer lock
  (the exclusive `flock` on `.store.json.lock`, which `FileDocumentStore` writers take) from its
  read of the file to the commit, so no app, widget or App Intent write can interleave, backs the
  file up with a schema manifest, stages and validates under the migration lock, and switches the
  store in one transaction or changes nothing; the legacy file is never modified. Its outbox entries and issues
  are carried whole, not converted. Change the import's counts or errors in Rust, the facade
  and the importer together.
- `BrainBuddyPersistence/RustOutboxImporter` is the one caller of
  `RustBridgeRuntime.legacyOutboxSends` / `resolveLegacyOutbox`, run after `RustStoreImporter`
  (`bb-client` `legacy_outbox.rs`). It lists the old sends from the Rust store (not from
  `store.json`, so it reads and locks nothing of the legacy file), asks a `LegacyReceiptLookup`
  about each (`NoLegacyReceipts` until the transport exists) and has the core classify, in one
  transaction: *unsent* (never left the device; still a pending intent), *accepted* / *rejected*
  (a receipt for the send's own idempotency key says so; only proven aliases are written),
  *awaiting* (sent, no proof, key still kept for 24 hours) and *uncertain* (an issue keeping
  `everSent`, `issuedAt`, `attempts`, key and body). Nothing is ever sent again or rebuilt as a new
  command, and a title, list or time never matches. The workspace must not run on the Rust store
  until the status says `mayRun` (every entry classified, no `unsent` intent left), and the UI must
  not say "synced" unless `fullySynced`. The `unsent` intents are the runtime's to turn into new
  commands (use the entry's idempotency key as the command ID so a retry is idempotent).
- `BrainBuddyWorkspace/RustRuntimeLauncher` + `RustRuntimeSelectionStore` choose the runtime per install
  (T044, pilot): `runtime/selection.json` beside the stores (App Group on iOS, the Mac's folder on
  macOS) names the Rust workspace identity; no file means legacy. Only the app writes it, and only
  after the PR-41/42 importers finished with `mayRun`; the default-OFF pilot switch
  (`RustRuntimePilotSwitch`, a local `UserDefaults` key, never a server flag) gates that first move
  alone. A handoff refused because a legacy writer committed after the import (`LEGACY_CHANGED`)
  removes the never-selected `imported` store (no client can open a store without a selection), so
  the next launch imports the changed file instead of meeting `IMPORT_ALREADY_IMPORTED`. The same holds
  after a crash: `runtime/import-pending` is written durably before the import and removed only after
  the selection is published; a launch that finds it with no selection discards the `imported` store and
  imports fresh. With no marker an existing store is never discarded. An existing selection that cannot be opened is `unavailable`, never a fallback to the
  retired file. Widgets and App Intents (`SharedWorkspace.make()`) read only the file and open the
  store through `Workspace.openForExtension`. The sync host plugs in at `RustTransportProvider`;
  `HostRustAccountLifecycle` is the production `RustAccountLifecyclePort` over the core's
  `link_account` / `remove_account_copy` (one transaction each, under the store's lock).
- `BrainBuddySync/RustSyncHost` is the Apple host of the shared sync loop (`bb-client`
  `transport.rs`/`subscriptions.rs`, `rust/bindings/swift/src/sync.rs`) and a `SyncRuntimePort`.
  The core's own threads run it (one sync worker over its own store connection, one hint-stream
  reader while foregrounded); Swift supplies the ports: `URLSessionRustSyncTransport` and
  `URLSessionRustSyncHintStream` (same-origin `URLSession`, no redirects, cancellation polled while
  blocked) over `BrainBuddyAPI.SessionCookieCredential`, which keeps the session token in the
  `SessionTokenStore` and applies the client's cookie rules (`Set-Cookie` renewal, 401 forgets the
  token sent). No token ever enters Rust. Build one after the account link is recorded with
  `RustSyncHost.start(…)` and install it as the selection's `transport`; call `enterBackground()`
  when the scene leaves the foreground. `UPGRADE_REQUIRED` reads as `SyncRuntimeWakeResult.updateNeeded`
  (`Workspace.runtimeSyncNeedsUpdate`, `RuntimeSyncRecovery.syncNeedsUpdate`). Tests use
  `BrainBuddyFakeServer`'s `StubServer` (URLProtocol); `RustSyncHostBackendTests` is the opt-in run
  against the real backend (`BB_BACKEND_PYTHON`). The `Rehearsal/` tests beside it (and `macos/Tests/.../MacRehearsalTests.swift`)
  are the opt-in automated rehearsal of the pilot scenarios Q01-Q12, skipped unless `BB_REHEARSAL_TARGET=local|prod`
  is set; `prod` is guarded (confirm variable, Keychain credentials, 300-request budget) and its results are never
  reference-device evidence (`ios/scripts/rehearsal_report.py` writes the evidence section).
- A Rust-selected `Workspace` save (`capture`, `apply`, `updateTask`, …) returns once the write is durable
  and its receipt adopted (SC-003, FR-001). What follows runs behind the return: the queries in use are
  read again (the page stays on screen, stale-while-revalidate, after a short quiet period so a burst of
  writes is one refresh), then the status read and the transport wake, each single-flight and latest-wins.
  The next command waits only for a read of the tasks the last save changed (their revisions); one that
  touched a project, tag, subtask or comment, and any review decision, waits for the full refresh.
  Code that must see the write in a page or count (tests, a screen that reads it at once) prepares the
  query it reads or awaits `Workspace.settleRustWork()`; `flush()` does. The capture preview is dropped
  on submit and by `discardCapturePreviews()` (call it when the sheet is dismissed), never refreshed
  after a save. Blocking bridge calls run on `RustBridgeExecutor` (one thread per runtime, writes and
  the reads a save depends on ahead of query refreshes), not on the cooperative pool, and pages are
  decoded off the main actor (`RustPreparedPage`).
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
| `BrainBuddyKit/Sources/BrainBuddyDesign` | The Carry On design system for the iPhone and Mac: generated tokens, the bundled Instrument faces, SwiftUI components and their catalog | Hold GTD rules, or hand-edit `Generated/` |
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

### Carry On design system (the redesign)

- One source: `BrainBuddyKit/DesignTokens/carry-on.tokens.json`, copied from the
  design canvas boards. `python3 scripts/generate_design_tokens.py` writes
  `BrainBuddyDesign/Generated/`; `DesignTokensTests` fails when the two disagree.
  Never type a hex, size or radius into a screen: add a token, regenerate, use it.
- Screens are built from the `BrainBuddyDesign` components (`CarryOnButtonStyle`,
  `CarryOnNextStepCard`, `CarryOnStepRow`, `CarryOnChip`, …). A component that is
  missing is added there, with its states in `CarryOnCatalog`, not drawn in a screen.
- `CarryOnCatalogSnapshotTests` (macOS) renders every catalog section at iPhone and
  Mac sizes, light and dark, against `Tests/BrainBuddyDesignTests/__Snapshots__/`.
  A snapshot is committed only after it was compared with the design board and
  approved; any later pixel change fails the `ios-app` lane. App and Mac snapshot
  tests use the same `assertSnapshot` from the `BrainBuddyDesignTestSupport` product.
- Colours follow the design board exactly, including grey text on stone (3.98:1).
  Change a colour for contrast only when App Review or an accessibility audit asks
  for it (Max, 2026-10-16).

### Current system

- The app theme (`BrainBuddy/DesignSystem/Theme.swift`: `BBColor`, `BBFont`, `bbCard`)
  maps onto Carry On: colours come from the `BrainBuddyDesign` roles in light and dark,
  fonts are the Instrument faces (`CarryOnFonts.register()` runs at launch), and the app
  tint (`AccentColor`) is basalt/limestone, because terracotta is only for the one next
  step. Screens keep calling `BBColor` / `BBFont`; stored project colours from the old
  palette are displayed as the Carry On colour at the same index, never rewritten.
- The brand curve `cubic-bezier(0.22, 1, 0.36, 1)` for our own animations, 44 pt hit
  targets, Reduce Motion respected.
- Glass on chrome only (tab bar, toolbars, sheets, the capture accessory,
  floating clusters); content stays flat.
- Pending product sign-off (`docs/native-ios-app.md`): SF Symbols instead of
  Lucide (use the documented mapping) and system glass motion. Do not add more
  deviations without flagging them.
- Copy: English, sentence case everywhere ("Move to next actions", not "Move
  To Next Actions"), calm second person, short imperatives. List names are
  "Inbox", "Next actions", "Waiting for", "Someday / maybe". Use `·` between
  inline metadata. Sync state is always words ("Offline · 3 changes
  waiting"), never a colour alone. No emoji. Weekly review is flag-gated: a
  non-interactive `coming later` entry while the `weekly_review` flag is off
  (account-less: while its release switch is off; ADR-0027).

## Style

Swift API Design Guidelines, four-space indent, one primary type per file.
Conventional commits scoped to the app: `feat(ios): …`, `fix(ios): …`,
`ci(ios): …`.
