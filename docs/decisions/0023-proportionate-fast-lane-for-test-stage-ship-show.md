# ADR-0023: Proportionate fast lane for test-stage SHIP/SHOW delivery

Date: 2026-09-16
Status: Accepted by the product owner
Amends: ADR-0005 (mandatory Spec Kit scope), ADR-0008 (SHIP/SHOW evidence),
ADR-0011/0012/0014 (planning-review applicability)
Related: ADR-0010 (opt-in managed outcomes), ADR-0022 (proportionate feature flags)

## Context

BrainBuddy has only a test environment, no users, and no valuable customer data. The
verified-trunk path already preserves the safeguards that matter at this stage: an
isolated writer, exact-SHA CI, serial landing, deploy-time SHA verification,
authenticated production smoke, cleanup, and rollback.

The process around that path had accumulated duplicate gates. A bounded SHIP or SHOW
change could require the full Spec Kit campaign, a multi-lens planning review, a
separate implementation review, a separate QA lane, and an additional protected
browser acceptance after the standard authenticated production smoke. A successfully
landed and deployed exact SHA could therefore remain "not Done" because a second form
of evidence repeated a risk that another gate had already covered.

This optimizes for evidence volume rather than release confidence. At the current
product stage it delays learning without protecting real users or valuable data. The
product owner selected a balanced fast lane: one independent gate, exact-SHA CI, and
the existing deploy smoke for bounded SHIP/SHOW changes. High-risk work remains on the
full path.

## Decision

### Eligibility

The fast lane is the default for a bounded change whose paths are mechanically proven
non-ASK by ADR-0008's classifier, that is explicitly classified semantically as SHIP
or SHOW under ADR-0008, and that meets all of these conditions. The path classifier
emits `SHIP` or `ASK`; it enforces the ASK boundary and does not decide whether
non-ASK behavior is user-visible. Every user-visible behavior change is semantically
SHOW even when its paths mechanically emit `SHIP`.

- it does not touch an ASK surface: authentication/privacy, destructive data or schema,
  billing/provider credentials, CI/CD/security/infrastructure, secrets/permissions,
  or an irreversible external effect;
- it is not a significant new capability under ADR-0022;
- it does not change a cross-surface contract or persistence/schema behavior;
- it does not materially change a workflow/state-machine boundary; and
- its acceptance outcome and highest-risk failure mode can be stated and verified as
  one bounded slice.

A change that fails any condition uses the existing full path. Ambiguity escalates out
of the fast lane; it is not evidence of eligibility.

### Proportionate planning

A fast-lane change uses the repository's lightweight brief in `AGENTS.md`: accepted
outcome, non-goals, acceptance evidence, and untouched scope. It does not require a new
Spec Kit feature directory, the five-lens `/speckit-review` campaign, or an opt-in
managed Kanban outcome.

The canonical full-path triggers are: a significant new capability, a cross-surface
contract change, a persistence/schema change, a materially changed workflow/state-
machine boundary, or any ASK-class outcome. Existing feature
artifacts must still be amended when a fast-lane change alters their already-frozen
intent; the fast lane is not permission for implementation to contradict a current
spec.

### One independent post-freeze gate

The frozen fast-lane candidate SHA receives exactly one independent gate:

- choose **code review** when contract, backend, persistence, concurrency, security, or
  implementation correctness is the dominant risk;
- choose **QA** when rendered UI, interaction, browser/device behavior, accessibility,
  or the end-user journey is the dominant risk.

The gate actor must be independent of the writer and must identify the exact SHA. A SHA
change invalidates the verdict. Material mixed risk or an acceptance contract that
genuinely requires both disciplines makes the outcome ineligible for the fast lane and
moves it to the full path. If the selected actor cannot evaluate the dominant risk,
replace that gate or escalate the outcome to the full path; do not accumulate a second
fast-lane gate. The absence of a second gate is not missing fast-lane evidence.

### Verification and production acceptance

The writer runs the smallest relevant deterministic checks before freezing the
candidate. The pre-freeze receipt may mark local `writer.verify_all` as
`NOT_APPLICABLE` with a concrete justification when targeted checks passed and full
required CI will run on the exact candidate SHA; it must never record an unrun suite as
`PASS`.

Full required CI, verified-trunk landing, deploy-time SHA proof, authenticated
production smoke, cleanup, and rollback behavior remain unchanged.

For docs, tests, refactors, internal changes, and non-user-visible corrections, a green
standard production smoke completes production acceptance. Any user-visible change —
therefore semantically SHOW — additionally needs one bounded production journey proving
the changed outcome at the intended flag/audience. Verify the changed success path and the highest-risk applicable
failure or recovery state; do not require a full state matrix unless the accepted
criteria or observed risk call for it.

A separate protected-identity or browser acceptance is required only when the change
materially affects authentication, permissions, identity/cohort selection, feature-
flag exposure, browser-only behavior, or when the accepted outcome explicitly names
that journey. It is not an automatic gate after an already green authenticated smoke.

Once the selected independent gate, exact-SHA CI, landing, deployment, standard smoke,
and any applicable bounded SHOW journey are green, the change is Done. Additional
experiments or broader exploratory coverage become follow-up work unless they expose a
real release blocker.

### Safeguards retained

This decision does not weaken:

- one isolated writer per branch/worktree;
- current `origin/main` provenance and bounded diffs;
- exact-SHA evidence and invalidation after SHA drift;
- required CI, serial non-force landing, least-privilege identities, or path-risk
  classification;
- production SHA re-verification, authenticated smoke, cleanup, rollback, or feature-
  flag audience checks when applicable;
- secret, billing/account, legal/regulatory, destructive valuable-data, or other
  irreversible authority boundaries; or
- the ASK landing path.

Hermes managed outcomes remain opt-in under ADR-0010. Choosing that full managed mode
also chooses its additional lane and receipt requirements; ordinary work must not be
silently enrolled merely to recreate the ceremony this record removes.

## Consequences

Bounded SHIP/SHOW work has one planning path, one independent gate, one primary
exact-SHA candidate CI evidence run, and one release proof. UI-heavy work normally
chooses QA; correctness-heavy work normally chooses review. Large or high-risk
outcomes keep the existing full campaign.

The main trade-off is less duplicated human- or agent-generated evidence. That is
intentional: confidence comes from matching the gate to the dominant risk and retaining
the exact-SHA delivery controls, not from requiring every available gate on every
change.
