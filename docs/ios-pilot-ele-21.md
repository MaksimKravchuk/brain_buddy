# ELE-21 iOS pilot build and smoke record

## Scope and backend contract

The client targets iOS 17 and is packaged as a dependency-free Swift Package so it can be opened directly in Xcode or embedded in a signed host target. It integrates only with the current session-cookie endpoints: `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, and `GET /api/auth/me`. `URLSession`'s shared cookie store carries the HTTP-only session cookie; the client does not read, persist, or log the token.

The current backend has no password-reset, account-deletion, or delegated-research endpoint. The pilot UI therefore states those limitations and routes recovery/deletion to the pilot coordinator. It does not claim completion or issue an invented API mutation. Research rendering accepts a validated result value only: exactly three options, every option with at least one source and non-empty uncertainty.

## Safety boundary

The result screen says that BrainBuddy cannot contact providers, book appointments, make purchases, or complete the task. Source URLs are the only interactive result actions. There are no phone, booking, checkout, purchase, or autonomous-completion controls.

## Distribution and test path

Chosen path: internal development build first, then internal TestFlight after an Apple team, bundle identifier, signing identity, privacy metadata, and App Store Connect record are assigned. This repository intentionally contains no team ID or signing material. The package can be added to a minimal SwiftUI host target without third-party dependencies.

Required local verification on an Apple host:

1. Open `ios/Package.swift` in Xcode 16 or newer and run the `BrainBuddyPilot` tests on an iPhone 15 simulator running iOS 17.5 or newer.
2. Embed the package in the signed host target, set its Debug API base URL to a reachable BrainBuddy backend, and launch on that simulator.
3. Mint a disposable invite; verify signup, logout, login, relaunch/session restoration through `GET /api/auth/me`, invalid-invite messaging, and invalid-login messaging.
4. Open Account Help and verify recovery/deletion limitations are visible.
5. Render a fixture/result with exactly three sourced options and verify uncertainty plus the prohibited-action notice; verify no provider-contact, booking, purchase, or completion control exists.

## Evidence from this execution environment

Execution host: Linux workspace on 2026-08-05. Neither `xcodebuild` nor `swift` is installed, and no iOS Simulator or physical Apple device is attached. Consequently no honest launch/session smoke claim can be made here. Static inspection confirms the package layout, endpoint paths, cookie-preserving `URLSession` use, three-option validation, source/uncertainty requirements, and boundary copy. Simulator/device smoke remains a named Apple-host handoff, not a passed check.
