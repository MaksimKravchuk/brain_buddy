# ADR-0014: Hybrid reviewer fallback with recorded degradation

- **Status**: Accepted
- **Date**: 2026-08-10
- **Amends**: ADR-0012 (risk classes, escalation, gate integrity), specifically
  its "A de-correlated panel" section — does not replace it
- **Relates to**: ADR-0011 (portable spec review stage)

## Context

ADR-0012 de-correlated the panel by moving `architecture-consistency` from
`codex/gpt-5.6-sol` to `claude/opus`, and recorded as a side benefit that three
of five lenses then run without the `codex` CLI, "which is what a single-runtime
machine actually has". That side benefit is real and it is not enough. It made
the panel *cheaper* on a single-runtime machine. It did not make it *runnable*
there.

Two lenses still shell out to `codex exec`: `requirements-consistency` and
`testability-evidence`. Both name `"integration": "codex"` in `ROLE_CONFIGS`,
so `build_review_command()` returns a `codex exec` argv for them.
`run_review()` checked `shutil.which(command[0]) is None` *before* spawning
anything and raised `ReviewError` when the binary was absent. No
`reviews/<role>.json` was written. `summarize()` walks `STANDARD_ROLES`, finds
those two files missing, and appends both to `missing`. `aggregate_reviews()`
sees a non-empty `missing_roles` and returns `escalated`.

Follow that chain to the end and state the result plainly: **on a machine
without the `codex` CLI, no campaign can ever reach `approved`.** Not "usually
escalates" — never approves, for any feature, however clean the artifacts. The
machine this record was written on has `claude` on `PATH` and no `codex`.

That is correct fail-closed behaviour, and it is also useless. ADR-0012
introduced `escalated` so that an incomplete campaign became an auditable fact
instead of a stack trace someone could rerun away. A gate that returns the same
auditable fact on every run, for reasons that have nothing to do with the
artifacts under review, is not a signal — it is a constant, and people stop
reading constants. The failure mode ADR-0012 warns about is a gate that looks
stricter while being weaker; a permanently escalated gate is that same shape,
arrived at by accident rather than by edit.

Two supporting facts, both checkable in the tree as this was written:
`.specify/workflows/runs/` does not exist, and `specs/` stops at
`005-multilingual-voice-brain-dump`. The pipeline these gates protect has never
been run end to end. The gate is not failing in production; it has no
production yet. Fixing runnability before the first real campaign costs a
change to two config entries. Discovering it during one costs the campaign.

## Decision

A hybrid fallback with recorded degradation.

### A fallback for the codex lenses, and only for absence

`requirements-consistency` and `testability-evidence` gain a `fallback` in
`ROLE_CONFIGS` naming `claude` / `sonnet`. Runtime selection moves out of
`run_review()` into `resolve_oracle()`, which resolves an integration to its
executable through a new `INTEGRATION_CLI` map and returns both the effective
config and the provenance record. `build_review_command()` takes that config
rather than always reading `ROLE_CONFIGS` itself. Four rules govern it:

- Primary CLI present — the lens runs as configured, as before.
- Primary CLI absent, fallback defined and installed — the lens runs on the
  fallback.
- Primary CLI absent, no fallback defined — still raises. Unchanged behaviour
  for every role that does not opt in.
- Primary CLI present but **failing** — a non-zero exit still raises, and is
  never retried on the fallback.

The last rule is the one worth defending. Absence and failure are different in
exactly the way ADR-0012 already distinguishes a missing review from a
malformed one: a missing reviewer is a gap, and a gap can legitimately be
filled by a different oracle; a failing reviewer is a defect in evidence that
*was produced*, and quietly substituting another model for it hides the
breakage rather than routing around it. A `codex` that is installed and dies on
this repository is information about the repository or the reviewer, and it
should surface as a failure, not be papered over by sonnet.

Fail-closed is preserved at the bottom of the chain: when neither the primary
CLI nor its fallback is installed, `resolve_oracle()` raises naming both.

### The `oracle` block is written by the harness, never by the reviewer

Every review file records which oracle actually ran:

```json
"oracle": {
  "integration": "claude",
  "model": "sonnet",
  "degraded": true,
  "reason": "the codex CLI is not installed",
  "configured_integration": "codex",
  "configured_model": "gpt-5.6-sol"
}
```

On the normal path the block carries the configured integration and model with
`"degraded": false` and nothing else. The degraded path records what was
configured alongside what ran, so the summary shows the substitution rather
than just its result.

This is provenance, not reviewer content, and the distinction carries the
weight of the whole mechanism. `validate_review()` does not pass its input
through. It builds and returns a fresh dict containing exactly `role`,
`verdict`, `summary`, `reviewed_files`, `findings` and `product_decisions`, and
discards every other key the model emitted. (`review.schema.json` also sets
`"additionalProperties": false`, so a well-behaved CLI would not emit one — but
the schema is the reviewer's contract, and a gate must not depend on the thing
it is judging honouring its contract.) The harness attaches the `oracle` block
after validation returns.

The consequence is that a reviewer cannot author its own provenance. It cannot
claim to be opus while running as sonnet, and it cannot mark itself
undegraded. Were `oracle` instead a field in the review schema, it would be
exactly as trustworthy as the `human_signoff` boolean ADR-0012 removed: a value
supplied by the actor it describes, about itself, on the one axis where
self-report is worthless.

The same property has a round-trip cost that is easy to get wrong.
`summarize()` re-validates each persisted review through `validate_review()`,
so the block written to disk is dropped on the way back in unless it is carried
across deliberately from the raw payload. Without that step degradation would
survive to the review file and vanish from the artifact whose whole job is to
report it.

### `summarize()` reports degradation in the human field, not only the JSON

`planning-review-summary.json` gains:

- `degraded_lenses` — the roles that ran on a fallback.
- `panel_correlated` — true when one oracle holds a strict majority of the
  lenses whose provenance is known.
- `panel_oracles` — the `integration/model` histogram the majority is computed
  from, so the claim can be checked rather than trusted.
- `oracle_unknown_lenses` — reviews carrying no `oracle` block at all. An
  absent block is unknown provenance, not proof the lens ran as configured, and
  those lenses are excluded from the correlation denominator instead of
  counted as clean. Treating silence as evidence of safety is the exact defect
  ADR-0012 removed from risk derivation.

Each reviewer entry in `reviewers` carries its own `oracle`, and
`aggregate_reviews()` appends a panel note to `architect_action` naming the
degraded lenses and saying plainly that their agreement with the other Claude
lenses is weaker corroboration than it looks. A fact that lives only in a JSON
key is a fact read once, by whoever wrote it. `architect_action` is the
sentence a human actually reads, so degradation has to appear there too.

### The gate status is deliberately unchanged by degradation

A degraded campaign may reach `approved`.

This is the crux of the record, so it is stated rather than buried: blocking on
degradation produces, on a machine without `codex`, precisely the permanently
`escalated` gate this ADR exists to escape. Same outcome, more machinery, and a
new field to explain it. The mechanism here is visibility, not blocking.
Whether a degraded panel is good enough for a particular change is a judgement,
and the summary now carries the facts that judgement needs.

Everything ADR-0012 gave `escalated` still fires: artifact drift, missing
mandatory evidence, an unsigned high-risk campaign. A fallback that runs and
still produces no review is missing evidence like any other.

### The substitution cannot become silent

`check_gate_integrity.py` gains four non-waivable invariants over
`scripts/spec_kit_planning_review.py`: `resolve_oracle()` marks a fallback
`"degraded": True`; the harness stamps `review["oracle"]`; `summarize()` writes
`degraded_lenses`; and a non-zero reviewer exit still raises rather than
falling through. Each carries a mutation test in the pattern of the existing
`test_*_is_caught` cases, so an invariant cannot rot into a no-op.

Without them the cheapest imaginable future edit — keep the fallback, drop the
`oracle` write — silently converts this decision into rejected alternative (c),
in a diff nobody would flag. The guard cannot prevent that edit; it removes the
word *silently*, which is the only thing it has ever claimed to do. Both files
involved are already in the twelve-file hash manifest, so the change must be
re-recorded in the same commit as well.

### The guard was not running in CI

Writing those invariants surfaced a defect in ADR-0012's own delivery, and it
is recorded here rather than quietly patched because it is the same failure
shape that record is about.

ADR-0012 added two invariants asserting that `make check-specs` runs
`check_gate_integrity.py` and `check_speckit_manifests.py`. Both hold. Neither
says anything about whether *anything runs `check-specs`* — and the CI
`spec-kit` job ran only `test_check_spec_kit_specs.py` and
`check_spec_kit_specs.py`. The gate-integrity guard, all of its invariants and
the preserved-override check were absent from every build. An actor could edit
`aggregate_reviews`, re-record the hash manifest, and watch CI go green: the
whole two-layer mechanism was reachable only by a human choosing to run
`make check-specs` locally.

Guarding the Makefile without guarding its caller is a guard with no reader.
The CI job now runs both validators and all four gate suites, and two further
invariants assert that it keeps doing so — over `.github/workflows/ci.yml`
directly, because the property that matters is that CI invokes the guard, not
that some `make` target mentions it.

Those two are deliberately invariants without a hash entry. `ci.yml` changes
constantly for unrelated reasons, and adding it to the manifest would spend the
friction budget — the thing that makes a manifest change visible in review — on
routine noise. Twenty-two invariants now, twelve hashed files still.

### Why sonnet and not opus

The opus seats belong to `architecture-consistency` and
`privacy-consent-security`, the lenses that carry dedicated rubric files under
`.claude/agents/` — `build_prompt()` injects the "apply the review rubric in
.claude/agents/<name>.md verbatim" instruction only for roles whose config
names an `agent`. The two codex lenses have no such file; they run on focus
text alone. Promoting an unrubriced fallback into the same tier as the lenses
running as configured dilutes exactly the seats that are working.

With both fallbacks active, a medium-risk panel is opus x2 and sonnet x3, so
sonnet holds a strict majority and `panel_correlated` reports `true`.

Be explicit that the model choice was not contorted to dodge the metric. There
are two review-grade Claude tiers, so *any* all-Claude panel of five has a
majority model — the choice was never between a correlated panel and an
uncorrelated one, only between reporting the correlation and not reporting it.
Reporting it honestly is the point of the field.

### The honest limit

ADR-0012 set the precedent of stating what a mechanism does not buy, and this
one needs it more than most.

Opus versus sonnet is the same provider and the same model lineage. It is far
weaker independence than codex versus claude. Correlated blind spots across
tiers of one family are the normal case, not the exception, and no amount of
tier-splitting makes them two opinions.

ADR-0012's claim that the panel "spans two providers" holds for the
*configured* panel and is false for a *degraded* one. That sentence is not
retracted — it was true of what it described — but it must not be read as
covering the state this record introduces. The `degraded` flag is the
mechanism; the opus/sonnet split is a mitigation, not a restoration of what was
lost.

A campaign that genuinely requires independent oracles needs the `codex` CLI
present. The difference now is that the summary tells you whether it was.

## Corrections made during review of this record

Every one is a defect in this record's own first implementation, found by an
independent adversarial review before it landed. They are listed rather than
quietly folded in, because ADR-0012 established that pattern and because each
is another instance of the failure mode both records are about: a mechanism
that looks stricter while being weaker.

### The correlation signal inverted at the one class that depends on it

`panel_correlated` used a strict majority, `max(counts) > known // 2`. A
fully degraded high-risk panel is six lenses — sonnet ×3, opus ×2, fable ×1 —
and `3 > 3` is false. So a panel that had collapsed to a single provider
reported "not correlated", *the same value a genuinely cross-provider panel
gets*, at precisely the risk class where ADR-0012 scopes the human sign-off as
the increment on top of an uncorrelated mechanism. It fired only at `medium`,
where nothing turns on it.

The majority is now rounded up. More importantly, model-majority was the wrong
question: a fallback only ever moves lenses onto **one provider**, so
`single_provider_panel` and a `panel_providers` histogram were added. They have
no arithmetic edge — true for every fully degraded campaign at every risk
class — and `single_provider_panel` appears in `architect_action` alongside the
degradation note.

### Unknown provenance was silent, and the repository told you to create it

`oracle_unknown_lenses` was written to the summary and nowhere else: no note in
`architect_action`, no effect on anything. Meanwhile `speckit-review/SKILL.md`
still instructed the operator to hand-write review JSON when codex was absent,
and `docs/spec-kit-workflow.md` still described the pre-fallback behaviour.
Following the repository's own documented procedure produced five hand-written
reviews, no provenance, and a summary reporting a clean uncorrelated panel.

Both documents were corrected, `unknown_oracle_roles` now produces a note as
loud as degradation's, and `panel_correlated` becomes `null` — not `false` —
whenever any provenance is missing. Unmeasured and measured-and-diverse must
not share a value.

### The report would have become *less* honest than before the change

`render_feature_report.py` derived "lenses that did not run" from the roles
present in the summary. Before the fallback, a codex-less campaign rendered a
warning naming two lenses. After it, all five produce reviews, so the same
machine rendered "All five standard lenses ran." and nothing else.

Worse, this section originally argued that not blocking is acceptable because
"`architect_action` is the sentence a human actually reads" — and nothing read
`architect_action`. The justification rested on a consumer that did not exist.
The renderer now surfaces degradation, provenance, the histograms, stale
reviews and the architect's next action, with tests asserting the rendered
text; a clean panel still renders exactly as before.

That fix created its own gap, caught in the same review. Four invariants
assert `summarize()` *writes* these facts and none asserted anything *reads*
them — but once the gate trades blocking for visibility, the renderer is
load-bearing for the trade, and the cheapest edit that undoes this decision is
to keep the write and drop the render. An invariant now requires
`section_review()` to read all three provenance keys, with a mutation test.
Like the CI ones it is an invariant without a hash entry: the file changes for
ordinary reporting reasons.

### Four of the five new invariants were satisfiable by code that does not work

The anchored patterns used an unbounded DOTALL `.*?`, which runs to the end of
the file and terminates on an identical token anywhere later. Deleting
`run_review`'s own `raise ReviewError` left the invariant matching
`preflight`'s, three hundred lines on. That is the exact hazard flagged in a
comment twenty lines above these invariants, reintroduced while writing them.

All patterns are now right-bounded to the enclosing function. A `MustNotMatch`
guards the call site, since a correct resolver can have its verdict overwritten
one line later, and a `MustMatch` asserts both codex lenses keep a fallback at
all.

Regexes still cannot catch a dataflow defect: flip the fallback's marker to
`False` and plant the literal `{"degraded": True}` in a comment below it, and
every pattern is satisfied while nothing is ever degraded. So the text layer is
no longer carrying that weight alone — `BehaviouralMutationTests` writes the
mutant to disk, imports it, simulates a claude-only PATH, runs a whole campaign
and asks the summary what it recorded. The planted-comment test asserts *both*
that the invariants pass and that the behaviour is wrong, which is the argument
for the class stated as an assertion.

### Re-running preflight laundered stale reviews past the drift escalation

ADR-0012 correction #3 made "editing the spec invalidates the approval" true by
recomputing the digest. But `preflight` rewrites `planning-context.json`
including that digest and never clears `reviews/`. Editing the spec, re-running
preflight on the same run id, and summarizing therefore reported no drift over
five verdicts describing the original content — the escalation turned off by
re-running the step that produces its baseline.

Each review's `oracle` now stamps the digest it was produced against, and any
review disagreeing with the recomputed digest is named in `stale_reviews` and
escalates. That is strictly stronger than the run-level check and also catches
a panel of mixed vintage when a single lens is rerun. Pre-existing, but this
record makes the run directory something you return to, so it became
load-bearing here.

### `build_review_command` was a second entry point with no presence check

Moving the `shutil.which` guard into `resolve_oracle` left
`build_review_command(config=None)` defaulting to `ROLE_CONFIGS[role]` — a
caller could get a `codex exec` argv with no availability check and no
provenance, which is the pre-fallback behaviour with the guard removed. It
existed only to keep two tests on the old signature. `config` is now required
and the tests pass it.

### Provenance is only as strong as PATH

The record claims a reviewer cannot author its own provenance, and that holds.
It does not follow that provenance is trustworthy. `resolve_oracle` decides
from `shutil.which`, and any actor that can run a shell controls PATH: narrow
it and a lens degrades on demand; shim `codex` to exec `claude` and the oracle
reports `degraded: false` with no configured/actual pair to contradict it.

The oracle now records the resolved absolute path, which makes the two cases
distinguishable after the fact rather than asserted from configuration. It does
not close the hole. Nothing at this layer can — it is the same absence of
cryptographic identity ADR-0012 recorded for the sign-off — and combined with
degradation having no effect on status, an actor that prefers its own model
family can arrange to be reviewed by it. The mitigation is that the arrangement
is now visible in the summary, the report and the handoff.

### Two keys for one fact, and three tests nothing ran

`aggregate_reviews` returned `degraded_reviewers` while `summarize` wrote
`degraded_lenses`, same content, and the invariant guarded one while the tests
asserted the other. One key now.

Separately, wiring the guard into CI turned up two more orphans of the same
kind: the report renderer's tests were written and never referenced, and
`scripts/test_validate_backend_coverage.py` was referenced by nothing at all —
not the Makefile, not CI, not another script. Three instances of "a test
nothing runs" in one change is a class, not a coincidence, so a structural test
now asserts that every `scripts/test_*.py` is named by some make target.

### The same correction, missed one field over

Found not during authoring but by the repository's automated reviewer on the
open pull request, which makes it the tenth defect in this change and the
sixth round of review to find one.

`single_provider_panel` was `len(provider_counts) == 1 and known_oracles > 1`.
The `known_oracles > 1` guard is right — one lens carrying provenance is not
evidence a panel collapsed onto one vendor — but routing that insufficiency
into `False` put it in the same bucket as a panel measured and found diverse.
Two distinct states reached it: one lens with provenance, and no lens with
any, the latter being the ordinary shape of a hand-written campaign. The
report then rendered `False` as "more than one provider is represented", so a
panel nobody measured read as a panel measured and found independent, with a
histogram directly beneath it listing one provider or none.

The correction is the one already made to `panel_correlated` fifteen lines
away, and the comment there states the principle in general terms — "an
unmeasured panel and a measured-and-diverse one must not share a value" —
while being applied to a single field. `single_provider_panel` is now
`bool | None`, `None` below two known oracles, and the renderer prints the
third state rather than falling silent on it. Silence would have been the
subtler version of the same defect: an absent line invites the same inference
as a false one.

That the fix for a "false reads as verified" defect itself shipped a "false
reads as verified" defect, in the adjacent field, is the strongest evidence in
this record for the review posture it argues for.

## Consequences

**Positive.** The conveyor can run to completion, including to `approved`, on a
single-runtime machine — which is the machine the repository actually has.
Degradation is auditable rather than invisible, recorded per review and
aggregated per campaign, in a field the reviewer cannot write. The distinction
between a reviewer that is absent and one that failed is now explicit in the
code rather than collapsed into a single `ReviewError`.

**Costs, accepted.** A degraded panel is a genuinely weaker panel, and nothing
in this record prevents someone reading `degraded_lenses`, shrugging, and
landing anyway. That is the deliberate trade for not blocking, and it is worth
naming rather than implying the flag does more work than it does.

`panel_correlated` is computed from which oracle ran each lens, never from any
measurement of what the reviewers actually said. It detects correlated
*oracles*, not correlated *findings*: five reviewers on five providers all
agreeing on a wrong reading of the spec is invisible to it, and always was.

It is also coarse in a way worth recording. A fully degraded high-risk campaign
is six lenses — sonnet on three, opus on two, fable on one — and three of six
is not a strict majority, so `panel_correlated` reports `false` while
`degraded_lenses` still lists both fallbacks. The two fields answer different
questions and neither subsumes the other; read both.

Adding `fallback` extends the "adding or removing a role touches five places
atomically" hazard ADR-0011 recorded. The fallback lives only in `ROLE_CONFIGS`
and is invisible to `workflow.yml`, so a role's declared integration no longer
predicts what will actually run — the summary is now the only honest answer to
"which model reviewed this?".

## Alternatives rejected

**Require the `codex` CLI everywhere.** Cleanest on paper and it preserves real
cross-provider independence. It also makes the review stage non-portable, which
directly contradicts ADR-0011's decision that the campaign runs "in Claude Code
or Codex, with or without a managed outcome". A stage that mandates a second
vendor's CLI is a managed-outcome overlay again, wearing a different name.

**Keep failing closed and accept permanent escalation.** Defensible if the gate
were occasionally escalating for artifact reasons. It escalates unconditionally
on the available runtime, for every feature, forever. An `escalated` verdict
that carries no information about the artifacts trains readers to route around
the gate, and a gate people route around is worse than one that reports an
honest weaker result.

**Fall back silently without recording.** The panel would run and the summary
would be a lie by omission — it would state a status computed from evidence it
misrepresents, and ADR-0012's "the panel spans two providers" claim would
quietly become false with nothing in the output to say so. Laundering a
degraded campaign into a clean-looking one is the same defect as
`aggregate_reviews` laundering `changes-required` into `approved`, which
ADR-0011 was written to fix.

**Block the gate on any degradation.** Identical in effect to accepting
permanent escalation: on a machine without `codex` every campaign blocks. It
costs an extra field and a branch to arrive at the same dead end, and it
disguises a runtime-availability problem as a quality verdict.

**Shrink the panel to only the lenses that can run.** Three lenses would pass
cleanly with no missing evidence and no degradation to report — which is the
problem. `requirements-consistency` and `testability-evidence` are in
`STANDARD_ROLES` and in the role enum, and `aggregate_reviews()` already treats
any configured lens that produced no review as missing mandatory evidence.
Dropping them when inconvenient converts a mandatory check into an optional one
based on what happens to be installed — the self-weakening
`check_gate_integrity.py` was built to catch, done deliberately.
