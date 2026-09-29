# Brain Buddy for iOS

The native, offline-first Brain Buddy app for iPhone and iPad: SwiftUI on
iOS 26 with Liquid Glass. Every GTD action works without a network; the server
is somewhere to sync to. The design, the data model and the sync rules are in
[`docs/native-ios-app.md`](../docs/native-ios-app.md). This app sits beside the
Expo client in `mobile/` and grew out of the macOS prototype in `macos/`.

Agent and contributor rules are in [`AGENTS.md`](AGENTS.md).

## Requirements

- A Mac with **Xcode 26** (iOS 26 SDK) and an iOS 26 simulator or device.
- **XcodeGen 2.42 or later**: `brew install xcodegen`. The Xcode project is
  generated, not committed.
- For the package on Linux: Docker (no Xcode needed).

## Generate and open

```sh
cd ios
xcodegen generate
open BrainBuddy.xcodeproj
```

Run `xcodegen generate` again after pulling and after adding, moving or
deleting files. Source folders are globbed, so a new file only needs a
regenerate, never a project edit.

`project.yml` is the source of truth. These files are written from it on every
generate and are git-ignored; change `project.yml` instead of editing them:

- `BrainBuddy.xcodeproj`
- `BrainBuddy/Resources/Info.plist`, `BrainBuddy/Resources/BrainBuddy.entitlements`
- `BrainBuddyWidgets/Info.plist`, `BrainBuddyWidgets/BrainBuddyWidgets.entitlements`

Build from the command line exactly as CI does (unsigned, simulator):

```sh
cd ios
xcodebuild -project BrainBuddy.xcodeproj -scheme BrainBuddy \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

The `BrainBuddy` scheme builds the app and the widget extension; its test
action runs the package's test targets on a simulator:

```sh
xcodebuild test -project BrainBuddy.xcodeproj -scheme BrainBuddy \
  -destination 'platform=iOS Simulator,name=iPhone 17'
```

## Signing and identifiers

Every identifier derives from one build setting, `BB_BUNDLE_ID_PREFIX`
(`settings.base` in `project.yml`, default `com.brainbuddy`):

| Identifier | Value | Where it is used |
|---|---|---|
| App bundle id | `<prefix>.ios` | `PRODUCT_BUNDLE_IDENTIFIER`, App Store Connect app record |
| Widget extension | `<prefix>.ios.widgets` | `PRODUCT_BUNDLE_IDENTIFIER` of `BrainBuddyWidgets` |
| App Group | `group.<prefix>.ios` | `BB_APP_GROUP_ID`: both entitlements, and the `BBAppGroupIdentifier` Info.plist key in both bundles |
| Background refresh task | `<prefix>.ios.refresh` | `BGTaskSchedulerPermittedIdentifiers` |
| URL scheme | `brainbuddy://` | `CFBundleURLTypes` |

Code never spells these out: it reads the App Group from the
`BBAppGroupIdentifier` Info.plist key and registers the refresh task as
`Bundle.main.bundleIdentifier + ".refresh"`. Signing under another team's
namespace is therefore one change, followed by `xcodegen generate`:

- edit `BB_BUNDLE_ID_PREFIX` in `project.yml`, or
- pass `BB_BUNDLE_ID_PREFIX=com.example` to `xcodebuild` (CI does this from
  the `IOS_BUNDLE_ID_PREFIX` variable).

The prefix must match, in every place that names it: `project.yml` (or the
`IOS_BUNDLE_ID_PREFIX` variable that overrides it in CI), the App Store Connect
app record, and the identifiers registered under Certificates, Identifiers &
Profiles (app id, widget id, App Group). Automatic signing registers the last
three for you on the first signed build.

**Team.** `DEVELOPMENT_TEAM` is deliberately empty in `project.yml`, so no
team id is committed and CI's variable is the only one.

- Simulator: builds usually need no team. If Xcode asks for one, set it as
  below.
- Device: choose your team under *Signing & Capabilities* for both targets
  (the choice lasts until the next `xcodegen generate`), or pass
  `DEVELOPMENT_TEAM=<team id>` to `xcodebuild`.

**Capabilities.** App Groups (both targets) and the background fetch mode.
There is no keychain sharing: the widget and the App Intents never sync, so
they never need the session.

## Package tests

`BrainBuddyKit` holds everything below the SwiftUI layer (rules, persistence,
API, sync, the app model) and builds and tests on macOS and Linux.

```sh
# macOS
cd ios/BrainBuddyKit && swift test

# Linux, or any machine with Docker (build products go to .build-linux/)
sh ios/scripts/swift-linux.sh test
sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests
```

## Layout

| Path | What it is |
|---|---|
| `project.yml` | XcodeGen spec: targets, settings, Info.plists, entitlements, scheme |
| `BrainBuddyKit/` | Swift package, no dependencies: `BrainBuddyCore`, `BrainBuddyPersistence`, `BrainBuddyAPI`, `BrainBuddySync`, `BrainBuddyWorkspace` |
| `BrainBuddy/` | App target: `App/`, `DesignSystem/`, `Components/`, `Screens/`, `Intents/`, `Resources/` (asset catalog) |
| `BrainBuddyWidgets/` | WidgetKit extension: widgets and Control Center controls, its own asset catalog |
| `Shared/` | Compiled into both the app and the widget extension. `PrivacyInfo.xcprivacy` lives here so both bundles ship it |
| `ci/ExportOptions.plist` | `xcodebuild -exportArchive` options for the TestFlight upload |
| `scripts/swift-linux.sh` | `swift <args>` for the package inside the `swift:6.2-noble` image |
| `scripts/select-xcode.sh` | CI: selects the newest installed Xcode 26 on a GitHub macOS runner |

## CI

[`.github/workflows/ios.yml`](../.github/workflows/ios.yml) runs on pull
requests and on pushes to `main` and `trunk-candidate/**` that touch `ios/`
(or the workflow), and on manual dispatch.

| Job | Runner | What it proves |
|---|---|---|
| `kit-linux` | `ubuntu-latest`, `swift:6.2-noble` | The package builds and its tests pass on Linux |
| `app-macos` | `macos-26`, newest Xcode 26 | The generated project builds the app and widgets for the simulator (unsigned); the package tests pass on macOS. The raw `xcodebuild` log and `.xcresult` are uploaded on failure |
| `testflight` | `macos-26`, `testflight` environment | Only on `main` (push or dispatch), after both jobs pass: archive, sign, upload |

This workflow is not part of `make verify-all` and not a landing-required
check; it is separate from `ci.yml` so iOS changes do not slow the web
pipeline down.

## TestFlight

Every push to `main` that touches `ios/` (and every manual run on `main`)
uploads a build to TestFlight once `kit-linux` and `app-macos` pass. Until the
owner finishes the setup below, the `testflight` job writes what is missing to
the run summary ("TestFlight upload skipped: configure …") and stays green.

### One-time setup

1. **Identifiers.** In Certificates, Identifiers & Profiles register the app id
   `<prefix>.ios`, the widget id `<prefix>.ios.widgets` and the App Group
   `group.<prefix>.ios`, with App Groups enabled on both ids. (Automatic
   provisioning can register them on the first CI archive, but the App Store
   Connect record in step 2 needs the app id to exist.)
2. **App record.** In App Store Connect create the app (*Apps → +*, iOS) with
   bundle id `<prefix>.ios`. The name, SKU and primary language are yours.
3. **API key.** *Users and Access → Integrations → App Store Connect API →
   Team keys*: create a key with the **Admin** role. Admin is what lets
   `xcodebuild` create cloud-managed distribution certificates; App Manager is
   not enough. Download the `.p8` (it can be downloaded once) and note the key
   id and the issuer id.
4. **GitHub environment.** *Settings → Environments → New environment*, named
   `testflight`:
   - *Deployment branches and tags*: **Selected branches → `main`**. This
     branch policy, not the workflow's `if`, is what keeps the key away from
     pull requests and other branches, as the `production` environment does
     for Fly.
   - Optional: required reviewers, to approve each upload.
   - Secrets:
     - `APP_STORE_CONNECT_API_KEY_ID`: the key id
     - `APP_STORE_CONNECT_API_ISSUER_ID`: the issuer id
     - `APP_STORE_CONNECT_API_KEY_P8`: the full contents of the `.p8` file,
       including the `BEGIN`/`END` lines
   - Variables (environment or repository level):
     - `APPLE_TEAM_ID` (required): the 10-character team id
     - `IOS_BUNDLE_ID_PREFIX` (optional): overrides `BB_BUNDLE_ID_PREFIX`;
       leave unset to use `project.yml`'s value
     - `IOS_BUILD_NUMBER_OFFSET` (optional, default `0`): see below
5. **Testers.** In App Store Connect, *TestFlight → Internal Testing*: create
   a group, add yourself, and turn on automatic distribution so every processed
   build reaches the group. `ITSAppUsesNonExemptEncryption = false` in the
   Info.plist answers the export-compliance question, so builds are not held
   for it.

Then run the workflow on `main` (*Actions → iOS → Run workflow*), or push a
change under `ios/`.

### What the job does

1. Selects the newest Xcode 26 and generates the project.
2. Writes the key to `$RUNNER_TEMP/private_keys/AuthKey_<key id>.p8` (mode 600).
3. `xcodebuild archive` (Release, `generic/platform=iOS`) with
   `DEVELOPMENT_TEAM`, `CURRENT_PROJECT_VERSION` and, if set,
   `BB_BUNDLE_ID_PREFIX` on the command line, and `-allowProvisioningUpdates`
   with the API key: automatic signing creates or refreshes the certificates
   and profiles it needs.
4. `xcodebuild -exportArchive` with `ci/ExportOptions.plist` (the team id is
   added to a temporary copy): method `app-store-connect`, destination
   `upload`, so the export uploads the build and its symbols directly.
5. Writes the bundle id, version, build and commit to the run summary, and
   deletes the key whatever happened. On failure it uploads the archive and
   export logs, with the key id and issuer id redacted.

### Build numbers and versions

- Build number (`CFBundleVersion`) = the workflow's run number +
  `IOS_BUILD_NUMBER_OFFSET`. App Store Connect needs it to go up. If builds
  were uploaded from somewhere else with higher numbers, raise the offset past
  them.
- Re-running a failed run keeps its run number. That is fine when the upload
  never happened; if it did, App Store Connect rejects the duplicate. Start a
  fresh run from *Run workflow* instead.
- The version (`CFBundleShortVersionString`) is `MARKETING_VERSION` in
  `project.yml` (`0.1.0`). Bump it there when you start a new version.

### Cost

The `app-macos` and `testflight` jobs use macOS runners, which are free on
public repositories. On a private repository, macOS minutes are billed at a
multiple of the Linux rate (10× at the time of writing; check GitHub's
current pricing). Only pushes and pull requests that touch `ios/` run them.

### When the upload fails

- *No profiles / no signing certificate*: the API key is not Admin, or the
  identifiers in step 1 are missing or under another prefix.
- *Bundle version must be higher*: raise `IOS_BUILD_NUMBER_OFFSET`.
- *ITMS-91053 Missing API declaration*: code started using a required-reason
  API; declare it in `Shared/PrivacyInfo.xcprivacy`.
- *No suitable application records*: the App Store Connect record (step 2) is
  missing or has a different bundle id.

## Offline QA checklist

Run on a device (or simulator with the Mac's network off) in **airplane
mode**. Nothing below may show a spinner that waits on the network, lose
data, or need a sign-in.

- [ ] Fresh install, no account: the app opens straight into Inbox ("On this
      iPhone").
- [ ] Capture from the capture bar with Smart Add: `Call Sam #phone @Garage`
      creates the task, the new tag and the new project; the preview shows
      what will be created before saving.
- [ ] Process inbox: clarify each item to Next, Waiting (asks who or what),
      Someday, a project, or complete it, one at a time.
- [ ] Move between lists, complete (the undo toast reopens into the previous
      list), cancel, and reopen from Completed / Cancelled into a chosen list.
- [ ] Edit title, notes, due date, priority, project, tags and waiting-for;
      add, rename, complete and reopen subtasks; add and edit comments.
- [ ] Projects: create, rename, recolour, archive ("needs a next action"
      shows correctly). Tags: create, rename, delete.
- [ ] Today shows Overdue / Today / Upcoming; search, sort, group by project,
      and the priority and tag filters all work.
- [ ] Widgets show current counts and tasks; completing from a widget or a
      Control Center control updates the app.
- [ ] Siri / Shortcuts capture and completion work and appear in the app.
- [ ] Force-quit and relaunch: everything above is still there.
- [ ] The sync status reads "Offline — N changes waiting" in words.
- [ ] Turn the network on and sign in: local data uploads, the status reaches
      "Synced …", and the web app shows the same tasks, projects and tags.

## Known gaps

- The SwiftUI layer compiles only on macOS; it has no automated UI tests.
  The rules it relies on are tested in the package.
- iOS results are not in the Allure report or `make verify-all`, and
  `ios.yml` does not gate landing.
- An iOS-only landing still redeploys the Fly apps: `ios/` is not in the
  inert set of `scripts/classify_deploy_paths.sh` (gate-guarded, so that is a
  separate change).
- The design deviations in `docs/native-ios-app.md` (SF Symbols, derived dark
  mode, SF Pro, system glass motion) are awaiting product sign-off.
- The app icon is the Sprout logo in white on sky (`#0EA5E9`), a single
  1024 × 1024 px image; iOS derives the dark and tinted variants. No other
  brand mark exists yet.
- `Shared/PrivacyInfo.xcprivacy` declares a baseline (UserDefaults, file
  timestamps, account email and user content for app functionality). Keep it
  in step with the code.
- CI signs automatically on a fresh runner each time, so the team may gain an
  Apple Development certificate per run. Revoke stale ones in Certificates,
  Identifiers & Profiles if they pile up.
- Background refresh is opportunistic (iOS decides when); widgets show the
  state of the last write to the shared store.
- Weekly review stays deferred; the brain dump is pass 2.
