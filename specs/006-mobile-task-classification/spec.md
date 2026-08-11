# Feature Specification: Assign project and tags from the mobile task screen

**Feature Branch**: `claude/multi-agent-plugin-search-37qezh`

**Created**: 2026-08-10

**Status**: Draft

**Input**: Business intake at `intake.md`, produced by `/speckit-interview` with
the founder on 2026-08-10. The scope boundary and non-goals in §4 of that
document were read back as nine numbered items and confirmed explicitly.

## Clarifications

### Session 2026-08-11

The `/speckit-clarify` stage was interrupted and its questions were put to the
human directly. Two of the five came from the repository's automated reviewer
on the pull request rather than from the spec's own open questions, and both
were verified against the codebase before being asked.

- Q: AGENTS.md requires new production behavior behind a server-owned flag,
  default OFF, while this spec forbade every backend change. Which wins?
  → A: Permit the minimal flag wiring. The prohibition on new task routes
  stands. (`backend/app/core/config.py` holds `KNOWN_FEATURE_FLAGS` and is not
  one of the ASK-classified paths, so this does not touch the path constraint.)
- Q: Creating a project or tag needs the server to assign identity, so it
  cannot be queued. Accept that offline classification is limited to entities
  that already exist? → A: Accept the narrowing.
- Q: The mobile client can change servers and the queue survives restarts.
  What happens to pending entries on an account or server change?
  → A: Bind every entry to its account and server, and clear on any identity
  transition with the same warning as sign-out.
- Q (design sign-off): per-change "not sent" marker on each changed row, or one
  marker per screen? → A: **Neither — remove it.** "Store the data on the device
  until there is internet; you can show the person when the last sync was."

  **This reverses an earlier answer in the same run** and is recorded as a
  reversal rather than quietly applied. Asked during the interview what should
  happen offline, the human chose "show the new value with a not-sent marker"
  over "just show the new value". The later answer came with its reasoning —
  the app is offline-first, and per-field sync bookkeeping is the app's problem,
  not the person's — so it is treated as a considered revision and it wins.
  FR-007 and SC-004 are rewritten accordingly, and the consequence is recorded
  under Assumptions.

Still open, carried forward rather than answered: the KPI baseline (see
Assumptions) and what "connectivity returned" means concretely.

### Open product decisions

Raised by the review campaign of 2026-08-11 (run
`006-mobile-task-classification-c1`), put to the human, and **not yet
answered**. They are recorded here rather than resolved because the review gate
classifies them as product decisions: they trade user-visible behaviour against
cost, and no reviewer or agent has standing to settle them. Implementation is
blocked on all four. Each names what happens under the current text, so the
cost of leaving one unanswered is visible rather than implied.

1. **How long may an unsent change rest on the device?** No bound is stated
   anywhere, so an entry lives until it sends or the person discards it. The
   device queue is the only place in the product where account content has no
   retention limit — `docs/data-retention.md` bounds everything else — and the
   backend's idempotency replay window is 24 hours, so a retry older than that
   is no longer protected against double-applying by FR-017's mechanism.
2. **What happens to unsent work when the session ends involuntarily?** See
   FR-011. `SessionProvider` treats a network failure at cold start the same as
   a 401, so an offline launch is indistinguishable from a sign-out, and the
   session token expires by itself after 30 days. Under the current text both
   destroy the queue with no warning and no action to attach one to.
3. **Is the coalescing rule settled, and does anything remember the original
   value?** FR-010 states the net effect as a MUST while this section listed the
   same question as open, so the two disagree about whether it was ever asked.
   `data-model.md` implements a net-effect reducer that keeps the first
   `observedRevision` — which means the value the person started from is not
   retained, and M-04 cannot say "it was A, you set C" without it.
4. **Does the partial-failure behaviour stay?** M-01 and M-03 both specify it
   ("Project saved. Tags could not be saved."), and `PATCH /tasks/{id}` is
   atomic, so no sequence of events can produce that state. Either the design
   states an outcome that cannot occur, or the feature needs two calls per
   change — which is a materially larger queue with a new desynchronised state.

## User Scenarios & Testing *(mandatory)*

Three journeys, ordered by importance. The first is a viable slice on its own:
it closes the gap the feature exists for. The second and third each add a
capability the human asked for, and each is testable without the ones after it.

### User Story 1 - Classify a task where you read it (Priority: P1)

A person opens a task on their phone, sees it has no project and no tags, and
sets both without leaving the screen.

**Why this priority**: This is the whole problem. Capture already happens on the
phone; classification does not, so triage is split across two devices. Shipping
only this story makes inbox triage completable on mobile for every task whose
project and tag already exist — which, for an established set of projects and
tags, is nearly all of them.

**Independent Test**: With at least one project and two tags already present,
open a task on the phone, set the project, add both tags, and confirm the same
values in the web client after a refresh.

**Acceptance Scenarios**:

1. **Given** a task with no project, **When** the person picks a project, **Then**
   the task shows that project and the change reaches the server.
2. **Given** a task with a project, **When** the person clears it, **Then** the
   task shows no project — clearing is a supported outcome, not an absence of
   one.
3. **Given** a task with no tags, **When** the person adds two tags, **Then** both
   are attached, and the order they were added does not change which tags the
   task has.
4. **Given** a task with two tags, **When** the person removes one, **Then** only
   that tag is detached and the other is untouched.
5. **Given** a person picks a second project, **When** the change is saved,
   **Then** the task has only the newer project — a task carries at most one.

---

### User Story 2 - Name something that does not exist yet (Priority: P2)

While classifying, a person needs a project or tag that has never been created,
and creates it from the same screen rather than abandoning the triage.

**Why this priority**: Without it, triage stalls exactly when the person is
thinking clearly about how work should be organised — the moment a new project
suggests itself. It is second, not first, because a person with an established
set of projects and tags can finish triage without it.

**Independent Test**: On the phone, from a task, create a project with a name
that does not exist, and confirm the task carries it and the web client lists
the new project.

**Acceptance Scenarios**:

1. **Given** the person types a project name that does not exist, **When** they
   confirm creation, **Then** the project exists and is assigned to the task in
   one action.
2. **Given** the person types a tag name that does not exist, **When** they
   confirm creation, **Then** the tag exists and is attached to the task.
3. **Given** a name that matches an existing project or tag, **When** the person
   is choosing, **Then** the existing one is offered rather than a duplicate
   being created.
4. **Given** creation fails, **When** the error is shown, **Then** the task's
   existing classification is unchanged and the person can retry without
   retyping the name.

---

### User Story 3 - Classify with no signal, without having to think about it (Priority: P3)

A person triages on a train with no connectivity. Their changes are accepted and
simply look made — the app holds them on the device and delivers them when the
connection returns, without asking the person to track what is in flight. If the
task changed elsewhere in the meantime, they are asked which change wins.

**Why this priority**: It is the largest slice and the only one whose absence
still leaves a working feature — without it, the same actions simply fail
honestly while offline. It is a requirement rather than a refinement because the
human chose deferred send over an error when asked directly.

**Why the conflict question is part of this story and not a later one**: the task
update contract requires the revision the client last observed. A queued change
necessarily carries a revision from before it was queued, so rejection is an
ordinary outcome of normal use, not a rare race. Deferred send without a conflict
rule is not shippable.

**Independent Test**: With connectivity disabled, change a task's project on the
phone and confirm the screen shows it as made with no sync decoration, then
re-enable connectivity and confirm the change arrives and the last-synchronised
time advances.

**Acceptance Scenarios**:

1. **Given** no connectivity, **When** the person changes the project or tags,
   **Then** the change is accepted and shown as made, with no per-change
   not-sent decoration anywhere on the screen.
2. **Given** a queued change, **When** connectivity returns, **Then** the change
   is sent and the last-synchronised time advances, without the person doing
   anything.
3. **Given** a queued change and a task that changed elsewhere, **When** the
   server rejects the change, **Then** the person is asked whether to apply
   theirs over the newer state or abandon it, and neither is chosen for them.
4. **Given** the person chooses to apply theirs, **When** they confirm, **Then**
   their classification replaces the newer one and the queue entry clears.
5. **Given** the person chooses to abandon, **When** they confirm, **Then** the
   task shows the newer server state and nothing of theirs is left pending.
6. **Given** unsent changes exist, **When** the person signs out, **Then** they
   are warned that unsent work will be lost before it is discarded.
7. **Given** the person cancels that sign-out, **When** they return, **Then** the
   queued changes are still pending and still marked.
8. **Given** unsent changes and a switch to a different server or account,
   **When** the switch is confirmed, **Then** the person is warned first and the
   entries are discarded — they are never shown to, or sent under, the new
   identity.
9. **Given** the app is closed and reopened with the same account and server,
   **When** it starts, **Then** the queued changes are still pending and still
   marked.

---

### Edge Cases

- **A queued change for a task deleted elsewhere.** The task no longer exists
  when the queue drains. Treated as a conflict the person is told about, not a
  silent discard.
- **A queued change naming a project or tag deleted elsewhere.** The
  classification target is gone; the person is told rather than the change
  failing opaquely.
- **Two queued changes for the same task.** The later one supersedes the
  earlier; the queue does not send two changes that fight each other.
- **Creating a project or tag while offline.** Not possible; FR-016. The
  affordance is unavailable offline and says why, rather than failing after the
  person has typed a name.
- **A queued change belonging to another account or server.** Bound by FR-011
  and never displayed or sent under the wrong identity. The mobile client can
  change servers (`bb.serverUrl` is persisted), so this is reachable without
  signing out at all.
- **The app is closed with changes still queued.** Principle V requires local
  drafts and operation checkpoints to avoid data loss, so the queue survives.
- **A tag added and removed before the queue drains.** The net effect is sent,
  not both operations.
- **Sign-out while the queue is mid-send.** The warning must reflect what is
  actually unsent at that moment, not a stale count.
- **A conflict on a change the person no longer remembers making.** With no
  per-change marker there is nothing on the task screen that said the change was
  still in flight, so the conflict prompt must name what was changed and when,
  not only the two values.
- **A task with many tags.** The screen stays usable and the person can still
  reach the controls; no scroll trap.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A person MUST be able to set, change and clear a task's project
  from the mobile task detail screen.
- **FR-002**: A person MUST be able to attach and detach tags on a task from the
  mobile task detail screen, with more than one tag attachable.
- **FR-003**: The system MUST hold at most one project per task, and MUST allow
  a task to have no project. This restates the shape established by spec 003 and
  the web client; it does not redefine it.
- **FR-004**: A person MUST be able to create a project or a tag from the task
  detail screen and have it attached to the task in a single action.
- **FR-005**: When a typed name matches an existing project or tag, the system
  MUST offer the existing one rather than creating a duplicate.
- **FR-006**: The system MUST accept a classification change while offline and
  send it when connectivity returns, without the person re-entering it.
- **FR-007**: The app MUST NOT mark individual unsent changes. A change is shown
  as made, whether or not the server has it yet. The app MUST instead show when
  it last synchronised with the server, so a person can judge freshness once for
  the whole screen rather than field by field.
- **FR-008**: When the server rejects a queued change because the task changed
  meanwhile, the system MUST ask the person whether their change wins or is
  abandoned, and MUST NOT decide for them.
- **FR-009**: Queued changes MUST survive the app being closed and reopened.
- **FR-010**: When several queued changes target the same task, the system MUST
  send the net effect rather than replaying each in turn.
- **FR-011**: Every queued change MUST record the account and the server it was
  made against, and MUST NOT be displayed or sent under any other. On a
  **deliberate** sign-out, account change or server change, unsent changes MUST
  be warned about and then discarded, so no account's content is left on the
  device under another identity. What happens when the session ends without
  anyone choosing it — an expired token, or a network failure the client cannot
  currently tell apart from a rejection — is open decision 2 and MUST be settled
  before implementation; the warning this requirement relies on cannot be shown
  on a path where there was no action to warn about.
- **FR-017**: A queued change MUST reach the server at most once. Each entry
  MUST carry an idempotency key generated when the entry is created and reused
  unchanged on every retry, and the system MUST NOT have two sends of one entry
  in flight at the same time. A request that times out or loses its connection
  MAY already have been applied; retrying it MUST NOT be able to apply it twice.
- **FR-015**: Production exposure of this behavior MUST be controlled by a
  server-owned feature flag defaulting to OFF, per AGENTS.md. The flag governs
  exposure only and is never authorization.
- **FR-016**: Creating a project or tag MUST require connectivity, and the
  affordance MUST be unavailable rather than failing late when offline, saying
  why. Identity for a new project or tag is assigned by the server, so a
  created-offline entity would have nothing stable for a queued change to
  reference.
- **FR-012**: Every failure a person sees MUST be actionable and MUST carry the
  correlation ID of the failed request, matching the behaviour the rest of the
  product already has.
- **FR-013**: The system MUST use the term **Tag** throughout, per ADR-0006.
  Never Context, never @context.
- **FR-014**: The feature MUST NOT add a task route to the backend, and MUST NOT
  require any change to the web client. Backend change is limited to the flag
  wiring in FR-015; `backend/app/api/tasks.py` and the other ASK-classified
  path modules stay untouched.

### Out of scope

Confirmed by the human as a read-back of the interview, and repeated here
because `intake.md` is not what a reviewer or the acceptance auditor grades
against.

- **Bulk assignment from the task list.** Selecting several tasks and
  classifying them together is a different interaction with its own selection
  model.
- **Managing projects and tags** — renaming, colors, archiving, deleting. This
  screen may create and attach; it may never curate.
- **Smart-add `#tag` / `@project` token syntax on mobile.** That is a capture
  feature with its own ADR-0007 and its own delivered spec (003). Putting a
  parser on this screen would restate those rules on a second client.
- **Task routes, and web client changes** (FR-014). The web client already has
  this capability. Backend change is confined to registering and reading the
  feature flag of FR-015 — the interview's "no backend change" boundary was
  written before AGENTS.md's flag rule was checked against it, and the flag
  wiring is the narrowest thing that satisfies both.

### Key Entities

- **Task**: already exists. Carries at most one project and any number of tags,
  and a revision that the server uses to detect a change made elsewhere.
- **Project**: already exists. A task points at one or none.
- **Tag**: already exists. A task points at zero or more.
- **Pending classification change**: new, and device-local. What the person
  chose, which task it applies to, the task revision they were looking at when
  they chose it, and the account and server it was made against. It exists only
  until the server accepts it, the person abandons it at a conflict, or an
  identity transition clears it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person can take a task from unclassified to classified — project
  and tags both set — entirely on the phone, without opening the web client.
- **SC-002**: A classification made on the phone is visible in the web client on
  the next refresh, with the same project and the same tags.
- **SC-003**: A classification made with no connectivity is never lost: it is
  either delivered once connectivity returns, or abandoned by an explicit choice
  the person made.
- **SC-004**: A person can tell, without leaving the task screen, how current
  what they are looking at is — by the last-synchronised time, not by per-change
  bookkeeping they have to read and reconcile.
- **SC-005**: No conflict is resolved without the person choosing. Zero
  classifications are overwritten or discarded silently.
- **SC-007**: No pending change is ever shown to, or sent under, an account or
  server other than the one it was made against.
- **SC-006**: Triage of a task requires no more interactions on the phone than
  the same triage on the web client, so moving to mobile costs nothing in effort.

## Assumptions

- **Removing the per-change marker moves the whole burden onto two places.**
  With no not-sent decoration, the only surfaces that reveal unsent work are the
  last-synchronised time — which says *when*, never *what* — and the discard
  warning at an identity transition, which is also the last moment to act on it.
  That is the accepted cost of the offline-first choice, not an oversight.
  Sign-off then narrowed the second surface too: the discard warning states a
  count and no list. So no surface in the app names an unsent change — a person
  can be told that two exist and that continuing destroys them, never which
  two. The one place that still names anything is the conflict prompt, and only
  for the change that happened to conflict.

- **No numeric adoption target is claimed, and this is deliberate.** The intake
  names the objective — complete inbox triage from the phone — but the share of
  tasks classified without switching to the web client is not instrumented
  today, so there is no baseline to improve on and inventing one would produce
  a criterion the acceptance auditor cannot honestly grade. SC-001 through
  SC-006 are observable instead. Carried to `/speckit-clarify` in case the human
  wants a number after all.
- **Queued changes survive an app restart.** Not asked in the interview;
  derived from Principle V, which requires local drafts and operation
  checkpoints to avoid data loss. Recorded as an assumption rather than silently
  treated as a decision — flagged for `/speckit-clarify`.
- **Creating a project or tag requires connectivity — confirmed, not assumed.**
  Raised in clarify and accepted by the human, so offline classification is
  limited to projects and tags that already exist. User Story 3 is deliberately
  narrower than User Story 2, and FR-016 states it.
- **"Connectivity returned" means the next time the app is in use and a request
  succeeds.** No background sync while the app is closed is assumed. Flagged for
  `/speckit-clarify`.
- **Not a single-user system, corrected.** An earlier draft of this spec
  assumed one, reasoning from invite-gated signup. That was wrong: `docs/auth.md`
  describes reusable invites, ordinary accounts and per-owner isolation, and the
  mobile client persists a switchable server URL. The correction matters
  because it is what makes FR-011 more than a sign-out rule — a durable device
  queue outlives both the account and the server it was made against. Found by
  the repository's automated reviewer, not by this spec's own author.
- **No new consent surface.** No new personal data is collected and no AI
  provider sees this content, so the existing consent model is untouched. The
  device-local queue is the only new place account content rests, and FR-011
  bounds its lifetime.
- **Primary loop impact: clarify/approve.** The loop is capture → atomic items →
  clarify/approve → route or CRT candidate → Weekly Review → evidence. Today
  classification during clarify/approve is only completable in the web client;
  this closes that on the device where capture already happens. No other stage
  of the loop changes.
- **No responsiveness target beyond the existing product expectation.** This
  feature does not touch the CRT canvas, so the ~200-node responsiveness
  requirement does not apply to it.
