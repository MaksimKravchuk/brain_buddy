# Brain Buddy for iOS

The native, offline-first Brain Buddy app for iPhone and iPad: SwiftUI on
iOS 26 with Liquid Glass. Every GTD action works without a network; the server
is somewhere to sync to. The design, the data model and the sync rules are in
[`docs/native-ios-app.md`](../docs/native-ios-app.md). It is the iPhone client
(the Expo client that used to live in `mobile/` was removed) and grew out of
the macOS prototype in `macos/`.

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
(`settings.base` in `project.yml`, default `brainbuddy`):

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
| `BrainBuddyKit/` | Swift package, no dependencies: `BrainBuddyCore`, `BrainBuddyPersistence`, `BrainBuddyAPI`, `BrainBuddySync`, `BrainBuddyWorkspace`, `BrainBuddyDiagnostics` |
| `BrainBuddy/` | App target: `App/`, `DesignSystem/`, `Components/`, `Screens/`, `Intents/`, `Resources/` (asset catalog) |
| `BrainBuddyWidgets/` | WidgetKit extension: widgets and Control Center controls, its own asset catalog |
| `Shared/` | Compiled into both the app and the widget extension. `PrivacyInfo.xcprivacy` lives here so both bundles ship it |
| `ci/ExportOptions.plist` | `xcodebuild -exportArchive` options for the TestFlight upload |
| `scripts/swift-linux.sh` | `swift <args>` for the package inside the `swift:6.2-noble` image |
| `scripts/select-xcode.sh` | CI: selects the newest installed Xcode 26 on a GitHub macOS runner |

## CI

The app is built and tested by two lanes of the main CI,
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml). Like the backend
and frontend lanes they are part of `Full CI`, the verdict a pull
request merges on and a trunk candidate lands on, so no change reaches `main`
with the package tests red or the app unbuilt.

| Job | Runner | What it proves |
|---|---|---|
| `ios-kit` | `ubuntu-latest`, `swift:6.2-noble` | The package builds and its tests pass on Linux |
| `ios-app` | `macos-26`, newest Xcode 26 | The generated project builds the app and widgets for the simulator (unsigned); the package tests pass on macOS. The raw `xcodebuild` log and `.xcresult` are uploaded on failure |

On a pull request they do their work only when it touches `ios/` (or a shared
surface such as `.github/` or `scripts/`); otherwise they pass at once, and
`ios-app` does so on Linux rather than waiting for a macOS runner. On pushes
to `main` and `trunk-candidate/**` they always run, as every lane does on the
landing path.

[`.github/workflows/ios.yml`](../.github/workflows/ios.yml) only uploads: see
TestFlight below. Neither is part of `make verify-all`.

XcodeGen is the release zip of the version in `XCODEGEN_VERSION`, checked
against `XCODEGEN_SHA256` and against `xcodegen --version` before it runs;
both workflows pin the same pair. To upgrade XcodeGen, download the new
`xcodegen.zip`, take its `shasum -a 256`, and change both values together in
both files. In `ios.yml`, which holds the App Store Connect key, every action
is also pinned to a commit SHA (with its tag in a comment).

## TestFlight

`ios.yml` uploads from `main` and from feature branches.

- **`main`**: it starts when CI completes on a push to `main`. If that run
  passed and its commit changed the app itself, it uploads that commit, so
  every `main` build passed `ios-kit` and `ios-app` first. "The app itself"
  is `BrainBuddy/`, `BrainBuddyWidgets/`, `Shared/`, the kit's `Sources/`,
  `Package.swift`/`Package.resolved` and `project.yml`, minus Markdown
  (`ci/testflight_changes.py`); tests, docs, `ci/`, `scripts/` and the macOS
  app alone never upload. The commit is compared with its first parent,
  which covers a trunk landing and a merged or squashed pull request; if
  several commits are pushed at once only the last one is checked, so
  dispatch the workflow for anything that missed an upload.
- **Any other branch**: nothing uploads automatically. Run the workflow on
  that branch (*Actions → iOS TestFlight → Run workflow*, pick the branch) to
  upload its head straight away, without waiting for CI, for fast feedback
  on a phone. The build carries `<branch> @ <commit>`
  in Settings → About (the `BBBuildLabel` Info.plist key, from
  `BB_BUILD_LABEL`).
- **What to Test** on every build (`ci/testflight_changes.py`, written by
  `ci/testflight_notes.py`, best effort): `<branch> @ <commit>`, the pull
  request title (or the commit subject), and one line per commit that
  changed the app — on `main` since the previous `main` commit, on a branch
  since it left `main`. It stays under Apple's 4000-character cap, and the
  run summary shows the same text.
- **Manual run on `main`** uploads the current `main`, whether or not it
  changed `ios/`.

Uploads from all branches, `main` included, run one at a time, because the
build number is the run number and App Store Connect rejects a build whose
number is not higher than the last one uploaded. GitHub keeps at most one
upload waiting: a newer one, from any branch, replaces it. If a `main` upload
was replaced that way, dispatch the workflow on `main` again.

Until the owner finishes the
setup below, the `testflight` job writes what is missing to the run summary
("TestFlight upload skipped: configure …") and stays green.

### One-time setup

1. **Identifiers and a device.** In Certificates, Identifiers & Profiles
   register the app id `<prefix>.ios`, the widget id `<prefix>.ios.widgets`
   and the App Group `group.<prefix>.ios`, with App Groups enabled on both
   ids. (Automatic provisioning can register them on the first CI archive,
   but the App Store Connect record in step 2 needs the app id to exist.)
   Also register at least one device under *Devices* (any iPhone of yours;
   its UDID is in Finder when it is connected to a Mac, under the device
   name). Automatic signing archives with a development profile and only
   re-signs for the App Store on export, and Apple issues no development
   profile to a team without devices. TestFlight testers need not be
   registered.
2. **App record.** In App Store Connect create the app (*Apps → +*, iOS) with
   bundle id `<prefix>.ios`. The name, SKU and primary language are yours.
3. **API key.** *Users and Access → Integrations → App Store Connect API →
   Team keys*: create a key with the **Admin** role. Download the `.p8` (it
   can be downloaded once) and note the key id and the issuer id.

   *Why Admin.* Archive imports a reusable Apple Development identity (below)
   and automatic provisioning obtains/refreshes profiles for both targets.
   Export uses the cloud-managed distribution certificate through the API key;
   that takes the Admin role, not App Manager.

   *What it can do if it leaks.* A team key is not scoped to this app. Until
   someone revokes it, whoever holds the `.p8`, key id and issuer id acts as
   an Admin of the whole team through the App Store Connect API: every app's
   builds, TestFlight testers and App Store submissions, certificates,
   identifiers, devices and profiles (including revoking the certificates
   other apps sign with), and users and their roles. It does not expire on its
   own. That is why the next step's protection rules are not optional, why the
   job deletes the key before any third-party action runs, and why the answer
   to a suspected leak is to revoke the key in *Users and Access →
   Integrations* at once and create a new one.
4. **GitHub environment.** *Settings → Environments → New environment*, named
   `testflight`.
   - *Deployment branches and tags*: **No restriction**, so branch builds
     can use the key. This is a deliberate trade-off for fast feedback:
     anyone with write access can dispatch any branch and get it signed and
     uploaded with the Admin key (pull requests from forks cannot, they get
     no secrets). To tighten it later, restrict the policy to a pattern such
     as `main` and `claude/*`.
   - *Required reviewers*: none. A reviewer gate would make every branch
     upload wait for a second click; add one (with **Prevent self-review**) if more
     people get push access.
   - Secrets:
     - `APP_STORE_CONNECT_API_KEY_ID`: the key id
     - `APP_STORE_CONNECT_API_ISSUER_ID`: the issuer id
     - `APP_STORE_CONNECT_API_KEY_P8`: the full contents of the `.p8` file,
       including the `BEGIN`/`END` lines
     - `IOS_DEVELOPMENT_CERTIFICATE_BASE64`: Base64 of a password-protected
       `.p12` containing exactly one Apple Development certificate and its
       private key for `APPLE_TEAM_ID`. Export that certificate from Xcode's
       *Settings → Accounts → team → Manage Certificates → Export Certificate*,
       then use `base64 -i /path/to/development.p12 | pbcopy` and paste directly
       into this environment secret. A downloaded `.cer` contains no private key.
     - `IOS_DEVELOPMENT_CERTIFICATE_PASSWORD`: the `.p12` export password.
       Keep both secrets in this environment, with no repository-level duplicates.
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

The two development-signing secrets are required once the existing Apple API/team
setup is configured; missing or invalid values fail before archive. CI imports the
identity into a temporary keychain, verifies the team and trusted certificate,
and checks app/widget archive leaf certificates match it before export. Decoded
`.p12` is removed after installation; always-run cleanup removes the keychain and
API key. Failure logs are redacted and uploaded only after successful cleanup.

Under the existing unrestricted branch policy, repository writers who can run
branch workflows can extract this reusable private key as well as the Admin API
key. These are controller-side operational credentials, excluded from BrainBuddy
account export and unaffected by account deletion. Retain the downloaded public
`.cer` privately outside the repository to identify the active certificate and
expiry. Before expiry, replace both environment secrets together with a new
matching identity. On suspected disclosure or retirement, the owner must match
and revoke only the affected certificate, replace/remove both secrets, and audit
the affected runs. Reverting workflow code does not invalidate a disclosed key.
CI never revokes certificates automatically.

Then run the workflow on a branch (*Actions → iOS TestFlight → Run
workflow*), or land a change under `ios/`.

### What the job does

1. Selects the newest Xcode 26, installs the pinned XcodeGen and generates the project.
2. Writes the key to `$RUNNER_TEMP/private_keys/AuthKey_<key id>.p8` (mode 600).
3. `xcodebuild archive` (Release, `generic/platform=iOS`) with
   `DEVELOPMENT_TEAM`, `CURRENT_PROJECT_VERSION`, `BB_BUILD_LABEL` and, if set,
   `BB_BUNDLE_ID_PREFIX` on the command line, and `-allowProvisioningUpdates`
   with the API key: automatic signing creates or refreshes the certificates
   and profiles it needs.
4. `xcodebuild -exportArchive` with `ci/ExportOptions.plist` (the team id is
   added to a temporary copy): method `app-store-connect`, destination
   `upload`, so the export uploads the build and its symbols directly.
5. Writes the change list above into the build's *What to Test*
   through the App Store Connect API (`ci/testflight_notes.py`: standard
   library and the system `openssl` only, polls up to 15 minutes for the
   build to appear; a failure only warns).
6. Deletes the key, whatever happened, as soon as those steps are over:
   before the summary, the log redaction and the artifact upload.
7. Writes the bundle id, version, build, branch and commit to the run summary. On
   failure it uploads the archive and export logs, with the key id and issuer
   id redacted.

### Build numbers and versions

- Build number (`CFBundleVersion`) = the workflow's run number +
  `IOS_BUILD_NUMBER_OFFSET`. App Store Connect needs it to go up. The run
  number is shared by `main` and branch uploads and counts every CI
  completion on `main`, uploads or not, so builds skip
  numbers; that is fine. If builds were uploaded from somewhere else with
  higher numbers, raise the offset past them.
- Re-running a failed run keeps its run number. That is fine when the upload
  never happened; if it did, App Store Connect rejects the duplicate. Start a
  fresh run from *Run workflow* instead.
- The version (`CFBundleShortVersionString`) is `MARKETING_VERSION` in
  `project.yml` (`0.1.0`). Bump it there when you start a new version.

### Cost

The `ios-app` and `testflight` jobs use macOS runners, which are free on
public repositories. On a private repository, macOS minutes are billed at a
multiple of the Linux rate (10× at the time of writing; check GitHub's
current pricing). `ios-app` takes a macOS runner for pull requests that touch
`ios/` or a shared surface and for every push to `main` or
`trunk-candidate/**`; `testflight` for every upload, including each
dispatched branch build.

### When the upload fails

- *No profiles / no signing certificate*: the API key is not Admin, or the
  identifiers in step 1 are missing or under another prefix.
- *Your team has no devices from which to generate a provisioning profile*:
  register a device (step 1), then re-run.
- *Conflicting provisioning settings … automatically signed for development*:
  something set `CODE_SIGN_IDENTITY` to a distribution identity. Automatic
  signing must archive with `Apple Development`; export re-signs it.
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
      Someday, a project, or complete it, one at a time. "Make it a project"
      names the project and asks for the first next action; Undo puts the
      item back and archives the project. The Project chip can also create a
      new project.
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

## Performance diagnostics (beta)

While the app ships through TestFlight it records its own performance, so a
report of the phone running hot comes with figures. **Settings → About →
Performance** shows them and exports them.

| Recorded | How | Arrives |
|---|---|---|
| CPU use of the app's process | Every 10 s in the foreground, with the screen on top (by kind: `inbox`, `task`, `capture`, never content), the thermal state and Low Power Mode. 100 % is one core busy the whole time | At once |
| Thermal state changes | `ProcessInfo.thermalStateDidChangeNotification`, with the screen on top | At once |
| MetricKit daily reports | CPU and GPU time, hitches, network, disk writes, foreground and background time | About once a day |
| MetricKit diagnostic reports | CPU exceptions, hangs, excessive disk writes, crashes, with call stacks | After the event, usually at the next launch |

Everything stays in the app's Caches directory (the log keeps six hours of
foreground samples, 30 reports of each kind) until **Export diagnostics**
shares one JSON file (`BrainBuddy-diagnostics-<UTC time>.json`) through the
share sheet: AirDrop, Files, Mail, Messages. **Clear diagnostics** starts over,
for example before a test session.

To report heating: clear, use the app the way that warms the phone, then
export. If no MetricKit reports arrive after a couple of days, turn on
Settings → Privacy & Security → Analytics & Improvements → Share With App
Developers. Stack frames from the app in diagnostic reports are addresses;
symbolicate them with the build's dSYMs from App Store Connect.

The build setting `BB_PERFORMANCE_DIAGNOSTICS` in `project.yml` turns all of
it on (YES, every build today). Set it to NO before the first App Store
release; then nothing is recorded and the Performance row is gone.

## Known gaps

- The SwiftUI layer compiles only on macOS; it has no automated UI tests.
  The rules it relies on are tested in the package.
- iOS results are Swift Testing and `xcodebuild` output: they gate
  `Full CI` but are not in the Allure report or `make verify-all`.
- The design deviations in `docs/native-ios-app.md` (SF Symbols, derived dark
  mode, SF Pro, system glass motion, sky-700 for text and filled controls) are
  awaiting product sign-off.
- The app icon is the Sprout logo in white on sky (`#0EA5E9`), a single
  1024 × 1024 px image; iOS derives the dark and tinted variants. No other
  brand mark exists yet.
- `Shared/PrivacyInfo.xcprivacy` declares a baseline (UserDefaults, file
  timestamps, account email and user content for app functionality). Keep it
  in step with the code.
- Fresh CI runners reuse the configured Apple Development identity. If archive
  reports a certificate quota error, check the installation/validity step and
  configured team; verify the portal inventory before an owner-authorized repair.
  Routine certificate revocation is not part of the upload workflow.
- Background refresh is opportunistic (iOS decides when); widgets show the
  state of the last write to the shared store.
- The weekly review is flag-gated (`docs/native-ios-app.md`); its notification, widget chip, day and time settings and AI navigator are not built yet. The brain dump is pass 2.
