# Feature Specification: Assign project and tags from the mobile task screen

**Feature Branch**: `claude/multi-agent-plugin-search-37qezh`

**Created**: 2026-08-10

**Status**: Draft

**Input**: Business intake at `intake.md`, produced by `/speckit-interview` with
the founder on 2026-08-10. The scope boundary and non-goals in §4 of that
document were read back as nine numbered items and confirmed explicitly.

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

### User Story 3 - Classify with no signal, and be told the truth about it (Priority: P3)

A person triages on a train with no connectivity. Their changes are accepted,
visibly marked as not yet sent, and delivered when the connection returns. If
the task changed elsewhere in the meantime, they are asked which change wins.

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
phone, observe the not-sent marker, re-enable connectivity, and confirm the
change arrives and the marker clears.

**Acceptance Scenarios**:

1. **Given** no connectivity, **When** the person changes the project or tags,
   **Then** the change is accepted, shown as applied, and carries a visible
   not-sent marker.
2. **Given** a queued change, **When** connectivity returns, **Then** the change
   is sent and the marker clears without the person doing anything.
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
- **Creating a project or tag while offline.** Creation needs the server to
  assign identity, so it cannot be queued the way an assignment can. This is a
  real boundary of the offline story and is called out in Assumptions rather
  than papered over.
- **The app is closed with changes still queued.** Principle V requires local
  drafts and operation checkpoints to avoid data loss, so the queue survives.
- **A tag added and removed before the queue drains.** The net effect is sent,
  not both operations.
- **Sign-out while the queue is mid-send.** The warning must reflect what is
  actually unsent at that moment, not a stale count.
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
- **FR-007**: A change that has not been confirmed by the server MUST be visibly
  marked as not sent, distinct from a confirmed change.
- **FR-008**: When the server rejects a queued change because the task changed
  meanwhile, the system MUST ask the person whether their change wins or is
  abandoned, and MUST NOT decide for them.
- **FR-009**: Queued changes MUST survive the app being closed and reopened.
- **FR-010**: When several queued changes target the same task, the system MUST
  send the net effect rather than replaying each in turn.
- **FR-011**: Signing out with unsent changes MUST warn before discarding them,
  and MUST discard them on confirmation so no account content is left on the
  device.
- **FR-012**: Every failure a person sees MUST be actionable and MUST carry the
  correlation ID of the failed request, matching the behaviour the rest of the
  product already has.
- **FR-013**: The system MUST use the term **Tag** throughout, per ADR-0006.
  Never Context, never @context.
- **FR-014**: The feature MUST NOT add a task route to the backend, and MUST NOT
  require any change to the web client.

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
- **Any change to the web client or the backend** (FR-014). The web client
  already has this capability.

### Key Entities

- **Task**: already exists. Carries at most one project and any number of tags,
  and a revision that the server uses to detect a change made elsewhere.
- **Project**: already exists. A task points at one or none.
- **Tag**: already exists. A task points at zero or more.
- **Pending classification change**: new, and device-local. What the person
  chose, which task it applies to, and the task revision they were looking at
  when they chose it. It exists only until the server accepts it, the person
  abandons it at a conflict, or sign-out clears it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person can take a task from unclassified to classified — project
  and tags both set — entirely on the phone, without opening the web client.
- **SC-002**: A classification made on the phone is visible in the web client on
  the next refresh, with the same project and the same tags.
- **SC-003**: A classification made with no connectivity is never lost: it is
  either delivered once connectivity returns, or abandoned by an explicit choice
  the person made.
- **SC-004**: A person can always tell, without leaving the task screen, whether
  what they are looking at has reached the server.
- **SC-005**: No conflict is resolved without the person choosing. Zero
  classifications are overwritten or discarded silently.
- **SC-006**: Triage of a task requires no more interactions on the phone than
  the same triage on the web client, so moving to mobile costs nothing in effort.

## Assumptions

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
- **Creating a project or tag requires connectivity.** Identity is assigned by
  the server, so a created-offline entity would have no stable identity to
  attach. Offline classification is therefore limited to projects and tags that
  already exist. This is a genuine narrowing of User Story 3 against User Story
  2 and should be confirmed with the human rather than assumed away.
- **"Connectivity returned" means the next time the app is in use and a request
  succeeds.** No background sync while the app is closed is assumed. Flagged for
  `/speckit-clarify`.
- **Single-user deployment.** Private and invite-gated, so there is no
  multi-user permission question about who may create a project or tag. Read
  from `docs/auth.md`, not asked.
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
