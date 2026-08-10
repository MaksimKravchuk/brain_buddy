# ADR-0004: Start mutation testing with report-only deterministic-core evidence

Date: 2026-07-14
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0001, Quality Spine P7

## Context

Mutation testing is useful only when a failing mutant represents a missing assertion in code
whose behavior is deterministic and locally reproducible. BrainBuddy's tree, version, and
relation services and their file-backed repositories meet that condition: their inputs and
persistence are controlled by pytest fixtures, and their invariants have focused unit and
property tests.

The provider/LLM layer, asynchronous orchestration, network integrations, filesystem
failures outside the fixture root, and browser/API end-to-end paths do not currently meet that
condition. Mutating those boundaries would conflate a survivor with provider behavior,
scheduling, external I/O, or a non-deterministic retry. The shared `BaseRepository` is also
excluded: FastAPI constructs concrete repositories during module import, before mutmut can
associate execution with a test. Concrete tree, version, and index repository behavior remains
in scope. These are scope boundaries, not score-improving suppressions.

## Decision

The scheduled report-only campaign mutates only these modules:

- `app/services/tree_service.py`
- `app/services/version_service.py`
- `app/services/relation_service.py`
- `app/repositories/tree.py`
- `app/repositories/version.py`
- `app/repositories/index.py`

The exact allow-list and its direct regression selection are configured in `backend/pyproject.toml`.
The campaign runs the tree, relation, version, version-repository, index, and property-invariant
test modules. These 31 hermetic tests exercise the in-scope code directly. ASGI endpoint fixtures are outside this
deterministic-core boundary and cannot run under mutmut's stack-statistics instrumentation. Normal
product testing continues to run all 103 backend tests. Coverage and Allure test plugins are
disabled for the mutation campaign. It does not alter normal product-test reporting.

Each nightly run retains for 30 days:

- raw mutmut state (`mutants/`), including per-mutant outcomes;
- machine-readable CI/CD mutation statistics;
- complete `mutmut results --all` survivor output and the concise summary;
- a separate Allure Report 3 evidence artifact.

The Allure entry is explicitly named as report-only mutation campaign evidence, has `unknown`
status, and is tagged `mutation-testing` and `report-only`. It attaches the summary and
survivor files, but does not present individual mutation outcomes as ordinary product tests.

The nightly workflow is intentionally not triggered by `pull_request` or `push`. A runner
failure still fails the nightly so missing evidence cannot appear green; surviving mutants and
score changes are evidence to investigate, not a blocking product-test result during this
calibration period.

## Promotion to a blocking pull-request gate

Do not add the blocking gate until two consecutive scheduled runs complete successfully and
both retain complete artifacts. Before promotion, record their run URLs, the non-zero mutant
count, and a mutation score of at least 95% for this unchanged allow-list.

**Promoted on 2026-08-10.** The score half of the precondition had been asserted twice
without being measured; measured directly it was 94.81% (1279 killed, 70 survived, 1 timeout
of 1350 mutants) — below the bar. After the survivors were worked down the same unchanged
allow-list scored **97.92% (1319 killed, 28 survived of 1347 mutants)**, reproducible with
`make mutation-gate-backend`. ADR-0011 records the measurement and the disposition of every
survivor. The gate is the `mutation-gate` and `mutation-base` jobs in
`.github/workflows/ci.yml`.

The subsequent gate must:

1. run only when a pull request changes a file in the allow-list;
2. compare the PR's scoped result to the base revision using the same mutmut configuration;
3. fail below 95% and fail when no mutants were checked;
4. upload the same raw state, statistics, summary, survivors, and clearly-labelled Allure
   evidence even on failure;
5. keep this allow-list unchanged unless an ADR gives a behavioral reason for a boundary change.

Requirement 1 is met for pull requests, and deliberately exceeded on the landing path: a push
to `main` or `trunk-candidate/**` measures the whole allow-list, because SHIP/SHOW changes
land without a pull request (ADR-0008) and scoping that push to a diff would leave most of
delivery ungated. Requirement 2 is met by measuring the base revision in its own job, which
is what keeps `pip install -e` pointed at one checkout per measurement; a single job doing
both can run the base's tests against the head's code and report a green comparison that
means nothing. `scripts/check_gate_integrity.py` now guards `scripts/mutation_gate.py`, with
non-waivable invariants on the 95% constant, the zero-mutants rule, and the base comparison,
so requirement 3 cannot be softened in silence.

## Consequences

- Mutation score is initially observable evidence rather than a gate that can interrupt normal
  delivery before its stability is known.
- Survivors must be inspected and either killed with focused regression/property tests or
  documented as an explicitly justified non-behavioral mutation; broad exclusions are not an
  acceptable remedy.
- Four constructors use a line-level `# pragma: no mutate block` only: `TreeService`,
  `VersionService`, `RelationService`, and `IndexRepository`. Mutmut's signature mutations in
  these constructors alter annotations or initial local assignment syntax without changing the
  concrete dependency values each constructor stores. They have no externally observable
  deterministic-core behavior to assert, so the scope keeps the constructor bodies and every
  operational method mutable while excluding only those signature blocks.
- A later pull-request gate has a measurable calibration prerequisite instead of an arbitrary
  threshold.

## Alternatives considered

### Mutate all backend modules immediately

Rejected. This would mix deterministic core behavior with provider, async, and external-I/O
noise and reward exclusion changes rather than better tests.

### Block pull requests on the first mutation run

Rejected. The score and execution stability are unknown; two retained nightly baselines are
needed before score enforcement can be trusted.

### Publish mutation cases as normal Allure product tests

Rejected. Mutation outcomes are quality evidence about test strength, not user-facing product
behavior. They receive a distinct report-only evidence entry instead.

## Verification

`python3 scripts/validate_ci_artifacts.py mutation-workflow --workflow
.github/workflows/mutation-quality.yml` verifies the workflow's scheduling, report-only event
policy, explicit scope, mutmut commands, and retained evidence artifacts. The first manual or
scheduled run must be inspected with `mutmut results --all` before any score claim.
