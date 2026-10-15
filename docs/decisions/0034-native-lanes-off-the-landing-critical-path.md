# ADR-0034: Native lanes follow the path filter on the landing path

Date: 2026-10-15
Status: Accepted by the product owner, 2026-10-15
Amends: ADR-0008 (which lanes a landing push exercises)
Preserves: ADR-0008 landing mechanics, exact-SHA CI, the `Full CI` required check,
the verified deploy smoke and rollback

## Context

ADR-0008 runs the full required job set on every `trunk-candidate/**` push and again
on the `main` push that the landing fast-forward produces. Pull requests are path
filtered lane by lane, but the landing path was not.

Most lanes run on Linux runners, which are plentiful. Four do not: the iOS app and
the Mac app (macOS), and the CLI's darwin and Windows targets. Over 14 hours on
2026-10-15 those runners spent about 3,100 minutes:

| Event | macOS minutes |
| --- | --- |
| `trunk-candidate/**` push | ~1,350 |
| `main` push | ~970 |
| pull request | ~780 |

Every candidate re-ran the native lanes, even when it touched no Swift, Rust or CLI
code. The `main` push then repeated the same work on a tree the candidate run had
already verified. Concurrent landings filled the macOS concurrency limit and queued
everything behind them. The owner asked to run these lanes less often:
"Нам надо еще как-то concurrency за macOS раннеры снизить" (2026-10-15).

## Decision

On the landing path, the lanes on macOS and Windows runners (`ios-app`, `macos-app`,
`cli-native`, `cli-artifacts`) are exercised by what changed:

- **`trunk-candidate/**` push**: the `changes` job diffs the candidate against its
  fork point on `main` and applies the same per-lane filter pull requests use. That
  covers `.github/` as a shared surface and `scripts/` and the `Makefile` through
  `scripts/classify_changed_scripts.py`. Every Linux lane still runs in full.
- **`main` push**: when the Actions API shows a successful `trunk-candidate/**` CI
  run of the same SHA, the native lanes stay idle, because that run already
  verified the identical tree. A merged pull request has no candidate run and is
  verified in full, as is any push the lookup cannot vouch for.
- **Nightly (`schedule`, 02:41 UTC, on `main`)**: the native lanes run regardless of
  the diff, and the Linux lanes and the mutation scope stay idle. A new Xcode, a
  runner image or a toolchain change that breaks unchanged native code shows up
  within a day. The landing and TestFlight workflows act only on `push` runs, so
  the nightly run never lands or ships anything.

Filtered lanes still run and succeed without doing work, so `Full CI` never sees a
skipped job. Every branch of the decision fails toward running more.

## Consequences

- A landing that touches no native input no longer waits on macOS runners, and the
  duplicate `main` pass is gone. Together that is roughly half of the measured macOS
  minutes.
- Native breakage that has no input in the diff (an image or toolchain change) is
  caught by the nightly run rather than by the landing that happened to meet it.
  Until then it can sit on `main` for up to a day, and the nightly failure is the
  signal to fix it.
- Exact-SHA CI still gates every landing. A native lane is idle on it only when
  none of that lane's inputs changed since the fork point on `main`.
