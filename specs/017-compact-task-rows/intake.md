# Business Intake: Compact Task Rows

**Feature**: `specs/017-compact-task-rows/`
**Interviewed**: 2026-09-10
**Interviewee**: Max

## The ask, as given

> «Полоска задачи должна быть достаточно узкой, чтобы я на экране видел, ну, задач 10 вообще без проблем.»

## 1. Problem

- **Whose problem**: the owner processing and reviewing their BrainBuddy task lists on a 13-inch Mac.
- **How it shows up today**: bordered task cards and the side sheet consume enough vertical and horizontal space that only about five tasks remain visible; the external-agent summary is verbose and row actions feel visually aggressive.
- **What it costs**: scanning requires unnecessary scrolling, task processing loses list context, and agent state competes with the task title.
- **If we build nothing**: the primary task-processing surface continues to feel sparse and cumbersome on the owner's everyday device.

## 2. Customer and persona

- **Primary**: the BrainBuddy owner using desktop web task lists.
- **Secondary**: none for this slice.
- **Deployment shape**: single-user product within a multi-tenant owner-scoped service.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| Fully visible open-task rows in the ordinary 13-inch Mac list viewport | about 5 | at least 10 | feature acceptance |
| Collapsed task-row height | roughly 56–64 px depending on content | 44 px, with no action wrapping | feature acceptance |

## 4. Scope boundary

**In scope**

- [x] Replace desktop task cards with quiet 44 px rows.
- [x] Expand the selected Task detail directly below its row instead of in a right-side sheet.
- [x] Show short Tags on the collapsed row and omit Project/List text from that row.
- [x] Show a small split agent control before assignment: robot for the last-used eligible agent and arrow for choosing another eligible agent.
- [x] Preserve the mandatory review-and-confirm step before any task content leaves BrainBuddy.
- [x] Show an assigned agent as a fixed-size state control with no arrow; clicking it opens the inline Task detail/run information.
- [x] Keep Delete out of the collapsed row.

**Out of scope — explicitly confirmed by the human**

- [x] Backend API, persistence, Task lifecycle, or relay-contract changes.
- [x] Mobile-client redesign.
- [x] A new Project/List label on collapsed rows.
- [x] A collapsed-row Delete action or delete-confirmation flow.
- [x] Changing the server-owned external-agent state vocabulary or weakening hand-off consent/review.

**Confirmed by**: Max on 2026-09-10 with «делаем» after the design iterations.

## 5. Constraints

- **Deadline**: none stated.
- **Platform**: desktop web; responsive web must remain usable at narrow widths.
- **Offline behavior**: existing cached task and agent projections remain unchanged; no new offline mutation queue.
- **Must not break**: owner scoping, URL-addressable Task selection, autosave recovery, Task completion animation, agent consent/review, server-owned state labels, feature-flag behavior, keyboard focus, and existing task creation.
- **Budget / provider cost limits**: no new provider calls or dependencies.

## 6. Compliance obligation

This feature adds no data-handling obligation beyond the existing baseline.

- **New server records**: none. One owner/API-scoped browser-local preference stores
  only the last-used eligible connection ID plus confirmation timestamp; it contains no
  Task content, credential, agent address, or authorization and is ignored when the
  connection is no longer eligible or the record is older than 30 days.
- **Consent**: unchanged mandatory hand-off review and confirmation before content leaves BrainBuddy.
- **Retention**: unchanged.
- **Export**: unchanged.
- **Purge**: unchanged.
- **Residency / other obligations**: unchanged.

## 7. Existing-system dependencies

- **Backend surfaces**: existing Task detail/list and agent connection/run summary responses; no contract change.
- **Frontend surfaces**: desktop Task list, route-backed Task detail, external-agent hand-off overlay, agent summary copy, completion animation.
- **Mobile**: unaffected.
- **AI providers**: no new use; existing external-agent relay only.
- **Primary loop impact**: improves the clarify/route/review part of capture → atomic items → clarify/approve → route or CRT candidate → Weekly Review → evidence/results by keeping more Tasks visible while one Task is inspected.

## 8. Definition of done

- [x] At least ten collapsed 44 px rows fit in the ordinary target desktop list area without action wrapping.
- [x] Selecting a Task keeps the list visible and expands its existing detail controls below that row.
- [x] Collapsed rows show Tags but no Project/List label and no Delete button.
- [x] The pre-assignment robot/arrow control and every assigned state control are keyboard operable and have accessible names.
- [x] Assigned state controls share one width and height, omit the arrow, and preserve the server-owned primary state label.
- [x] The last-used shortcut and explicit agent chooser both enter the existing hand-off review before dispatch.
- [x] Targeted frontend tests, build, Spec Kit gates, and affected accessibility/focus assertions pass.

## Deferred to /speckit-clarify

- [x] None. The design iterations settled density, visible metadata, Delete removal, split-button behavior, assigned-chip behavior, and alignment.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| Delete should be visible with two-step confirmation | Delete is visually unnecessary | Delete is removed from the collapsed row; deeper lifecycle controls remain in Task detail | Max |
| Assigned agent control included a dropdown arrow | An already-selected agent does not need an arrow | Only the pre-assignment control retains the arrow | Max |
