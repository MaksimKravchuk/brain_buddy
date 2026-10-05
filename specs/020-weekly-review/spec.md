# Feature Specification: Weekly Review

**Feature Branch**: `020-weekly-review`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "A weekly review that keeps Next Actions executable: no formulation stays in Next longer than a user-chosen threshold without a decision; a guided, shame-free review for GTD practitioners and newcomers with ADHD as the design centre; an AI navigator that proposes a first step; auto-park to Someday when a review is missed; full parity on iOS, web and (after Mac sync) macOS." Business requirements: [intake.md](./intake.md). Concept and owner decisions: [`.specify/assessments/weekly-review/concept.md`](../../.specify/assessments/weekly-review/concept.md).

## Primary loop impact

This feature implements the **smart Weekly Review** stage of the constitution's primary loop (capture → clarify → organize → **review** → evidence) for native tasks. It feeds back into clarify (reformulate, find a first step) and organize (Waiting, Someday, cancel). Voice-led review (ADR-0002 `weekly_review_voice`) and review of agent-delegated work remain later phases and are not part of this spec.

## Vocabulary

- **Formulation**: a task's title while the task is in Next. A substantive title change starts a new formulation. Moving the task into Next also starts a new one.
- **Formulation age**: time since the current formulation started.
- **Threshold**: the user-chosen age (7, 14, 21 or 28 days; default 14) after which a formulation **asks for a decision**.
- **Asks for a decision**: a derived marker, not a list. ADR-0006's four open lists are unchanged.
- **Auto-park**: the system moves a formulation that is still undecided **7 days after the threshold** from Next to Someday.
- **Extension**: a one-time, reasoned "keep 7 more days" for one formulation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A stalled task asks for a decision (Priority: P1)

A person sees in Next which tasks are fresh, which are ageing and which ask for a decision. For a task that asks, they open a decision card and resolve it in one or two taps:
- done;
- reformulate;
- find a first step;
- move to Waiting (who/what);
- release to Someday;
- cancel;
- keep 7 more days (once, with a reason).

Optionally they say what got in the way. The card is reachable from the task on any day, not only during a review.

**Why this priority**: This is the owner's core rule — "a task must not hang in Next with the same name for more than two weeks". Every other story builds on the formulation clock and the card.

**Independent Test**: Seed a task whose formulation is older than the threshold. Verify the marker, open the card, exercise each decision, and verify the resulting task state and formulation clock. This works without any review session, schedule or AI.

**Acceptance Scenarios**:

1. **Given** a task that entered Next 15 days ago with an unchanged title and a 14-day threshold, **When** the person views Next, **Then** the task shows "asks for a decision" and nothing is coloured as an error or labelled "overdue".
2. **Given** a task in Next for 9 days with a 14-day threshold, **When** the person views Next, **Then** it shows the "ageing" marker. **Given** 3 days, **Then** it shows no age marker.
3. **Given** a task that asks for a decision, **When** the person reformulates it with a substantively different title, **Then** the task stays in Next, its formulation age restarts at zero, and its marker disappears.
4. **Given** a task that asks for a decision, **When** the person changes only letter case, whitespace or punctuation of the title, **Then** the formulation age does not restart.
5. **Given** a task that asks for a decision, **When** the person chooses "find a first step" and saves a new title, **Then** the old title is preserved in the task's notes as "Was: …" and the formulation age restarts.
6. **Given** a task that asks for a decision, **When** the person picks the stall reason "too big", **Then** "find a first step" is visually recommended. The person may still choose any decision.
7. **Given** a task that asks for a decision and has not been extended, **When** the person chooses "keep 7 more days" with a reason, **Then** the marker clears for 7 days and both the threshold and the auto-park date move 7 days later.
8. **Given** a formulation already extended once, **When** its card opens, **Then** "keep 7 more days" is not offered.
9. **Given** a task in Next, **When** the person edits only notes, tags, project, priority, due date or subtasks, **Then** its formulation age does not change.
10. **Given** a task leaves Next (done, cancelled, Waiting, Someday, Inbox) and later returns to Next, **Then** a new formulation starts at the moment of return.

---

### User Story 2 - Auto-park and a shame-free return (Priority: P1)

When the person misses reviews, Next stays honest anyway. One day before parking, a task shows "moves to Someday tomorrow". On schedule it moves to Someday, marked as parked automatically. The next time the person opens the review or the app, a "while you were away" screen lists what was parked. One tap returns a task to Next; one action returns all of them.

After 3 or more weeks without a review, the review opens in a restart mode. It offers to release everything older than 4 weeks to Someday in one reversible action, with neutral wording.

**Why this priority**: Owner decision D1. Review collapse is the main way GTD systems die, especially for ADHD users. Without auto-park the core rule only holds when a review actually happens.

**Independent Test**: Seed tasks at various ages with no review. Advance time past the "tomorrow" marker and the auto-park point. Verify the parked state and markers, the "while you were away" list, single and bulk return, and the restart offer, on each platform.

**Acceptance Scenarios**:

1. **Given** a 14-day threshold and an undecided formulation aged 20 days, **When** the person views Next, **Then** the task shows "moves to Someday tomorrow".
2. **Given** an undecided formulation aged 21 days, **When** auto-park runs, **Then** the task is in Someday, marked as auto-parked with the parking time, and keeps its project, tags, notes and due date.
3. **Given** auto-parked tasks the person has not yet seen, **When** they next open the review, **Then** the first screen is "while you were away" with each parked task and a one-tap return to Next.
4. **Given** a returned task, **Then** it is in Next with a new formulation starting at the return time.
5. **Given** a formulation reformulated, moved or extended after auto-park was scheduled, **When** auto-park runs, **Then** that task is not parked.
6. **Given** two devices that both observed the same task due for auto-park while offline, **When** both sync, **Then** the task is parked exactly once and no sync conflict is shown.
7. **Given** no completed or partial review for 21+ days, **When** the person opens the review, **Then** it starts in restart mode with the bulk-release offer. Accepting can be undone in one action.
8. **Given** the feature has just been released and a user already has old tasks in Next, **Then** none of those tasks is auto-parked earlier than 14 days after the feature first becomes active for that user.

---

### User Story 3 - The AI navigator proposes a first step (Priority: P2)

From the decision card, during "find a first step" or "reformulate", the person asks for a suggestion. The navigator proposes 1–3 concrete first steps. It takes into account the task's title, notes, project and the chosen stall reason. The person picks one, edits it if needed, and confirms. Nothing is written without confirmation.

For a project without a next action, the same navigator proposes a first next action.

On iPhone and Mac the navigator uses Apple's on-device model: nothing leaves the device and it works offline. When the on-device model is unavailable, the person is told so and offered the server provider under a separate one-time consent. On web the server provider is used under the same one-time consent.

**Why this priority**: Owner decision D4. Proposing a first step is what the competitor brief identifies as the unoccupied "AI suggests, you decide" position. The rule (US1/US2) is valuable without it, so it is P2.

**Independent Test**: With a stubbed on-device model and a stubbed server provider, request suggestions for seeded stalled tasks. Verify 1–3 proposals, no write before confirmation, the consent flow, fallback messaging, offline behaviour, and that no task content reaches logs.

**Acceptance Scenarios**:

1. **Given** an Apple device with the on-device model available, **When** the person taps "suggest" on a stalled task, **Then** 1–3 first-step proposals appear in the task's language, without any server request and without a consent prompt. A short note says they come from the on-device model.
2. **Given** a proposal, **When** the person picks it, **Then** it fills the title field for editing. The task changes only after the person confirms.
3. **Given** the person dismisses all proposals, **Then** the task is unchanged.
4. **Given** an Apple device where the on-device model is unavailable (unsupported device, Apple Intelligence off, or unsupported task language), **When** the person taps "suggest", **Then** they are told the on-device model is unavailable and why. They are offered the named server provider, which requires consent first.
5. **Given** web with no prior consent, **When** the person taps "suggest", **Then** a consent screen names the provider and lists what is sent (title, notes, project, chosen reason). Declining leaves the card fully usable without AI.
6. **Given** consent was revoked in settings, **When** the person taps "suggest" with the server provider, **Then** no request is sent and the consent screen appears again.
7. **Given** the task has too little information to propose a grounded step, **Then** the navigator asks one clarifying question instead of inventing facts about the person's life (names, places, amounts not present in the task).
8. **Given** a project without a next action, **When** the person asks for a suggestion, **Then** 1–3 proposals for a first next action appear, and confirming one creates it in Next in that project.
9. **Given** the server provider fails, times out or hits the cost cap, **Then** the person sees an actionable message with a correlation ID and can continue without AI.

---

### User Story 4 - The guided weekly review (Priority: P2)

The person starts the review in one of two modes.

**Quick (~5 min)**:
1. wins of the week;
2. Inbox to zero;
3. tasks that ask for a decision;
4. summary.

**Full (~20 min)**, the classic GTD Get Clear / Get Current / Get Creative:
1. wins of the week;
2. mind sweep (capture anything on their mind);
3. Inbox to zero;
4. tasks that ask for a decision;
5. the rest of Next, with a capacity mirror;
6. Waiting items older than 7 days;
7. projects without a next action;
8. a short pass over Someday;
9. dates in the next 14 days;
10. summary.

Every step can be skipped. The review can be left and resumed later, and a partial review counts. The summary asks one question: "Clear how to start the week? yes / not really".

**Why this priority**: This turns the rule into a weekly practice. It depends on US1, and its decision step reuses the card.

**Independent Test**: Seed a realistic task set and run both modes end-to-end. Verify each step's content, skip/resume, partial completion, the capacity mirror numbers, and the stored summary and answer.

**Acceptance Scenarios**:

1. **Given** completed tasks this week, **When** the review starts, **Then** the first step lists them with their count, before any backlog is shown.
2. **Given** more than 15 Inbox items, **When** the Inbox step opens, **Then** the person can choose to process 10 now, process all, or release the rest to Someday. Items are processed one at a time.
3. **Given** tasks that ask for a decision, **When** the decision step runs, **Then** they appear one card at a time, oldest first, with the same card as US1.
4. **Given** 41 tasks in Next and an average of 9 completions per week over the last 4 weeks, **When** the full review shows the rest of Next, **Then** it states the count, the weekly average and roughly how many weeks of work that is. No limit is enforced.
5. **Given** a Waiting item older than 7 days, **When** the Waiting step runs, **Then** the person can keep waiting (it returns in 7 days unless it changes), create a follow-up next action, return it to Next with an editable title, or cancel it.
6. **Given** a Someday item not reviewed in 30 days, **When** the Someday step runs, **Then** at most 7 such items are shown. The person can keep (it returns in 30 days unless it changes), move to Next with a concrete title, or cancel.
7. **Given** a review left at step 4, **When** the person returns on the same or another device, **Then** it resumes at step 4 with earlier decisions kept.
8. **Given** a review the person ends early, **Then** it is recorded as partial and counts toward review regularity.
9. **Given** the summary, **Then** it shows counts per decision (done, reformulated, first step, Waiting, Someday, cancelled, extended, Inbox processed) and the date of the next scheduled review.
10. **Given** the review step lists, **Then** no screen shows more than one decision at a time in steps 3, 4, 6 and 8.

---

### User Story 5 - Schedule, cue, onboarding and settings (Priority: P3)

Before the first review, one onboarding screen explains why the review exists, the threshold rule and auto-park. On the same screen the person picks a review day and time (default Friday 16:00, local time) and a threshold (7/14/21/28, default 14).

On the chosen day the person gets one notification. On iOS, the Next Actions widget shows how many tasks ask for a decision. "Last review: 9 days ago" is shown in neutral wording. There are no streaks. Settings allow changing the day, time, threshold and AI consent.

**Why this priority**: These are the cues that keep the habit going. The review works without them (US4 can be opened any time), so they come after the core.

**Independent Test**: Complete onboarding, change settings, advance time to the review slot. Verify exactly one notification, widget counts, neutral wording, and the effect of a threshold change on markers.

**Acceptance Scenarios**:

1. **Given** a person who has never reviewed, **When** they open the review, **Then** the onboarding screen appears once, with default Friday 16:00 local and threshold 14, both changeable.
2. **Given** a review slot passes without a review, **Then** exactly one notification is sent for that week. There is no follow-up reminder.
3. **Given** 3 tasks ask for a decision, **Then** the iOS Next Actions widget shows 3.
4. **Given** the person changes the threshold from 28 to 7, **Then** markers update at once. No task is auto-parked earlier than 7 days after the change because of that change.
5. **Given** the person changes their time zone, **Then** the review slot follows the new local time.
6. **Given** any review-related screen or message, **Then** none shows a streak, a streak loss, red error styling for age, or the word "overdue" for formulation age.

---

### User Story 6 - The same review on Mac (Priority: P3)

The Mac app offers the same markers, card, auto-park visibility, review and on-device navigator over the same synced tasks as iPhone and web.

**Why this priority**: The owner put macOS in scope. It depends on a separate Mac↔backend sync capability, which the Mac app lacks today, so the Mac part ships last. iOS and web do not wait for it.

**Independent Test**: With Mac sync available, run US1–US5 acceptance scenarios on Mac against the same account and verify cross-device consistency with iOS and web.

**Acceptance Scenarios**:

1. **Given** Mac sync is available and a task was reviewed on iPhone, **When** the Mac app syncs, **Then** it shows the same task state, formulation age and review summary.
2. **Given** the Mac app without Mac sync, **Then** the Weekly Review entry stays visibly "coming later" on Mac. No local-only review is shipped.

---

### Edge Cases

- **Offline for a long time (iOS/Mac)**: markers are computed on the device from the local clock. Auto-park found due on the device is applied locally and reconciled with the server without duplicates (US2-6). A server-side park that arrives while the device has pending local decisions for the same task resolves in favour of the person's explicit decision when it was made before the park time; otherwise the person sees the task in "while you were away".
- **Clock skew**: a device clock ahead of or behind the server must not park a task early. The server's park time is authoritative once synced.
- **Account-less iOS use**: the whole feature works locally (including auto-park and on-device AI). Server-only parts (server AI, cross-device resume) are unavailable and say so.
- **Task with a due date in Next**: subject to the same rule. A due date does not stop the clock or exempt the task.
- **Task in an archived project**: auto-park still moves it to Someday. Returning it to Next requires restoring the project first, consistent with existing project rules.
- **Recurring or repeatedly reformulated tasks**: when the same task asks for a decision for the third consecutive formulation, the card gently offers Someday or examining the problem on the thinking canvas, without blocking any decision.
- **Huge backlog on first use**: the post-release grace period (US2-8) and restart mode prevent dozens of tasks from asking at once on day one.
- **Concurrent edits**: a decision made on one device against a task that changed elsewhere is rejected as stale and shown again with current data. It is never silently applied to the wrong formulation.
- **Server AI failures**: consent denied, consent revoked mid-session, provider timeout, cost cap reached, malformed response. Each fails visibly with a correlation ID and leaves the card usable.
- **On-device AI unavailable mid-session** (model downloading, Apple Intelligence turned off): same fallback as US3-4.
- **Interrupted review** (app killed, phone call, device switch): progress and decisions made so far are kept; resume works (US4-7).
- **Threshold changed during an open review**: the decision step's list is not reshuffled under the person. New markers apply on the next visit to the step.

## Requirements *(mandatory)*

### Functional Requirements

**Formulation clock and markers**

- **FR-001**: System MUST record, for every task in Next, when its current formulation started. The start is set when a task is created in Next, moved or reopened into Next, or returned from auto-park, and when its title changes substantively while in Next.
- **FR-002**: A title change MUST count as substantive only if the titles differ after ignoring letter case, surrounding and repeated whitespace, and punctuation.
- **FR-003**: Edits to notes, tags, project, priority, due date or subtasks MUST NOT change the formulation start.
- **FR-004**: System MUST show each Next task as **fresh** (age below half the threshold), **ageing** (half the threshold or more), **asks for a decision** (threshold or more) or **moves to Someday tomorrow** (within 24 hours of auto-park). It MUST NOT use error colouring or the word "overdue" for formulation age.
- **FR-005**: System MUST count how many consecutive formulations of the same task reached "asks for a decision", and offer Someday or the thinking canvas on the third, without blocking any decision.

**Decision card**

- **FR-006**: For a task that asks for a decision, users MUST be able to choose: done; reformulate; find a first step; move to Waiting (with who/what); release to Someday; cancel; or keep 7 more days.
- **FR-007**: Users MUST be able to optionally record a stall reason: unclear, too big, missing information, waiting on someone, unpleasant/no energy, no longer matters. Choosing a reason MUST visually recommend a fitting decision without restricting choice.
- **FR-008**: "Find a first step" MUST preserve the previous title in the task's notes as "Was: <old title>" and start a new formulation.
- **FR-009**: "Keep 7 more days" MUST require a reason, MUST be available once per formulation, and MUST shift both the threshold and the auto-park point by 7 days.
- **FR-010**: The decision card MUST be reachable from the task itself on any day, not only inside a review, and decisions made there MUST be recorded the same way as in-review decisions.
- **FR-011**: Every decision MUST be applied through the existing idempotent, owner-serialized task operations and MUST be rejected as stale if the task changed since the card was shown.

**Auto-park and return**

- **FR-012**: System MUST move an undecided formulation from Next to Someday when its age reaches threshold + 7 days (or + 14 days if extended), preserving project, tags, notes and due date, and marking it as parked automatically with the time.
- **FR-013**: Auto-park MUST NOT apply to a task whose formulation, state or extension changed after the park became due. Applying it twice to the same formulation MUST have no additional effect and MUST NOT create a sync conflict.
- **FR-014**: Auto-park MUST run whether or not any client is open, for accounts with server sync, and on-device for account-less iOS use.
- **FR-015**: System MUST show auto-parked tasks the person has not yet seen on a "while you were away" screen at the next review or app open, with one-tap return per task and a return-all action. Returned tasks start a new formulation.
- **FR-016**: For tasks already in Next when the feature first becomes active for a user, System MUST NOT auto-park any of them earlier than 14 days after that moment.
- **FR-017**: When no review (complete or partial) happened for 21 days or more, the next review MUST open in restart mode. It offers one reversible action that releases every Next task older than 4 weeks to Someday.
- **FR-018**: The only automatic change to a task's GTD state this feature makes is Next → Someday auto-park. No other task change happens without the person's action.

**AI navigator**

- **FR-019**: On request from the decision card or for a project without a next action, System MUST produce 1–3 proposed first steps in the task's language, using the task's title, notes, project and optional stall reason.
- **FR-020**: A proposal MUST NOT be written to any task until the person confirms it, optionally after editing.
- **FR-021**: Proposals MUST NOT introduce personal facts (people, places, amounts, dates) absent from the task. When information is insufficient, the navigator asks one clarifying question instead.
- **FR-022**: On iOS and macOS, System MUST use Apple's on-device model when it is available. In that case no task content leaves the device, and the feature works offline.
- **FR-023**: When the on-device model is unavailable (unsupported device, Apple Intelligence off, model not ready, unsupported language), System MUST say so and why. It MAY then offer the server provider, subject to FR-024.
- **FR-024**: Every server-provider request (web, and the Apple-platform fallback) MUST be preceded by a one-time consent that names the provider and lists the data sent. Consent MUST be revocable in settings, and a revoked consent MUST stop requests immediately.
- **FR-025**: Server-provider requests MUST respect existing provider cost caps. Failures (timeout, cap, provider error, malformed output) MUST be shown with a correlation ID and leave the review usable without AI.
- **FR-026**: System MUST record whether a confirmed decision used an AI proposal (used as-is, edited, or not used), without storing the proposal text in logs or metrics.

**Guided review**

- **FR-027**: Users MUST be able to start a quick or full review at any time, regardless of the schedule.
- **FR-028**: The quick review MUST consist of: wins of the week, Inbox to zero, decisions, summary. The full review MUST consist of: wins, mind sweep, Inbox to zero, decisions, rest of Next with capacity mirror, Waiting older than 7 days, projects without a next action, Someday pass (at most 7 items not reviewed in 30 days), dates in the next 14 days, summary.
- **FR-029**: Every step MUST be skippable, the review MUST be resumable on any of the user's devices, and an ended-early review MUST be recorded as partial.
- **FR-030**: The Inbox step MUST offer "10 now / all / release the rest to Someday" when Inbox holds more than 15 items.
- **FR-031**: The capacity mirror MUST state the Next count, the average weekly completions over the last 4 weeks, and the implied number of weeks. It MUST NOT enforce any limit.
- **FR-032**: "Keep waiting" and "keep in Someday" MUST hide the item from those steps for 7 and 30 days respectively, unless the task changes earlier.
- **FR-033**: The summary MUST show counts per decision type and the next scheduled review, and ask once "Clear how to start the week? yes / not really". The answer is optional.
- **FR-034**: Steps that involve decisions (Inbox, decisions, Waiting, Someday) MUST present one item at a time.

**Schedule, cue, onboarding, settings**

- **FR-035**: Before the first review, System MUST show one onboarding screen explaining the review, the threshold rule and auto-park, and collecting review day/time (default Friday 16:00 local) and threshold (7/14/21/28, default 14).
- **FR-036**: System MUST send at most one review notification per week, at the chosen local day and time, with no follow-ups.
- **FR-037**: The iOS Next Actions widget MUST show the number of tasks that ask for a decision.
- **FR-038**: System MUST show the time since the last review in neutral wording, and MUST NOT show streaks or streak loss.
- **FR-039**: Changing the threshold MUST update markers immediately, and MUST NOT cause any task to be auto-parked earlier than 7 days after the change.

**Platforms and parity**

- **FR-040**: iOS and web MUST offer US1–US5 with equivalent behaviour over the same account. iOS MUST support every non-server part offline.
- **FR-041**: macOS MUST offer US1–US5 over the same synced account once Mac↔backend sync exists. Until then, the Mac Weekly Review entry MUST remain visibly "coming later".
- **FR-042**: The existing disabled "Weekly review — coming soon" entries on web and iOS MUST be replaced by the working entry when the feature is active.

**Data, privacy, observability**

- **FR-043**: Review sessions, decisions (including stall reasons and optional reason text), receipts, settings and AI consent MUST be stored per owner, included in the account ZIP export, and removed by account purge.
- **FR-044**: Logs, metrics and events MUST contain only identifiers, decision and reason codes, counts, timings and stage names. They MUST NOT contain task titles, notes, reason text or AI input/output.
- **FR-045**: Every server response for this feature MUST carry the correlation ID, and every user-visible failure MUST show it.

### Key Entities *(include if feature involves data)*

- **Formulation clock** (on a task): when the current formulation started, how many consecutive formulations reached the threshold, and whether the one-time extension was used.
- **Park marker** (on a task): whether and when the task was parked, whether by the person or automatically, and whether the person has seen it on "while you were away".
- **Review session**: one review by one owner. Holds mode (quick/full), status (open, completed, partial), start and end times, current step for resume, per-decision counts, and the optional "clear start" answer.
- **Review decision**: one decision on one task. Holds the decision type, optional stall reason and reason text, whether an AI proposal was used, the time, and optionally the review session it belongs to (decisions can be made outside a review).
- **Review receipt**: "keep waiting" or "keep in Someday" for one task, with the date until which it stays out of the step.
- **Review settings**: review day, time, time zone and threshold per owner.
- **AI navigator consent**: per owner and provider; when granted and when revoked.

## Success Criteria *(mandatory)*

### Measurable Outcomes

Measured per active user over the first 8 weeks after their first review.

- **SC-001**: Users complete at least a partial review in at least 3 of every 4 weeks.
- **SC-002**: Immediately after every completed review, 0 Next formulations older than the user's threshold remain without a decision.
- **SC-003**: At least 70% of answered reviews end with "clear how to start the week: yes".
- **SC-004**: On the owner's real task set, the median quick review takes 5 minutes or less and the median full review 20 minutes or less.
- **SC-005**: On the owner's stalled tasks, at least 50% of AI first-step proposals are accepted (as-is or edited). In a reviewed evaluation set, 0 proposals introduce personal facts absent from the task.
- **SC-006**: 100% of auto-parked tasks show "moves to Someday tomorrow" for at least the preceding 24 hours, appear on the next "while you were away" screen, and can be returned in one action.
- **SC-007**: A review completed offline on iOS loses 0 decisions after sync, and its summary is visible on web.

## Assumptions

- Persona: a broad audience of GTD practitioners and newcomers, with users with ADHD as the design centre. The product is not positioned as "an ADHD app".
- Language follows the rest of the product today. AI answers in the task's language. Full localisation is out of scope.
- Apple's on-device model requires iOS 26 / macOS 26 on an Apple Intelligence-capable device with Apple Intelligence enabled. Whether it supports Russian is **unverified** (checked 2026-10-05). If it does not, Russian-language tasks use the consented server fallback on Apple platforms.
- The server provider and per-call budget for the navigator reuse the existing provider and cost-cap configuration; the exact choice is a planning decision.
- Waiting and Someday review behaviour (7- and 30-day receipts) follows the macOS POC pattern, with Someday lengthened from 7 to 30 days to reduce noise.
- Mac↔backend sync is delivered as a separate feature spec; US6 depends on it.
- This feature requires superseding or amending ADR-0006 (Weekly Review deferred, no cadence or due state, D-11), ADR-0001's capture-based review model, and the macOS POC principle that review never changes GTD state automatically. That will be recorded in a new ADR during planning.

## Out of Scope

- "Weekly focus" (choosing a handful of tasks for the week).
- Any hard or soft limit on the number of Next tasks.
- Streaks, points, badges or other gamification.
- Voice-led review (ADR-0002 `weekly_review_voice`).
- Review of work delegated to external agents (relay, spec 007).
- Defer/start dates ("tickler"), time blocking, calendar integration, time estimates.
- Any automatic task change other than Next → Someday auto-park.
- Repeated or escalating reminders.
- Full app localisation and in-app GTD training beyond one onboarding screen.
- Mac↔backend sync itself (separate spec).
