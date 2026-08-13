# Business Intake: Assign project and tags from the mobile task screen

**Feature**: `specs/006-mobile-task-classification/`
**Interviewed**: 2026-08-10
**Interviewee**: MaksimKravchuk (founder)

<!--
  Produced by /speckit-interview before /speckit-specify. This is the record of
  what the human actually agreed to, in their own terms. It is not a
  specification: no schemas, no endpoints, no module boundaries. Where a
  heading did not apply, say why — never delete the heading.
-->

## The ask, as given

> Assigning a project and tags to a task from the task detail screen in the
> mobile app. Today that screen displays project and tag pills read-only
> (`mobile/src/app/task/[id].tsx` around lines 309-314) and offers no way to
> change them.

The ask was selected by the human from three offered candidates as the subject
of the first end-to-end run of the delivery pipeline.

**No stage-0 assessment exists.** `.specify/assessments/` is absent. Assessment
was skipped deliberately: the ask is small, concrete, and the human chose it
explicitly, which is the "small, obviously-wanted change" case the interview
skill permits to proceed. Recorded here rather than silently omitted.

## 1. Problem

- **Whose problem**: the person triaging their own inbox from a phone.
- **How it shows up today**: the mobile task screen renders the project and tag
  pills but has no control to change them. The web client has had post-create
  classification since before this feature — a project select and tag
  checkboxes in `TaskDetailPanel` — so the capability exists everywhere except
  where the triage actually happens.
- **What it costs**: inbox triage cannot be finished on the phone. Tasks are
  captured on mobile and then left unclassified until the person opens the web
  client, which splits one intention across two sittings and two devices.
- **If we build nothing**: mobile stays capture-only for classification
  purposes, and the backlog of unclassified tasks keeps being drained from the
  desktop.

## 2. Customer and persona

- **Primary**: the founder, triaging their own tasks on iOS.
- **Secondary**: none.
- **Deployment shape**: single-user in practice — a private, invite-gated
  deployment (`docs/auth.md`; signup requires an invite code minted by CLI).
  Not asked in the interview; read from the repository, per the rule against
  asking what can be read. Stated explicitly because it is what makes the
  compliance answers in §6 small.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| share of tasks reaching a classified state without switching to the web client | **unknown — not instrumented** | **not set** | not set |

The human chose the objective — *complete inbox triage entirely from the
phone* — and the metric follows from it. **Neither the baseline nor the target
was given, and neither was invented here.**

This is a real gap, not a formality: the template warns that an objective with
no number produces a spec the acceptance auditor cannot grade. Two ways out,
both deferred to `/speckit-clarify`:

- pick a number now and accept that the baseline is a guess, or
- grade this feature on the observable definition of done in §8 and record
  that no numeric `SC-###` is claimed.

The second is more honest for a single-user tool with no analytics, and is the
recommendation carried into clarify.

## 4. Scope boundary

**In scope**

- [x] Assign a project to a task from the mobile task detail screen. One
      project per task, and it may be cleared.
- [x] Assign tags to a task from the same screen. Many tags per task.
- [x] Create a new project or a new tag inline, without leaving the screen.
- [x] Accept the change while offline and send it when connectivity returns.
- [x] Show a queued change as applied, carrying a visible "not sent" marker
      until the server confirms it.
- [x] When the server rejects a queued change because the task changed
      meanwhile, ask the human whether to apply theirs over the newer state or
      abandon it.
- [x] Clear the queue on sign-out, warning first when it is non-empty.

**Out of scope — explicitly confirmed by the human**

- [ ] Bulk assignment from the task list screen. Selecting several tasks and
      classifying them together is a different interaction with its own
      selection model.
- [ ] Managing projects and tags — renaming, colors, archiving, deleting. The
      screen may create and attach, never curate.
- [ ] Smart-add `#tag` / `@project` token syntax on mobile. That is a capture
      feature with its own ADR-0007 and its own delivered spec (003); putting a
      parser on this screen would duplicate those rules on a second client.
- [ ] Any change to the web client or the backend. The web client already has
      this capability, and `PATCH /tasks/{id}` already carries `project_id` and
      `tag_ids`.

<!--
  Non-goals are the highest-value answers in the interview. Both lists were
  read back and confirmed; record the confirmation, not an assumption.
-->

**Confirmed by**: MaksimKravchuk on 2026-08-10, by explicit answer to a
read-back of all nine numbered items — not by silence.

## 5. Constraints

- **Deadline**: none.
- **Platform**: mobile only (Expo / React Native, iOS-first).
- **Offline behavior**: **required.** The human chose deferred send over a
  plain error, so the queue is a requirement of the feature and not a quality
  of implementation.
- **Must not break**:
  - No new backend route. `backend/app/api/tasks.py` is ASK-gated by exact
    path in this environment, and the feature was scoped so that it does not
    need one.
  - `TaskUpdateRequest` requires `expected_revision`. This is the constraint
    that makes §4's conflict rule mandatory rather than optional: a queued
    change necessarily carries a revision observed earlier, so a rejection is
    an expected outcome of normal use, not an edge case.
  - The GTD vocabulary is fixed by ADR-0006: the term is **Tag**, never
    Context.
  - The one-project / many-tags shape is already established by spec 003 and
    the web client; this feature restates it, it does not redefine it.
- **Budget / provider cost limits**: not applicable — no AI provider is
  involved.

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management —
profile/email/password, ZIP data export, 14-day-grace deletion and purge — and
is never feature-flagged (see `docs/data-retention.md`). Record what **this
feature adds** to that baseline.

- **New durable records**: none on the server. On the device, the offline
  queue is new: it holds unsent task changes, which are user content. This
  followed from the human's choice of deferred send and was raised in the
  interview rather than discovered later.
- **Consent**: nothing new. No new personal data is collected and no AI
  provider sees this content.
- **Retention**: a queued entry lives until it is sent, abandoned at a
  conflict, or cleared at sign-out.
- **Export**: not applicable. Tasks, projects and tags are already in the ZIP
  export; the queue holds pending copies of data that is either already
  exported or not yet server-side at all.
- **Purge**: server-side purge is already covered. The device queue is cleared
  on sign-out — with a warning first, per the human's answer, because clearing
  it destroys unsent work and Principle V requires warning before a
  destructive side effect.
- **Residency / other obligations**: none.

## 7. Existing-system dependencies

- **Backend surfaces**: none changed. Reuses `PATCH /tasks/{id}`,
  `POST /projects` and `POST /tags`, all three of which the mobile API client
  already calls with idempotency keys.
- **Frontend surfaces**: none. The web client is untouched.
- **Mobile**: **must change** — the task detail screen, and new device-local
  queue behavior.
- **AI providers**: not used.
- **Primary loop impact**: this sits in *clarify/approve*. The loop is
  capture → atomic items → clarify/approve → route or CRT candidate → Weekly
  Review → evidence. Today the clarify/approve step is only completable on the
  web client for classification; this closes that gap on mobile, which is the
  device the capture step already happens on.

## 8. Definition of done

What the human wants to see to believe it works. Observable, not "it works":

- [ ] Change the project and tags of a task on the phone, refresh the web
      client, and see the same project and tags there.
- [ ] Make a change with no connectivity, see it marked as not sent, restore
      connectivity, and see it arrive.
- [ ] Have the same task changed elsewhere while a change is queued, and be
      asked which one wins rather than having either silently discarded.

Note on how this will be graded: `mobile/` has no component-render test
library, so acceptance evidence comes from extracted pure logic under unit
test, `make integration-mobile` against a disposable local backend, and
typecheck/build. The first bullet above is the end-to-end criterion and is
checkable without rendering a component.

## Deferred to /speckit-clarify

- [ ] **KPI baseline and target, or an explicit decision not to claim one.**
      See §3. Blocks a numeric `SC-###`; does not block the spec.
- [ ] **Does the queue survive an app restart?** Principle V requires local
      drafts and operation checkpoints to avoid data loss, which points
      strongly at yes, but the human was not asked directly and it should not
      be inferred into a requirement without them.
- [ ] **Ordering when several queued changes touch the same task.** Follows
      from the queue choice; not raised in the interview.
- [ ] **What "connectivity returned" means concretely** — on app foreground,
      on a network event, on the next successful request. Product-visible
      because it decides how long a change can sit unsent.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| — | — | none surfaced | — |

<!--
  One thing worth recording that is not a contradiction: the human chose the
  larger option on both forks offered — inline creation over pick-from-existing,
  and a deferred-send queue over an honest error. Both were flagged as the more
  expensive choice at the time of asking, and both were taken deliberately. The
  feature is consequently not a small one, which is worth knowing when reading
  the review verdict on a first pipeline run.
-->
