# ADR-0015: Give the mobile client a deterministic-core mutation scope

Date: 2026-08-10
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0004, ADR-0006, ADR-0011, ADR-0013

## Context

ADR-0004 established what a trustworthy mutation campaign looks like here: a
fixed allow-list of deterministic modules, report-only until calibrated, whole
evidence retained, and survivors either killed by a focused test or documented
as non-behavioral. ADR-0011 split scope into an observed tier (measured
nightly) and an enforced tier (allowed to block a pull request).

Both ADRs are about the backend. The mobile client had no mutation testing at
all, and until recently it had no meaningful test suite either: 13.76%
statement coverage, with a coverage floor set to exactly that. Its highest-risk
logic is the code that has to agree, byte for byte, with a server it cannot
see:

- `src/braindump/manifest.ts` must produce the same `manifest_hash` as
  `backend/app/workflows/voice_brain_dump/service.py::_brain_dump_manifest_hash`.
  A divergence rejects every seal.
- `src/braindump/uploader.ts` and `src/braindump/machine.ts` implement the
  chunk protocol: strictly sequential numbers, per-chunk digests, and a chunk
  size chosen to stay under the production proxy's 1 MiB body cap.
- `src/lifecycle/guards.ts` mirrors ADR-0006 — the UI must never offer a
  transition the server would reject.
- `src/config/serverUrl.ts` decides which host the app talks to at all.

Raising line coverage on those modules to 100% did not, by itself, say the
tests would notice a change. The first campaign over this scope proved it:
**276 killed, 23 survived, 4 uncovered — 91.35%**. Among the survivors were
every rejection reason in `guards.ts` (the tests asserted `ok === false` and
never the sentence the user reads), the whole of `processingStageLabel`'s
`fast_processing` and default arms, and the sort in `manifestHash` — that last
one meaning an out-of-order chunk echo from the server would have hashed
differently without a single test failing.

## Decision

The mobile client gets its own **observed** mutation scope, mutated by the
nightly report-only campaign:

- `src/braindump/machine.ts`
- `src/braindump/manifest.ts`
- `src/braindump/uploader.ts`
- `src/braindump/waveform.ts`
- `src/lifecycle/guards.ts`
- `src/config/serverUrl.ts`

The allow-list lives in `mobile/stryker.config.json`, which is the file the
campaign actually obeys, and `scripts/validate_ci_artifacts.py
mutation-workflow` parses that `mutate` array and requires it to match this
ADR's list exactly — narrowing it *or* widening it fails CI. The workflow's
header comment names the same modules, but it only documents the scope; an
earlier revision of this validator read the comment alone, which meant the
config could be narrowed silently while the comment still claimed otherwise.

Out of scope, for the same reason ASGI fixtures are out of the backend's:
React components and screens, the hooks that drive them, and the device
boundaries (`expo-audio`, `expo-file-system`, `expo-crypto`, `expo-router`).
They are covered by product tests — 95% statements across `mobile/src` — but a
survivor there would describe the test harness's stand-ins as much as the
product, which is not a number worth publishing.

The enforced tier stays **empty for mobile**. The campaign runs nightly and on
manual dispatch, never on `pull_request` or `push`, and a runner failure fails
the job so missing evidence cannot look green.

### Measured

After killing the survivors, on 2026-08-10, over this exact list:

**308 killed of 310 checked — 99.35%.**

Per file: `manifest.ts`, `uploader.ts`, `waveform.ts`, `serverUrl.ts` and
`guards.ts` at 100%; `machine.ts` at 98.23%.

### The two remaining survivors

Both are the same non-behavioral mutation of `planChunks`'s guard, and neither
is killable:

```ts
if (!Number.isFinite(totalBytes) || totalBytes <= 0) {
  return [];
}
```

Mutating `totalBytes <= 0` to `false`, or to `totalBytes < 0`, changes nothing
observable: the loop below is `while (offset < totalBytes)`, which already
produces an empty plan for zero and for negative sizes. The guard is kept
because it states the precondition where a reader looks for it, and because
`!Number.isFinite` genuinely matters — without it, `Infinity` loops forever.
This is documented rather than excluded, as ADR-0004 requires.

### Promotion to a blocking gate

Same bar as ADR-0004, and it is deliberately not taken here on the strength of
one local run: two consecutive successful scheduled runs retaining complete
artifacts, with a recorded score of at least 95% for an unchanged allow-list.
Promotion then means setting `thresholds.break` to 95 in
`mobile/stryker.config.json` and running the campaign on pull requests that
touch a file in the allow-list — not widening the list.

## Consequences

- The wire-protocol code the mobile client cannot verify against a live server
  is now measured on whether breaking it would be noticed, not on whether it
  was executed.
- Two real defects surfaced while killing survivors and are fixed in the same
  change: `"Only open tasks can be ${action}d."` rendered as "canceld", and
  `manifestHash` had no test that would notice its sort disappearing.
- The nightly job costs about five and a half minutes. It runs in parallel with
  the backend campaign and shares its report-only policy, so neither can
  interrupt delivery.
- The mobile score is published per-tier and separately from the backend's. A
  single repository-wide number would average scopes calibrated against
  different constraints and mean nothing, exactly as ADR-0011 concluded.

## Alternatives considered

### Mutate all of `mobile/src`

Rejected. The screens' tests run against stand-ins for the recorder, the file
system and the navigator. A surviving mutant in a screen would as often
describe a gap in the harness as a gap in the product, and the pressure it
creates is to assert on the stand-ins.

### Skip mutation testing and keep raising the coverage floor

Rejected, and the campaign is the argument: `guards.ts` was at 100% line
coverage while every rejection message in it could be emptied without failing a
test. Coverage records that a line executed; only mutation records that
breaking it would be noticed.

### Block pull requests immediately, since the score already clears 95%

Rejected. The score clears the bar on one machine, once. ADR-0004 asks for two
consecutive scheduled runs because the property being established is stability,
not just the number, and nothing about a new runner has been observed yet.

## Verification

`python3 scripts/validate_ci_artifacts.py mutation-workflow --workflow
.github/workflows/mutation-quality.yml --frontend-stryker-config
frontend/stryker.config.json --mobile-stryker-config
mobile/stryker.config.json` checks that the workflow still runs every campaign,
keeps the report-only event policy, retains the evidence for 30 days, and that
each Stryker config's `mutate` array is exactly the scope its ADR fixed.
`make mutation-mobile` reproduces the campaign locally and writes the same
summary and survivor list the nightly uploads.
