# Research: Transcript-first voice brain dump

**Feature**: `specs/015-transcript-first-brain-dump/` · **Plan**: [plan.md](plan.md) · **Date**: 2026-09-05

Phase 0 record. This is a retro feature: the Technical Context in `plan.md` has no
unknown left to research, and `spec.md` carries zero unresolved-clarification
markers. What this file records instead is every decision the feature already
rests on — the ten entries of the spec's `## Clarifications` session and the two
ADR-0002 amendments of 2026-09-05 — in the Decision / Rationale / Alternatives
form the plan template asks for, each with the record that took it. Nothing here
is new research.

## R-01 — New feature number; spec 002 stays frozen

- **Decision**: record the change as feature 015 and leave
  `specs/002-async-voice-workflows/` untouched; 015 narrows 002 US1, required
  outcome 2 and `002-SC-004` in prose, and the ADR-0002 amendment is the
  architecture record.
- **Rationale**: 002's normative files are hash-pinned as delivered history
  (`scripts/check_spec_kit_specs.py`); a material edit would invalidate the
  grandfathering and force the whole 002 pipeline to rerun for a change whose
  behaviour is already shipped.
- **Alternatives considered**: rewriting 002 in place — rejected by the founder
  («путь A»).
- **Source**: spec Clarifications, first decision; `intake.md` §4.

## R-02 — Browser preview is a transcript readout, never a task source

- **Decision**: `append_brain_dump_transcript` persists preview segments only;
  the "fast" provisional-extraction method is retired from the production path
  and `wording_changing` is no longer produced; proposals are minted only by the
  reconciler over the accurate transcript after seal.
- **Rationale**: Web Speech interim hypotheses fluctuate («Так» → «Надо» →
  «Надо купить моло» → «Купить молоко»); a proposal per fragment could not be
  retired by the reconciler (a provider `remove` is a visible conflict, an
  untouched `fast` proposal blocks commit), so the owner deleted six cards by
  hand before Save was enabled.
- **Alternatives considered**: keeping the preview lane as a task source and
  teaching the reconciler to retire its drafts — rejected because the substrate
  deliberately makes provider removals visible conflicts, and the owner's
  numbered ask was that raw text be a status, not tasks.
- **Source**: ADR-0002, 2026-09-05 amendment; `intake.md` §1; FR-001, FR-002.

## R-03 — GTD next-action titles from prompt v3 plus server-side guards

- **Decision**: prompt `brain-dump-reconciler-v3` (verb first, language spoken,
  fillers and modal scaffolding dropped, one proposal per distinct action) and
  adapter guards that hold independently of the model: filler titles dropped
  as ungrounded, in-envelope restatements folded into the survivor, an `add`
  restating an active proposal rewritten as an affirming `update`, a
  converging `update` dropped, tombstones keyed on `normalized_title`.
- **Rationale**: the model alone cannot be trusted to be clean or
  deterministic; the guards make FR-004 hold even when the prompt is ignored,
  and dropped operations are logged by fixed reason so the behaviour is
  auditable without content.
- **Alternatives considered**: prompt-only cleanliness — rejected as
  unverifiable; regex or punctuation post-processing in the production path —
  already forbidden by the 2026-07-19 ADR-0002 amendment (no regex or fixture
  extraction in the production decision path).
- **Source**: ADR-0002, 2026-09-05 amendment; FR-003, FR-004; `intake.md` §1
  point 2.

## R-04 — A review with no surviving proposal is not committable

- **Decision**: `brain_dump_operation_is_committable` requires at least one
  non-deleted proposal; the web review renders no Send control and shows what
  was heard; mobile hides the confirm control (with W-02).
- **Rationale**: an empty envelope (nothing actionable was said) or a review
  where everything was discarded must never mint an empty completion; the
  honest exit is discard, which returns the owner to a fresh recording.
- **Alternatives considered**: a disabled Save on an empty review — rejected in
  favour of removing the control and stating why (D-03.h, D-03.i).
- **Source**: ADR-0002 amendment ("A review with no surviving proposal is not
  committable"); FR-005; Clarifications on the empty review; design open
  decisions 3 and 5.

## R-05 — Recovery from a terminal failure is reconciler extraction over preview text

- **Decision**: after a terminal accurate-lane failure with no surviving
  proposal and stable browser-preview text present, the owner may explicitly
  run the same task-extraction step once over that text
  (`reconcile_preview`); the result enters the normal review as provisional.
- **Rationale**: once the preview stopped producing fallback drafts, a terminal
  failure left only cancel although readable text sat in the operation — the
  founder's «у нас превью же текст, почему нельзя восстановить?».
- **Alternatives considered**: manual task entry from the transcript — laid out
  to the founder and not chosen; automatic fallback to preview text — forbidden
  (ADR-0002: "If audio is intact, offer an accurate-transcript retry from that
  audio — not a retry over fast text" still holds for every automatic
  recovery; this is the single explicit exception).
- **Source**: spec Clarifications, second decision; ADR-0002 same-day
  amendment; `intake.md` contradictions table.

## R-06 — One attempt per recording, inside the existing ceilings, never automatic

- **Decision**: a `preview_transcribed` or `preview_reconciled` run anywhere in
  the operation's history makes `reconcile_preview` unavailable for good; the
  run reserves the reconciler role's `max_cost_usd_per_operation` and is
  admitted only if it fits under `max_cumulative_cost_usd_per_operation`; the
  server never selects it.
- **Rationale**: no new spend path and no way to loop a failing provider; a
  retryable preview failure still gets the ordinary bounded `retry` over the
  preview text (never an STT rewind), which is what "one attempt" means at the
  operation level.
- **Alternatives considered**: a separate ceiling for the recovery — rejected
  as a new spend path; gating the recovery on the accurate lane's exhausted
  recovery budget — rejected because the preview run is a fresh, separately
  bounded stage.
- **Source**: spec Clarifications, third decision; ADR-0002 same-day amendment
  ("One shot", "Cost").

## R-07 — No "leave and come back later" affordance on the processing screen

- **Decision**: the processing screen offers "Cancel processing" and nothing
  else; processing continues on the server while the panel stays open and
  reopening the app resumes the recording where it is.
- **Rationale**: there is no in-app list of in-flight recordings to return to,
  so a leave button would orphan the operation.
- **Alternatives considered**: a leave/return control — rejected for the reason
  above; derived from the UX audit, not raised by the founder.
- **Source**: spec Clarifications, fourth decision; D-02.g.

## R-08 — Inline confirmations on the web; the platform dialog on mobile

- **Decision**: the web overlay confirms every destructive exit inline, in
  place of the trigger, with focus on the safe answer and Escape restoring the
  trigger (`DestructiveConfirm`); mobile confirms its three destructive exits
  through the platform dialog with the cancel choice first, and no control that
  discards a recording may be named "Close".
- **Rationale**: the brain dump already runs as an overlay and a dialog inside
  an overlay is hard to make accessible (focus trapping, lost screen-reader
  context); on mobile the platform dialog is the native confirmation and the
  data-loss risk of an unconfirmed "Close" is exactly what Principle V forbids.
- **Alternatives considered**: nested dialogs on the web — rejected; narrowing
  FR-007 and SC-004 to the web surfaces — rejected in favour of building the
  mobile confirmation (design open decision 1, recommended "build it").
- **Source**: spec Clarifications, fifth and eighth decisions; `design.md`
  "Requirements with no affordance".

## R-09 — The resumed timer starts from the captured audio duration

- **Decision**: on resume the timer is seeded from the seconds of audio
  captured, pauses excluded — implemented as `audio_chunks.length` because each
  uploaded chunk is one 1 s MediaRecorder timeslice and a paused recorder emits
  none — and the live tail is seeded from the latest unsuperseded segment.
- **Rationale**: the owner was counting speech captured, not wall-clock time
  since the recording began.
- **Alternatives considered**: wall-clock since `created_at` — rejected.
- **Source**: spec Clarifications, sixth decision; FR-008; D-01.f.

## R-10 — The interview and design sign-off gates were waived by the founder

- **Decision**: no interview session was held and design sign-off was not
  requested; both waivers are recorded in `intake.md` and in the spec's
  seventh clarification so `/speckit-accept` and `/speckit-report` can see them.
- **Rationale**: «просто доделай» closed elicitation.
- **Alternatives considered**: running `/speckit-interview` after the fact —
  rejected because the human declined further elicitation; the open choices
  were decided by the agent and attributed.
- **Source**: spec Clarifications, seventh decision; `intake.md` header.

## R-11 — FR-006 binds the web processing screen only

- **Decision**: the transcript readout and "Cancel processing" are web-only;
  mobile keeps naming the stage (M-03.b).
- **Rationale**: mobile has no preview lane, so half-building a readout there
  would promise text it may never hold; recording the gap is more honest than a
  partial surface.
- **Alternatives considered**: binding FR-006 to mobile — rejected for this
  feature; recorded under Out of Scope.
- **Source**: spec Clarifications, ninth decision.

## R-12 — A refused recovery shows its reason and a reference id

- **Decision**: the server's refusal (consent, spend ceiling, unavailable
  state) is shown in words with the request's reference id; never a bare
  status word such as "Forbidden".
- **Rationale**: FR-009 and constitution Principle III require actionable
  errors with correlation ids; mobile already showed both, the web printed
  `ApiError.message` (the HTTP status text) — the gap W-01 closes.
- **Alternatives considered**: recording the web gap for a later feature —
  rejected; fixed on this branch.
- **Source**: spec Clarifications, tenth decision; design open decision 2;
  `plan.md` W-01.

## R-13 — Risk class: declared `medium`, derived `high` (planning-stage decision)

- **Decision**: declare `medium` and state in `plan.md` that the preflight
  classifier will derive `high`, so the review campaign runs at `high`.
- **Rationale**: the change carries no auth, migration, CI, deploy or secrets
  logic, but it touches `backend/app/api/tasks.py`, an ASK exact path in
  `scripts/classify_path_risk.py`, and ADR-0012 lets derivation raise a class
  and never lower it; writing the escalation down is more useful than
  pretending either number away.
- **Alternatives considered**: declaring `high` outright — misstates the
  change; declaring `low` — never derivable and unjustified.
- **Source**: ADR-0012; `docs/spec-kit-workflow.md` "The review gate";
  `plan.md` Risk class and landing class.
