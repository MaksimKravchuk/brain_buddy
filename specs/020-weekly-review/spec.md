# Feature Specification: Weekly Review

**Feature Branch**: `020-weekly-review`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "A weekly review that keeps Next Actions executable: no formulation stays in Next longer than a user-chosen threshold without a decision; a guided, shame-free review for GTD practitioners and newcomers with ADHD as the design centre; an AI navigator that proposes a first step; auto-park to Someday when a review is missed; full parity on iOS, web and (after Mac sync) macOS." Business requirements: [intake.md](./intake.md). Concept and owner decisions: [`.specify/assessments/weekly-review/concept.md`](../../.specify/assessments/weekly-review/concept.md).

## Primary loop impact

This feature implements the **smart Weekly Review** stage of the constitution's primary loop (capture → clarify → organize → **review** → evidence) for native tasks. It feeds back into clarify (reformulate, find a first step) and organize (Waiting, Someday, cancel). Voice-led review (ADR-0002 `weekly_review_voice`) and review of agent-delegated work remain later phases and are not part of this spec.

## Vocabulary

- **Formulation**: a task's title while the task is in Next. A substantive title change starts a new formulation. Moving the task into Next also starts a new one.
- **Formulation age**: time since the current formulation started. For a task with a future due date, it is time since the later of the formulation start and the start of the due date (FR-046).
- **Threshold**: the user-chosen age (7, 14, 21 or 28 days; default 14) after which a formulation **asks for a decision**.
- **Asks for a decision**: a derived marker, not a list. ADR-0006's four open lists are unchanged.
- **Auto-park**: the system moves a formulation that is still undecided **7 days after the threshold** from Next to Someday.
- **Extension**: a one-time, reasoned "keep 7 more days" for one formulation.
- **On-device model**: Apple's built-in model, or a separately downloaded model that runs on the device (FR-023). No task content leaves the device.
- **Cloud provider**: a remote AI provider, used only with consent (FR-024).

## Clarifications

### Session 2026-10-05

- Q: If Apple's on-device model does not support Russian, what does the navigator do with Russian-language tasks on iPhone and Mac? → A: Offer a choice: download a separate on-device model that supports the language, or use the cloud provider under consent.
- Q: What counts as a partial review for regularity and for postponing restart mode? → A: A review in which at least one item decision was made (Inbox, decision card, Waiting or Someday), or at least one step was finished that had nothing to decide. Merely opening the review does not count.
- Q: What data does the navigator see when proposing a first step? → A: The task's title, notes and chosen stall reason, the project name, and the titles of up to 20 other open tasks in the same project. The same set applies to on-device and cloud, and it is exactly what the cloud consent lists.
- Q: How is a Next task with a future due date treated? → A: Its clock is paused until the due date. Formulation age counts from the later of the formulation start and the start of the due date (local day). Such a task never ages, asks for a decision or gets auto-parked before its due date.
- Q: After "keep in Someday", how many days until the item reappears in the Someday step? → A: 30 days, unless the task changes earlier. At most 7 items are shown per review.

### Session 2026-10-06

Owner answers to the three product decisions raised by planning-review campaign 1 (`020-weekly-review-c1`).

- Q: What should the review summary show for decisions that have no counter among the eight listed (keep waiting, create a follow-up, return to Next from Waiting or Someday, keep in Someday)? → A: Add exactly two counters. "Kept as is" counts keep waiting and keep in Someday. "Moved to Next" counts creating a follow-up and returning a task to Next from Waiting or Someday. The summary therefore shows ten counts (FR-033, US4-9).
- Q: Does a review in which the person skips every step and then taps Done count as a completed review? → A: The person sees "Review done" without shame, but the review is recorded as **completed without activity**. It does not count toward regularity (SC-001), does not postpone restart mode (FR-017) and does not suppress the weekly notification (FR-036). FR-029 defines completed, completed without activity, partial and abandoned.
- Q: May auto-park run for a person who has not yet seen an explanation of it, and when does the 14-day grace for existing Next tasks start? → A: After the feature is activated, the first time the person opens the app (iOS) or the web, a short one-time explainer of the threshold rule and auto-park is shown, independent of the review onboarding (FR-051). The 14-day grace for existing Next tasks starts at that moment, per owner and per account. The first acknowledgement on any device wins and is recorded on the server; account-less iOS records it on the device. Auto-park never runs for an owner who has not seen the explainer (FR-014, FR-016).
- Q: Does a review completed without activity update "Last review: N days ago"? → A: No. The line follows the same counted-review rule as regularity, restart mode and the notification (FR-038).
- Q: Is it intended that restart mode mostly affects tasks kept in Next by an extension, a Waiting period or a passed due date, and that undoing its bulk release stays possible until the person leaves the restart screen, even across an app kill or reload? → A: Yes, confirmed as designed (FR-017).

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
2. **Given** a task in Next for 9 days with a 14-day threshold, **When** the person views Next, **Then** the list shows no marker for it, and its task detail shows "ageing". **Given** 3 days, **Then** neither the list nor the detail shows an age marker.
3. **Given** a task that asks for a decision, **When** the person reformulates it with a substantively different title, **Then** the task stays in Next, its formulation age restarts at zero, and its marker disappears.
4. **Given** a task that asks for a decision, **When** the person changes only letter case, whitespace or punctuation of the title, **Then** the formulation age does not restart.
5. **Given** a task that asks for a decision, **When** the person chooses "find a first step" and saves a new title, **Then** the old title is preserved in the task's notes as "Was: …" and the formulation age restarts.
6. **Given** a task that asks for a decision, **When** the person picks the stall reason "too big", **Then** "find a first step" is visually recommended. The person may still choose any decision.
7. **Given** a task that asks for a decision and has not been extended, **When** the person chooses "keep 7 more days" with a reason, **Then** the marker clears for 7 days from the day of the extension. The task asks again 7 days after the extension day and is auto-parked 14 days after it (for example, extended on day 18 with a 14-day threshold: asks again on day 25, parked on day 32).
8. **Given** a formulation already extended once, **When** its card opens, **Then** "keep 7 more days" is not offered.
9. **Given** a task in Next, **When** the person edits only notes, tags, project, priority or subtasks, **Then** its formulation age does not change.
9a. **Given** a task in Next for 20 days with a due date 10 days from now, **When** the person views Next, **Then** it shows no age marker. Auto-park does not happen before the due date. On the due date its age counts from that day.
10. **Given** a task leaves Next (done, cancelled, Waiting, Someday, Inbox) and later returns to Next, **Then** a new formulation starts at the moment of return.

---

### User Story 2 - Auto-park and a shame-free return (Priority: P1)

When the person misses reviews, Next stays honest anyway. One day before parking, a task shows "moves to Someday tomorrow". On schedule it moves to Someday, marked as parked automatically. The next time the person opens the review or the app, a "while you were away" screen lists what was parked. One tap returns a task to Next; one action returns all of them.

After 3 or more weeks without a review, the review opens in a restart mode. It offers to release everything older than 4 weeks to Someday in one reversible action, with neutral wording.

**Why this priority**: Owner decision D1. Review collapse is the main way GTD systems die, especially for ADHD users. Without auto-park the core rule only holds when a review actually happens.

**Independent Test**: Seed tasks at various ages with no review. Advance time past the "tomorrow" marker and the auto-park point. Verify the parked state and markers, the "while you were away" list at app open, and single and bulk return, on each platform. The parts that need the guided review itself — "while you were away" as the first review screen (scenario 3) and restart mode (scenario 7) — are verified with User Story 4, which delivers the review.

**Acceptance Scenarios**:

1. **Given** a 14-day threshold and an undecided formulation aged 20 days, **When** the person views Next, **Then** the task shows "moves to Someday tomorrow".
2. **Given** an undecided formulation aged 21 days, **When** auto-park runs, **Then** the task is in Someday, marked as auto-parked with the parking time, and keeps its project, tags, notes and due date.
3. **Given** auto-parked tasks the person has not yet seen, **When** they next open the review, **Then** the first screen is "while you were away" with each parked task and a one-tap return to Next.
4. **Given** a returned task, **Then** it is in Next with a new formulation starting at the return time.
5. **Given** a formulation reformulated, moved or extended after auto-park was scheduled, **When** auto-park runs, **Then** that task is not parked.
6. **Given** two devices that both observed the same task due for auto-park while offline, **When** both sync, **Then** the task is parked exactly once and no sync conflict is shown.
7. **Given** no completed or partial review for 21+ days (counted from onboarding for a person who has never had one, FR-017), **When** the person opens the review, **Then** it starts in restart mode with the bulk-release offer. Accepting can be undone in one action.
8. **Given** the feature has just been activated for a user who already has old tasks in Next, **When** they first open the app or the web, **Then** a one-time explainer of the rule and auto-park appears (FR-051). No task is auto-parked before the person has seen it, and none of those tasks is auto-parked earlier than 14 days after that moment.

---

### User Story 3 - The AI navigator proposes a first step (Priority: P2)

From the decision card, during "find a first step" or "reformulate", the person asks for a suggestion. The navigator proposes 1–3 concrete first steps. It takes into account the task's title, notes and chosen stall reason, and the project with its other open tasks (FR-019). The person picks one, edits it if needed, and confirms. Nothing is written without confirmation.

For a project without a next action, the same navigator proposes a first next action.

On iPhone (and on the Mac once Mac sync exists, FR-041) the navigator uses Apple's on-device model: nothing leaves the device and it works offline. When Apple's model is unavailable (for example, it does not support the task's language), the person is told so and chooses between:
- downloading a separate on-device model that supports the language (its size is shown; afterwards nothing leaves the device);
- using the cloud provider under a separate one-time consent.

On web the cloud provider is used under the same one-time consent.

**Why this priority**: Owner decision D4. Proposing a first step is what the competitor brief identifies as the unoccupied "AI suggests, you decide" position. The rule (US1/US2) is valuable without it, so it is P2.

**Independent Test**: With a stubbed on-device model and a stubbed cloud provider, request suggestions for seeded stalled tasks. Verify 1–3 proposals, no write before confirmation, the consent flow, fallback messaging, offline behaviour, and that no task content reaches logs.

**Acceptance Scenarios**:

1. **Given** an Apple device with the on-device model available, **When** the person taps "suggest" on a stalled task, **Then** 1–3 first-step proposals appear in the task's language, without any server request and without a consent prompt. A short note says they come from the on-device model.
2. **Given** a proposal, **When** the person picks it, **Then** it fills the title field for editing. The task changes only after the person confirms.
3. **Given** the person dismisses all proposals, **Then** the task is unchanged.
4. **Given** an Apple device where Apple's on-device model is unavailable (unsupported device, Apple Intelligence off, or unsupported task language), **When** the person taps "suggest", **Then** they are told why and offered two choices:
   - download a separate on-device model, with its download size shown, if the device can run it;
   - use the named cloud provider, which requires consent first.

   Choosing neither leaves the card fully usable without AI.
4a. **Given** the person chose to download the separate on-device model, **When** the download completes, **Then** suggestions for that language run on the device without any server request, including offline. The person can delete the model in settings to free space.
4b. **Given** the download is interrupted or there is not enough storage, **Then** the person sees why, can retry or switch to the cloud choice, and the card stays usable.
5. **Given** web with no prior consent, **When** the person taps "suggest", **Then** a consent screen names the provider and lists what is sent (title, notes, chosen reason, project name, and titles of up to 20 other open tasks in the project). Declining leaves the card fully usable without AI.
6. **Given** consent was revoked in settings, **When** the person taps "suggest" with the cloud provider, **Then** no request is sent and the consent screen appears again.
7. **Given** the task has too little information to propose a grounded step, **Then** the navigator asks one clarifying question instead of inventing facts about the person's life (names, places, amounts not present in the task).
8. **Given** a project without a next action, **When** the person asks for a suggestion, **Then** 1–3 proposals for a first next action appear, and confirming one creates it in Next in that project.
9. **Given** the cloud provider fails, times out or hits the cost cap, **Then** the person sees an actionable message with a correlation ID and can continue without AI.

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
2. **Given** more than 15 Inbox items, **When** the Inbox step opens, **Then** the person can choose to process 10 now, process all, or process 10 now and then release the remainder to Someday (FR-030). Items are processed one at a time.
3. **Given** tasks that ask for a decision, **When** the decision step runs, **Then** they appear one card at a time, earliest-asking first (FR-004), with the same card as US1. "Not now" sets a card aside without a decision: the task keeps asking and its auto-park schedule is unchanged.
4. **Given** 41 tasks in Next and an average of 9 completions per week over the last 4 weeks, **When** the full review shows the rest of Next, **Then** it states the count, the weekly average and roughly how many weeks of work that is. No limit is enforced.
5. **Given** a Waiting item older than 7 days, **When** the Waiting step runs, **Then** the person can keep waiting (it returns in 7 days unless it changes), create a follow-up next action, return it to Next with an editable title, or cancel it.
6. **Given** a Someday item not reviewed in 30 days, **When** the Someday step runs, **Then** at most 7 such items are shown. The person can keep (it returns in 30 days unless it changes), move to Next with a concrete title, or cancel.
7. **Given** a review left at step 4, **When** the person returns on the same or another device, **Then** it resumes at step 4 with earlier decisions kept.
8. **Given** a review the person leaves after making at least one decision, **Then** it stays open and resumable, counts toward review regularity from its last activity, and is recorded as partial once it is replaced by a new review or has been idle for 7 days (FR-029).
8a. **Given** a review the person opens and leaves without any decision or finished step, **Then** it does not count toward regularity, and it is recorded as abandoned once it is replaced by a new review or has been idle for 7 days.
8b. **Given** a review in which the person skips every step and taps Done on the summary, **Then** they see "Review done" with no reproach, and the review is recorded as completed without activity: it does not count toward regularity, does not postpone restart mode and does not suppress the next weekly notification (FR-029).
9. **Given** the summary, **Then** it shows ten counts (done, reformulated, first step, Waiting, Someday, cancelled, extended, Inbox processed, kept as is, moved to Next) and the date of the next scheduled review. "Kept as is" counts keep waiting and keep in Someday; "Moved to Next" counts follow-ups created and tasks returned to Next from Waiting or Someday.
10. **Given** the Inbox, decision, Waiting and Someday steps (FR-034), **Then** no screen in them shows more than one decision at a time.

---

### User Story 5 - Schedule, cue, onboarding and settings (Priority: P3)

Before the first review, one onboarding screen explains why the review exists, the threshold rule and auto-park. On the same screen the person picks a review day and time (default Friday 16:00, local time) and a threshold (7/14/21/28, default 14).

On the chosen day the person gets one notification. On iOS, the Next Actions widget shows how many tasks ask for a decision. "Last review: 9 days ago" is shown in neutral wording. There are no streaks. Settings allow changing the day, time, threshold and AI consent.

**Why this priority**: These are the cues that keep the habit going. The review works without them (US4 can be opened any time), so they come after the core.

**Independent Test**: Complete onboarding, change settings, advance time to the review slot. Verify exactly one notification, widget counts, neutral wording, and the effect of a threshold change on markers.

**Acceptance Scenarios**:

1. **Given** a person who has never reviewed, **When** they open the review, **Then** the onboarding screen appears once, with default Friday 16:00 local and threshold 14, both changeable.
2. **Given** no review in the preceding 6 days, **When** the review slot arrives, **Then** exactly one notification is sent for that week. There is no follow-up reminder. **Given** a partial or complete review on Wednesday, **Then** no notification is sent that Friday.
3. **Given** 3 tasks ask for a decision, **Then** the iOS Next Actions widget shows 3. In the medium and large widget, tapping the count opens the review's decision step at the first card. Tapping the small widget opens Next.
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
2. **Given** the Mac app without Mac sync, **Then** it shows a non-interactive "Weekly review · coming later" entry (new; the Mac has no such entry today, FR-041). No local-only review is shipped.

---

### Edge Cases

- **Offline for a long time (iOS/Mac)**: markers are computed on the device from the local clock. Auto-park found due on the device is applied locally and reconciled with the server without duplicates (US2-6). A server-side park that arrives while the device has pending local decisions for the same task resolves in favour of the person's explicit decision when it was made before the park time; otherwise the person sees the task in "while you were away". An explicit decision here means a decision-card decision (FR-006). Other pending edits (notes, tags, a plain move) are applied to the task as it now is and do not undo the park.
- **Clock skew**: a device clock ahead of or behind the server must not park a task early. The server's park time is authoritative once synced.
- **Account-less iOS use**: the whole feature works locally (including auto-park and on-device AI). Server-only parts (cloud AI, cross-device resume) are unavailable and say so. Exposure is staged: as signed-in accounts get the feature only when its flag is switched on for them, account-less use has its own release switch, because account-less auto-park has no remote way to stop it. That switch stays off in released builds until the owner turns it on after the synced path has run cleanly for one full threshold cycle (plan PR-14); until then account-less behaviour is verified in development builds and package tests, and released account-less builds keep the existing "coming later" entry (FR-042).
- **Task with a due date in Next**: the clock is paused until the due date (FR-046). From the due date on, the normal rule applies. A due date that keeps being pushed forward is a known way to defer the rule. The supporting metrics count how often due dates on Next tasks are moved, to watch for this, but the system does not block it.
- **Task in an archived project**: today, archiving a project clears the project from its tasks on backend and iOS, so this state cannot occur yet (ADR-0020's lossless archive is accepted but not implemented). Once lossless archive exists, the rule is: auto-park still moves such a task to Someday, and returning it to Next requires restoring the project first.
- **Recurring or repeatedly reformulated tasks**: when the same task asks for a decision for the third consecutive formulation, the card gently offers Someday or examining the problem on the thinking canvas, without blocking any decision.
- **Huge backlog on first use**: when the person first sees the explainer (FR-051), the age of every task already in Next starts counting from that moment. So nothing asks for a decision before the threshold has passed since then, and nothing is auto-parked earlier than 14 days after it (FR-016, US2-8). Restart mode handles a Next that is still stale later.
- **Concurrent edits**: a decision made on one device against a task that changed elsewhere is rejected as stale and shown again with current data. It is never silently applied to the wrong formulation.
- **Cloud AI failures**: consent denied, consent revoked mid-session, provider timeout, cost cap reached, malformed response. Each fails visibly with a correlation ID and leaves the card usable.
- **On-device AI unavailable mid-session** (model downloading, Apple Intelligence turned off): same fallback as US3-4.
- **Interrupted review** (app killed, phone call, device switch): progress and decisions made so far are kept; resume works (US4-7). Typed but unsaved text is kept as a draft or guarded by a warning (FR-052).
- **Review continued on two devices**: a review left open on one device and continued or replaced on another tells the person so when they return to the first one. Decisions already made on either device are kept.
- **Threshold changed during an open review**: the decision step's list is not reshuffled under the person. New markers apply on the next visit to the step.

## Requirements *(mandatory)*

### Functional Requirements

**Formulation clock and markers**

- **FR-001**: System MUST record, for every task in Next, when its current formulation started. The start is set when a task is created in Next, moved or reopened into Next, or returned from auto-park, and when its title changes substantively while in Next.
- **FR-002**: A title change MUST count as substantive only if the titles differ after ignoring letter case, surrounding and repeated whitespace, and punctuation. When the person saves a cosmetic-only change anyway ("Save anyway"), it is still recorded as a reformulate decision on the current formulation: the decision step moves on to the next card, and the task keeps asking for a decision with its clock unchanged.
- **FR-003**: Edits to notes, tags, project, priority, due date or subtasks MUST NOT change the formulation start.
- **FR-046**: For a task with a due date, formulation age MUST be measured from the later of the formulation start and the start of the due date in the user's local time zone. A task whose due date is in the future therefore shows no age marker and is never auto-parked before that date. Setting, moving or removing the due date re-evaluates the age immediately. Auto-park can never become due earlier than 7 days after such a change.
- **FR-004**: System MUST classify each Next task as **fresh** (age below half the threshold), **ageing** (half the threshold or more), **asks for a decision** (threshold or more) or **moves to Someday tomorrow** (within 24 hours of auto-park).
  - **In lists**: only "asks for a decision" and "moves to Someday tomorrow" are shown as markers.
  - **In task detail**: "ageing" is shown only there (design sign-off: keep long lists calm).
  - **Wording**: System MUST NOT use error colouring or the word "overdue" for formulation age.
  - **Counting**: wherever this spec counts or lists tasks that "ask for a decision" (the widget count, the review's decision step, the summary, SC-002), it includes tasks that are in the moves-tomorrow state and tasks whose park is due but not yet applied. Those tasks are listed earliest-asking first.
  - **Before activation**: until the person has seen the explainer (FR-051), no marker is shown.
- **FR-005**: System MUST count how many consecutive formulations of the same task reached "asks for a decision", and offer Someday on the third. A formulation counts as having reached it if it was asking for a decision when it closed, or if it had been kept 7 more days (FR-009), which is only possible once it asks. The offer never blocks any decision. It also offers the thinking canvas, but only where the canvas exists (web today; iOS has no canvas).

**Decision card**

- **FR-006**: For a task that asks for a decision, users MUST be able to choose: done; reformulate; find a first step; move to Waiting (with who/what); release to Someday; cancel; or keep 7 more days.
- **FR-007**: Users MUST be able to optionally record a stall reason: unclear, too big, missing information, waiting on someone, unpleasant/no energy, no longer matters. Choosing a reason MUST visually recommend a fitting decision without restricting choice.
- **FR-008**: "Find a first step" MUST preserve the previous title in the task's notes as "Was: <old title>" and start a new formulation.
- **FR-009**: "Keep 7 more days" MUST require a reason, MUST be available once per formulation. It is measured from the day of the extension, not from the original threshold: the formulation asks for a decision again 7 days after the extension day, and its auto-park point becomes 14 days after the extension day. It can be chosen whenever the task asks for a decision, including in the moves-tomorrow state and after the park became due but before it was applied (FR-013).
- **FR-010**: The decision card MUST be reachable from the task itself on any day, not only inside a review, and decisions made there MUST be recorded the same way as in-review decisions.
- **FR-011**: Every decision MUST be applied through the existing idempotent, owner-serialized task operations and MUST be rejected as stale if the task changed since the card was shown.
- **FR-048**: After any decision (decision card, Inbox, Waiting, Someday), System MUST offer **Undo** for a few seconds, as the existing Process inbox does. For a decision-card, Waiting or Someday decision, Undo restores the task's previous state, title and formulation clock, removes the recorded decision, and removes a follow-up task it created unless that follow-up was changed since. For an Inbox item, Undo returns the item to Inbox: on iOS this is the existing Process inbox Undo; on the web the review's Inbox step offers the same Undo. The review's "Inbox processed" count goes down by one. If Undo can no longer apply because the task changed elsewhere, the person is told so and nothing else changes. Keyboard and screen-reader users MUST be able to reach Undo within its lifetime.
- **FR-047**: On iPhone, the decision card opened from a task outside the review MUST appear as a large sheet over the list. Inside the review it is full-screen.
- **FR-052**: Text the person has typed in this feature's forms and not yet saved MUST NOT be discarded silently. This covers new wording, a first step (including an edited AI proposal), Waiting-for, the extension reason, the answer to a clarifying question, a follow-up title, a return-to-Next title, the concrete title for a Someday task moved to Next, and the mind-sweep line.
  - While such a field differs from its initial value, Close, swipe-down, Escape, Back, Leave and moving to another card or step MUST first ask whether to discard it, with "Keep editing" as the default choice and "Discard" as the other.
  - On iOS, interactive dismissal of a sheet holding unsaved text is blocked until the person chooses. On the web, closing or reloading the tab triggers the browser's leave warning.
  - The unsaved text is kept as a local draft for that task and formulation (or that review step item) and is offered again when the same form reopens, including after the app or tab was closed. A draft is device-local, never synced, logged or sent anywhere, and is deleted when the form is saved or discarded, when the task's formulation changes, or after 7 days.

**Auto-park and return**

- **FR-012**: System MUST move an undecided formulation from Next to Someday when its age reaches threshold + 7 days (or, if extended, 14 days after the extension day, per FR-009), preserving project, tags, notes and due date, and marking it as parked automatically with the time.
- **FR-013**: Auto-park MUST NOT apply to a task whose formulation, state or extension changed after the park became due. Applying it twice to the same formulation MUST have no additional effect and MUST NOT create a sync conflict.
- **FR-014**: Auto-park MUST run whether or not any client is open, for accounts with server sync, and on-device for account-less iOS use. It MUST NOT run for an owner who has not yet seen the auto-park explainer (FR-051).
- **FR-015**: System MUST show auto-parked tasks the person has not yet seen on a "while you were away" screen at the next review or app open, with one-tap return per task and a return-all action. Returned tasks start a new formulation. Closing the screen without continuing leaves the parks unseen: it is shown again at app open at most once per calendar day, and always as the first screen of the next review.
- **FR-016**: The feature becomes active for an owner at the moment they first see the auto-park explainer (FR-051) on any device. For tasks already in Next at that moment, formulation age counts from that moment, and System MUST NOT auto-park any of them earlier than 14 days after it.
- **FR-017**: When no counted review (complete or partial, FR-029) happened for 21 days or more, the next review MUST open in restart mode. For a person who completed onboarding but has never had a counted review, the 21 days count from onboarding; a person who has not onboarded gets the onboarding first and no restart mode. It offers one action that releases every Next task older than 4 weeks to Someday. That action can be undone until the person moves on from the restart screen ("Start the review" or Close). An interruption (app killed, backgrounded, tab reloaded) is not moving on: the review reopens on the released state with Undo still offered. Undo restores the released tasks as they were, including their formulation clocks. A person who completed onboarding but never reviewed sees the same neutral restart copy, without "you've been away".
- **FR-018**: The only automatic change to a task's GTD state this feature makes is Next → Someday auto-park. No other task change happens without the person's action. Re-anchoring formulation clocks at activation (FR-016) and repairing a missing clock are bookkeeping on the clock only: they change no list, title, notes or organisation.
- **FR-051**: After the feature is switched on for an owner, the first time the person opens the iOS app or the web, System MUST show a short one-time **auto-park explainer**, independent of the review onboarding (FR-035). It states the threshold rule (with the current threshold), that an undecided task moves to Someday 7 days later and can be brought back in one tap, that this is the only thing the app moves on its own, the date before which none of the tasks already in Next will move (FR-016), and where the threshold can be changed.
  - The explainer counts as seen when the person dismisses it ("Got it", Close, or Escape on the web). If the app or tab is closed while it is showing, it shows again at the next open.
  - Seen is recorded once per owner and account: the first acknowledgement on any device wins and is stored on the server; later or duplicate acknowledgements change nothing, and other devices do not show the explainer again once they know it was seen. Account-less iOS records it on the device.
  - Until the explainer has been seen, System MUST NOT auto-park any task of that owner and MUST NOT show age markers; clocks keep being maintained in the background.

**AI navigator**

- **FR-019**: On request from the decision card or for a project without a next action, System MUST produce 1–3 proposed first steps in the task's language.
  - **Input**: exactly the task's title, notes and optional stall reason, the project's name, and the titles of up to 20 other open tasks in the same project, plus which kind of suggestion is asked for (first step, new wording, or first next action for a project). Nothing else is sent, regardless of model; in particular the detected language of the task is used only on the device to choose a model and is not sent to the cloud provider.
  - **Project without a next action**: the input is the project name and its open task titles.
  - **No duplicates**: proposals MUST NOT duplicate any open task already in that project, including open tasks beyond the 20 titles sent.
  - **Too long for the model**: notes longer than one shared limit, chosen so that the reduced input fits every supported model, have their middle dropped. The beginning and the most recently added lines are kept. The card says "part of the notes was not considered". Every model, on-device or cloud, receives exactly the same reduced input.
- **FR-020**: A proposal MUST NOT be written to any task until the person confirms it, optionally after editing.
- **FR-021**: Proposals MUST NOT introduce personal facts (people, places, amounts, dates) absent from the task. When information is insufficient, the navigator asks one clarifying question instead. For a task, the person's answer is appended to the task's notes (a normal notes edit, which does not touch the formulation clock), and the navigator runs again on the updated input. For a project without a next action (which has no notes), the answer field is the next action itself: confirming it creates that task in Next in the project, nothing else is stored, and the navigator does not run again.
- **FR-022**: On iOS (and on macOS once Mac sync exists, FR-041), System MUST use Apple's on-device model when it is available. In that case no task content leaves the device, and the feature works offline.
- **FR-023**: When Apple's on-device model is unavailable (unsupported device, Apple Intelligence off, model not ready, unsupported language), System MUST say so and why. It MUST then offer the person a choice:
  - (a) download a separate on-device model that supports the task's language, if the device can run it — the download size is shown before it starts, and once installed the model serves suggestions with no task content leaving the device, including offline;
  - (b) use the cloud provider, subject to FR-024.

  The person's choice is remembered and changeable in settings. Option (a) is offered only where the device and OS can run the downloadable model (iOS/macOS 27 or later with enough memory, per plan). It is delivered in a late slice; until then, and on older systems, only (b) is offered. Apple Private Cloud Compute, if ever used, counts as a cloud provider under FR-024; it is not built now.
- **FR-049**: The separate on-device model MUST be downloaded only on explicit request, MUST be deletable in settings, and MUST NOT be required for any non-AI part of the feature. Download failure or lack of storage MUST be shown with a retry and the cloud alternative.
- **FR-024**: Every cloud-provider request (web, and the Apple-platform cloud choice under FR-023) MUST be preceded by a one-time consent that names the provider and lists the data sent. Consent MUST be revocable in settings, also while the feature is switched off for the owner, and a revoked consent MUST stop requests immediately. A consent given for a different provider or an earlier version of the list of data sent no longer counts, so the consent screen appears again.
- **FR-025**: Cloud-provider requests MUST respect cost caps that follow the existing provider cost-admission pattern, with navigator-specific limits. Failures (timeout, cap, provider error, malformed output) MUST be shown with a correlation ID and leave the review usable without AI.
- **FR-026**: System MUST record whether a confirmed decision used an AI proposal (used as-is, edited, or not used), without storing the proposal text in logs or metrics.

**Guided review**

- **FR-027**: Users MUST be able to start a quick or full review at any time, regardless of the schedule.
- **FR-028**: "Wins of the week" means tasks completed in the last 7 days. The quick review MUST consist of: wins of the week, Inbox to zero, decisions, summary. The full review MUST consist of: wins, mind sweep, Inbox to zero, decisions, rest of Next with capacity mirror, Waiting older than 7 days, projects without a next action, Someday pass (at most 7 items not reviewed in 30 days), dates in the next 14 days, summary.
- **FR-029**: Every step MUST be skippable, and the review MUST be resumable on any of the user's devices. **Qualifying activity** means at least one item decision (Inbox, decision card, Waiting or Someday) or at least one step other than the summary that was finished (not skipped) with nothing to decide. A review MUST be recorded as:
  - **completed** when the person taps Done on the summary and the review has qualifying activity;
  - **completed without activity** when the person taps Done on the summary with no qualifying activity (every step skipped). The person sees "Review done" with no reproach;
  - **partial** when it ends without Done (replaced by a new review, or idle for 7 days) with qualifying activity;
  - **abandoned** when it ends without Done and without qualifying activity.

  Leaving the review ("Leave for now", closing the app or tab) only pauses it: the review stays open and resumable on any device until it is finished, replaced or idle for 7 days. Only completed and partial reviews, and an open review that already has qualifying activity (from its last activity), are **counted reviews**: they alone count toward regularity (SC-001), postpone restart mode (FR-017), suppress the weekly notification (FR-036) and set "Last review" (FR-038). A review completed without activity and an abandoned review do none of these. Merely opening the review never counts.
- **FR-030**: When Inbox holds more than 15 items, the Inbox step MUST offer three choices: "process 10 now", "process all", or "process 10 now, then release the remainder to Someday". The release of the remainder can be undone in one action until the person leaves the Inbox step (Next, Skip or "Leave for now"). As for restart mode (FR-017), an interruption (app killed, backgrounded, tab reloaded) is not leaving the step: the step reopens on its finished state with the Undo still offered.
- **FR-031**: The capacity mirror MUST state the Next count, the average weekly completions over the last 4 weeks, and the implied number of weeks. With less than 4 full weeks of completion history, or no completions in them, it MUST show the Next count only, with a line saying the weekly pace appears after a few weeks of finished tasks. It MUST NOT enforce any limit.
- **FR-032**: "Keep waiting" and "keep in Someday" MUST hide the item from those steps for 7 and 30 days respectively, unless the task changes earlier. A Someday task is "not reviewed in 30 days" when no such hiding applies to it. Tasks auto-parked in the last 30 days are left out of the Someday step, because the person saw them on "while you were away". Tasks the person moved to Someday themselves (a "release to Someday" decision, the restart release, or the Inbox-remainder release) are treated like "keep in Someday": they are left out for 30 days unless they change. The Someday step shows the longest-unreviewed tasks first: never reviewed before reviewed, then oldest review first.
- **FR-033**: The summary MUST show ten counts in fixed order: done, reformulated, first step, Waiting, Someday, cancelled, extended, Inbox processed, **kept as is** (keep waiting and keep in Someday) and **moved to Next** (follow-ups created, and tasks returned to Next from Waiting or Someday). It also shows the next scheduled review, and asks once "Clear how to start the week? yes / not really". The answer is optional. When every count is zero it shows one calm line instead of the counts.
- **FR-034**: Steps that involve decisions (Inbox, decisions, Waiting, Someday) MUST present one item at a time.
- **FR-050**: In the decision step, the person MUST be able to set one card aside with "Not now" without deciding. The task stays "asks for a decision", its auto-park schedule is unchanged, and the next card is shown.

**Schedule, cue, onboarding, settings**

- **FR-035**: Before the first review, System MUST show one onboarding screen explaining the review, the threshold rule and auto-park, and collecting review day/time (default Friday 16:00 local) and threshold (7/14/21/28, default 14). The onboarding is independent of the one-time auto-park explainer (FR-051), which comes earlier, at the first app or web open; the onboarding repeats the rule briefly and states the grace date from FR-016.
- **FR-036**: On iOS (and macOS after Mac sync), System MUST send at most one review notification per week, at the chosen local day and time, with no follow-ups. No notification is sent for a week if a counted review (complete or partial, FR-029) happened in the preceding 6 days. Web sends no notifications; it shows the time since the last review in the navigation.
- **FR-037**: The iOS Next Actions widget MUST show the number of tasks that ask for a decision. In the medium and large widget, tapping that count MUST open the review's decision step at its first card. The small widget, which has a single tap target, shows the count and keeps opening Next. A widget configured to show Today instead of Next actions shows no count.
- **FR-038**: System MUST show the time since the last counted review (FR-029) in neutral wording, and MUST NOT show streaks or streak loss.
- **FR-039**: Changing the threshold MUST update markers immediately, and MUST NOT cause any task to be auto-parked earlier than 7 days after the change.

**Platforms and parity**

- **FR-040**: iOS and web MUST offer US1–US5 with equivalent behaviour over the same account. iOS MUST support every non-server part offline.
- **FR-041**: macOS MUST offer US1–US5 over the same synced account once Mac↔backend sync exists. Until then, the Mac app MUST show a non-interactive "Weekly review · coming later" entry. That is a small pre-sync change, because the Mac app has no such entry today.
- **FR-042**: The existing disabled "Weekly review — coming soon" entries on web and iOS MUST be replaced by the working entry when the feature is active: for a signed-in account, when the feature is switched on for it; for account-less iOS, once its release switch is on (edge case "Account-less iOS use"). Until then the existing entry stays.

**Data, privacy, observability**

- **FR-043**: Review sessions, decisions (including stall reasons and the reason text of a "keep 7 more days" decision), receipts, settings and AI consent MUST be stored per owner, included in the account ZIP export, and removed by account purge. Short-lived copies kept only to make Undo possible are deleted after 7 days, whether or not the feature is still switched on for the owner.
- **FR-044**: Logs, metrics and events MUST contain only identifiers, decision and reason codes, counts, timings and stage names. They MUST NOT contain task titles, notes, reason text or AI input/output.
- **FR-045**: Every server response for this feature MUST carry the correlation ID, and every user-visible failure MUST show it.

### Key Entities *(include if feature involves data)*

- **Formulation clock** (on a task): when the current formulation started, how many consecutive formulations reached the threshold, and whether the one-time extension was used.
- **Park marker** (on a task): whether and when the task was parked automatically, the clock it had before the park (so a yielding decision can restore it), and whether the person has seen it on "while you were away". A person's own release to Someday is not a park.
- **Review session**: one review by one owner. Holds mode (quick/full), status (open, completed, completed without activity, partial, abandoned; FR-029), start and end times, active time per step, current step for resume, the ten summary counts, and the optional "clear start" answer.
- **Review decision**: one decision on one task. Holds the decision type, optional stall reason, the reason text of a "keep 7 more days" decision, whether an AI proposal was used, the time, and optionally the review session it belongs to (decisions can be made outside a review).
- **Review receipt**: "keep waiting" or "keep in Someday" for one task (a person's own release to Someday writes the same Someday receipt, FR-032), with the date until which it stays out of the step.
- **Review settings**: review day, time, time zone and threshold per owner, and when the owner first saw the auto-park explainer (the activation moment, FR-016, FR-051).
- **AI navigator consent**: per owner and provider; when granted and when revoked.
- **Navigator preference** (per device): when Apple's on-device model is unavailable, whether the person chose the downloadable on-device model or the cloud provider, and whether the downloadable model is installed.
- **Form draft** (per device): unsaved typed text of one form for one task and formulation or review item (FR-052). Never leaves the device.

## Success Criteria *(mandatory)*

### Measurable Outcomes

Measured per active user over the first 8 weeks after their first review.

- **SC-001**: Users complete at least a partial review in at least 3 of every 4 weeks. Only counted reviews (completed or partial, FR-029) count.
- **SC-002**: Immediately after every completed review whose decision step was finished with no card set aside ("Not now", FR-050), 0 Next formulations older than the user's threshold remain without a decision. A decision recorded on the current formulation counts, including a cosmetic-only reformulation saved anyway (FR-002), even though that task still asks.
- **SC-003**: At least 70% of answered reviews end with "clear how to start the week: yes".
- **SC-004**: On the owner's real task set, the median quick review takes 5 minutes or less and the median full review 20 minutes or less, measured as active time in the review (pauses and gaps of inactivity excluded, so a review left and resumed later is not over-counted).
- **SC-005**: On the owner's stalled tasks, at least 50% of AI first-step proposals are accepted (as-is or edited). In a reviewed evaluation set, 0 proposals introduce personal facts absent from the task.
- **SC-006**: 100% of auto-parked tasks show "moves to Someday tomorrow" for at least the preceding 24 hours, appear on the next "while you were away" screen, and can be returned in one action.
- **SC-007**: A review completed offline on iOS loses 0 decisions after sync, and its summary is visible on web.

## Assumptions

- Persona: a broad audience of GTD practitioners and newcomers, with users with ADHD as the design centre. The product is not positioned as "an ADHD app".
- Language follows the rest of the product today. AI answers in the task's language. Full localisation is out of scope.
- Apple's on-device model requires iOS 26 / macOS 26 on an Apple Intelligence-capable device with Apple Intelligence enabled. Whether it supports Russian is **unverified** (checked 2026-10-05). If it does not, Russian-language tasks on Apple platforms go through the FR-023 choice: a downloadable on-device model or the consented cloud provider. Which downloadable model to use, its size and its device requirements are planning decisions. Its suggestions are held to the same SC-005 bar.
- The cloud provider and per-call budget for the navigator follow the existing provider adapter and cost-admission pattern, with navigator-specific settings and limits; the exact choice is a planning decision.
- Waiting and Someday review behaviour follows the macOS POC receipt pattern. Waiting returns after 7 days. Someday returns after 30 days, confirmed in clarification (the POC uses 7).
- Mac↔backend sync is delivered as a separate feature spec; US6 depends on it.
- This feature requires superseding or amending ADR-0006 (Weekly Review deferred, no cadence or due state), and must close open decision D-11 in `docs/vnext-cloud-design-build-contract.md`. It also requires amending ADR-0001's capture-based review model, and the macOS POC principle that review never changes GTD state automatically. That will be recorded in a new ADR during planning.

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
- A web project-page entry for a project's first next action. On the web, US3-8 is offered only in the full review's projects step; iOS also offers it on the project screen.
