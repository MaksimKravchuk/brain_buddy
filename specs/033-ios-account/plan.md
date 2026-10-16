# Implementation Plan: iPhone account screens and invite step

**Branch**: `033-ios-account` · **Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md)

## Summary

Bring the account rights of spec 023 to the iPhone as boards 25–28 draw them, and restyle
the invite step to board 06. The kit gains the account-change calls and an
`@Observable` model that holds every rule the screens need (which methods show, which
action each allows, proof freshness, failures); the app screens only render it.

## Technical Context

- Swift 6, iOS 26, SwiftUI; Swift Testing; no third-party dependencies.
- Server contracts: spec 023 (`/auth/confirm/password`, `/auth/email/*`,
  `/auth/{provider}/start` with purpose `reauth`/`link`, `/account/auth-*`), `GET/PATCH /account`.
- Package tests run on Linux (`sh ios/scripts/swift-linux.sh test`); the app target
  compiles in CI's `ios-app` lane.

## Constitution Check

- Principle II: the kit model and client carry the behaviour and are tested first
  (`AccountSecurityModelTests`, `AccountSecurityAPITests`, ids `033-FR-…`). Views are
  thin and checked by the `ios-app` build plus the board comparison.
- No feature flag: GDPR account rights are always on.
- No new design colours; one layout token added through the generator.

## Architecture

- `BrainBuddyAPI/AccountSecurityAPI.swift`: `AccountAction`, `RecentProof` (redacted),
  the change calls; `Endpoint.headers` carries `X-BrainBuddy-Expected-Owner`.
- `BrainBuddyWorkspace/AccountSecurityModel.swift`: `AccountSecurityRemote` protocol,
  method rows, confirmation options, password rule (12+ characters, typed twice),
  failure mapping (wrong account, expired proof, uncertain outcome), and every action.
  A proof is checked for expiry and action before any request (033-SC-002).
- App: `Screens/Account/` (Account, Sign in, sheets), `Components/CodeBoxesField.swift`,
  `AccountModels` (one model per linked account, above the navigation stacks), routes
  `.account` and `.signInMethods`. `Screens/Settings/SignInSheet.swift` hosts the invite step.

## Delivery phases

PR-01 foundation (kit + shared app pieces), then PR-02 (Account screen), PR-03 (Sign in
screen) and PR-04 (invite) in parallel; see [tasks.md](tasks.md).

## Verification

- `sh ios/scripts/swift-linux.sh test --filter AccountSecurity`
- CI `ios-app` lane builds the app.
- Board comparison in light and dark (033-SC-001), by the design thread / Max on device.

## Risks

- App target is not compiled locally on Linux: CI is the first compile of the views.
- Provider linking depends on Apple/Google sign-in on a real device; covered by the
  existing `ModernAuthCoordinator` paths.

## Complexity Tracking

PR-01 and PR-02 exceed the default slice budget; each states why in `oversize_reason`.
