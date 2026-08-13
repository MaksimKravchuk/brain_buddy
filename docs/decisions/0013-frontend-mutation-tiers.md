# ADR-0013: Extend the observed and enforced mutation tiers to the frontend

- **Status**: Accepted
- **Date**: 2026-08-10
- **Extends**: ADR-0004 (deterministic-core mutation policy), ADR-0016
  (observed and enforced mutation tiers) — neither is replaced
- **Relates to**: ADR-0008 (verified trunk serial landing)

## Context

The backend has had mutation evidence since ADR-0004 and a two-tier scope since
ADR-0016. The frontend had none. Its only quality number was line coverage, and
that number turned out to be reporting on a subset of the code without saying
so: four modules — `AppShell.tsx`, `AppRoutes.tsx`, `TaskListPage.tsx` and
`TaskDetailPanel.tsx`, 2,385 lines between them — carried
`/* istanbul ignore file */`. An excluded file is not reported as uncovered; it
leaves the measurement entirely. The floor read 97.37% while a third of the
source was unmeasured.

That is the same failure ADR-0016 recorded on the backend, in a different
disguise. There the predicates were *covered and unverified*; here the modules
were *excluded and presumed verified*. Both times the number was green and the
question it appeared to answer had not been asked.

Removing the four pragmas and covering what they hid brought the frontend to
98.77% statements and 97.56% branches over the whole tree. That fixes the
measurement, not the deeper problem: coverage still only records that a line
ran. The frontend carries logic where that distinction is expensive —
`smartAdd.ts` parses user input into task classifications, `client.ts` builds
every request the product sends, `error.ts` decides what a user is told when
something fails.

## Decision

The frontend gets the same two tiers as the backend, measured with Stryker
(`frontend/stryker.config.json`) instead of mutmut.

**Observed scope** — mutated by the nightly report-only campaign:

- `src/api/client.ts`, `src/api/account.ts`, `src/api/auth.ts`,
  `src/api/taskHooks.ts`
- `src/features/tasks/smartAdd.ts`,
  `src/features/brain-dump/brainDumpNavigation.ts`
- `src/stores/authStore.ts`
- `src/utils/error.ts`, `src/utils/telemetry.ts`

**Enforced scope** — the tier that is allowed to gate pull requests
(`frontend/mutation-enforced-scope.txt`): the modules that clear ADR-0004's 95%
on their own —

- `src/api/auth.ts`, `src/api/client.ts`, `src/stores/authStore.ts`,
  `src/utils/error.ts`, `src/utils/telemetry.ts`

As on the backend, the gate is **built but not connected**.
`scripts/mutation_gate.py check-stryker` implements it; nothing in CI calls it.
ADR-0004's promotion rule is unchanged and unmet: two consecutive successful
scheduled runs with complete artifacts, and a recorded score of at least 95% for
an unchanged allow-list. The frontend campaign has run locally, not nightly, so
the first half of that precondition cannot be satisfied yet by construction.

Measured locally on 2026-08-10, over the scopes exactly as configured above.
The campaign instruments 1,227 mutants and takes about 15 minutes:

| module | score | killed / checked | tier |
|---|---|---|---|
| `src/stores/authStore.ts` | 100.00% | 39 / 39 | enforced |
| `src/api/client.ts` | 98.97% | 289 / 292 | enforced |
| `src/utils/error.ts` | 97.69% | 127 / 130 | enforced |
| `src/api/auth.ts` | 96.83% | 61 / 63 | enforced |
| `src/utils/telemetry.ts` | 96.30% | 26 / 27 | enforced |
| `src/features/tasks/smartAdd.ts` | 96.23% | 536 / 557 | observed |
| `src/api/taskHooks.ts` | 93.51% | 72 / 77 | observed |
| `src/api/account.ts` | 93.33% | 28 / 30 | observed |
| `src/features/brain-dump/brainDumpNavigation.ts` | 91.67% | 11 / 12 | observed |
| **enforced tier** | **98.37%** | **542 / 551** | |
| **observed tier** | **96.90%** | **1189 / 1227** | |

The starting point for the same scopes, before this work, was 84.82% enforced
and 85.27% observed. What moved it was not more coverage — every one of these
modules was already at or near 100% line coverage — but assertions about things
no test had ever named: which telemetry event a request records and whether its
duration is a subtraction, which idempotency key and HTTP verb each write
carries, whether an abort signal is forwarded, whether the auth store's logout
also ends the server session, and how Smart Add ranks a suggestion.

`smartAdd.ts` was the one module that did not clear the bar, at 92.96% with 40
survivors. Working that backlog took it to **96.23%**, and the three remedies
below split it cleanly: 11 survivors were killable by assertion, 8 lived in code
no reachable input could construct, and 21 are equivalent.

The 11 assertions were not obscure. The suggestion cap of eight is written into
003-FR-004 and into the grammar contract, and deleting `.slice(0, 8)` was
invisible to every test. `name-char` is defined as Unicode Letter, Number, Mark
or `_`, and the suite only ever used ASCII letters. Nothing anywhere asserted
that canonical matching folds case *downwards* -- `"ß".toLocaleUpperCase()` is
`"SS"`, so folding upwards would silently resolve `#ß` onto an existing `ss`
tag, and every other comparison normalises both sides, so no test could see it.

`smartAdd.ts` **stays observed** even so. It now satisfies the score half of
ADR-0004's precondition and nothing else: the promotion rule asks for two
consecutive successful *scheduled* runs, and the nightly campaign that produces
them had not yet run when this was measured. The five modules already on the
enforced list were placed there when the tier was created and no nightly existed
at all; that bootstrap is spent, and repeating it for a sixth module one day
before real evidence arrives would be an exception, not a precedent.

### The 21 equivalent survivors in `smartAdd.ts`

Recorded so the next reader does not re-derive them. Each was checked by hand,
and they fall into five families:

| n | family | why no test can kill it |
|---|---|---|
| 4 | `^...$` anchors on `nameCharPattern` and `leftBoundaryPattern` | both regexes only ever test a single character, so the anchors cannot change a verdict |
| 7 | loop bounds in the four scanners | an out-of-range index reads `undefined`, which fails the character test that follows, so the bound never decides anything |
| 4 | injected values nothing reads back | a sparse `new Array()` indexes identically, and a mutated `kind` is only ever compared against `"tag"` |
| 2 | exact-match rank 0 versus prefix rank 1 | an exact match is always alphabetically first among prefix matches, so collapsing the ranks cannot reorder a list |
| 2 | `+` quantifiers on already-collapsed runs | whitespace is collapsed to single spaces before the second `replace`, so one-or-more and exactly-one match the same input |

The first family is the one worth naming, because it is a live temptation. The
anchors are provably redundant and deleting them would score four more kills for
nothing. They stay: weakening an assertion to move a number is the failure
ADR-0016 recorded, and a score bought that way measures nothing. The same logic
retired one deletion made while working this backlog -- `scoreEntity`'s
empty-query rank was reachable and covered, not unconstructible, so removing it
to claim two mutants was moving the number, and it was restored.

The third remedy applies to code that *cannot be constructed*, which is a
narrower claim than *cannot be observed*. Eight survivors here met it: three
dead `?? ""` fallbacks guarding reads that cannot be out of range -- two of which
Stryker reported as `NoCoverage`, which is the tool proving no test reaches the
fallback at all -- and a `refKey` parameter only ever passed `"tag"`, whose
project branch nothing could select.

**React component trees are in neither tier.** A mutant inside a component is as
likely to be caught by a DOM snapshot as by an assertion about behaviour, so the
score would measure how specific the rendering assertions are rather than
whether the tests defend the product. Component behaviour is defended by the
Vitest suites and the Playwright product E2E matrix; putting it under mutation
would produce a number that moves for reasons unrelated to test strength. This
is a scope boundary, in ADR-0004's sense, not a score-improving suppression.

Two mechanical consequences are worth stating because they are easy to get
wrong:

- **A mutant run is not a product test.** ADR-0004 disables coverage and Allure
  plugins for the backend campaign; `vite.config.ts` does the same for the
  frontend, keyed off `STRYKER_MUTATOR_WORKER`. Thousands of sandboxed runs must
  never reach the Allure report.
- **The tiers are checked for consistency.**
  `validate_ci_artifacts.py mutation-scope` fails when an enforced file is
  outside the observed scope, or when either list names a file that no longer
  exists. An enforced file the nightly never mutates would be gated on a number
  nothing produces.

## Consequences

- The frontend's deterministic logic becomes measurable on the same terms as the
  backend's, and survivors become an itemised backlog instead of an unknown.
- The nightly campaign gets longer. The observed scope is 1,227 mutants and
  takes about 15 minutes on four cores; it runs on the existing nightly schedule
  alongside the backend campaign and blocks nothing.
- Coverage can no longer be quietly narrowed:
  `validate_ci_artifacts.py coverage-suppressions` rejects file-level and range
  exclusions in `frontend/src` and `mobile/src`, and requires a written
  justification on a narrow `ignore next`.
- Three kinds of remedy are now in play for a survivor, where the backend had
  two. Kill it with a focused test; document it as equivalent; or delete the
  code it lives in. The third is more common in TypeScript than in Python: an
  unreachable default parameter or a defensive `?? ""` behind a value the types
  say cannot be null produces a mutant no test can kill, and removing it is a
  simplification the type system was already asking for. Three such changes went
  in with this ADR — a required `variant` on `Chip`, required options on
  `request()`, and a discriminated union for the sidebar project/tag commands
  that made two "is required" runtime guards unconstructible.

## Alternatives considered

### Mutate the components too

Rejected for now, and the reason is measurement quality rather than cost. Until
component specs assert behaviour rather than structure, a component mutation
score reports on the snapshot suite. Revisit when the E2E charter's behavioural
assertions are richer.

### Enforce immediately on the whole observed scope

Rejected: it is the mistake ADR-0016 already rejected on the backend. A tier
that starts blocking before it is calibrated creates pressure to weaken the
scope rather than to write assertions.

### Raise the coverage floor instead

Rejected, and the frontend now has its own receipt for why. `error.ts` was at
100% statements, 100% branches and 100% lines while 13 of its 130 mutants
survived — including a mutation that emptied the fallback message every error
toast falls back to. Coverage records that a line executed; only mutation
records that breaking it would be noticed.

## Verification

```bash
cd frontend && npm run test:mutation      # observed scope, report-only
python3 scripts/mutation_gate.py check-stryker \
  --report frontend/mutation-artifacts/mutation-report.json \
  --enforced frontend/mutation-enforced-scope.txt
python3 scripts/validate_ci_artifacts.py mutation-scope \
  --config frontend/stryker.config.json \
  --enforced frontend/mutation-enforced-scope.txt
python3 scripts/validate_ci_artifacts.py mutation-workflow \
  --workflow .github/workflows/mutation-quality.yml
```

`scripts/test_mutation_gate.py` covers the Stryker scoring rules, including the
two failure modes ADR-0004 treats as equally disqualifying: a score below the
threshold, and a run that checked no mutants at all.
