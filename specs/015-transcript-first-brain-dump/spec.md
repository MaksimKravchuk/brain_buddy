# Feature Specification: Transcript-first voice brain dump

**Feature Branch**: `claude/brain-dump-mechanics-t35ab7`

**Created**: 2026-09-05

**Status**: Retro-specification, in review on PR #194. This feature **narrows** `specs/002-async-voice-workflows/` User Story 1 ("See useful provisional tasks while speaking"), required user outcome 2 ("numbered provisional captures appear while recording continues") and `002-SC-004` ("the browser journey records, shows provisional tasks, …"): the browser preview is now a transcript readout and is never a task source. Spec 002's normative files remain hash-frozen as delivered history and are not edited; the architecture record of the change is the ADR-0002 amendment dated 2026-09-05 in `docs/decisions/0002-async-voice-operation-substrate.md`. The core behaviour landed on this branch in PR #194 (commits `12814a7`, `252fa01`, `50369bc`): FR-001 to FR-005, FR-011 and the stage-and-transcript part of FR-006. This document records the requirements that work satisfies and the follow-up items being built on the same branch — the "Cancel processing" affordance of FR-006, FR-007, FR-008 and FR-009 — while FR-010 restates the existing provisional label and extends it to recovered results.

**Input**: User description (founder, 2026-09-05, quoted from [intake.md](intake.md)): «Работает погано. Вот пример на текст: Так, надо купить молоко. [2 сек тишины] Сходить в магазин. [2 сек тишины] Покрасить комнату. Результат на фото. 1. Не надо показывать просто сырой текст как задачи. Сырой текст хорошо, как статус. 2. Задачи уже должны быть очищены от говна и дубликатов. И перефразированны под гайды GTD. Надо починить» — followed in the same conversation by «у нас превью же текст, почему нельзя восстановить?», «Из UX-аудита: нет отмены на экране обработки, нет подтверждения Discard, при resume не восстанавливаются хвост и таймер. добавь» and, closing elicitation, «просто доделай».

The reference utterance throughout this document is «Так, надо купить молоко. Сходить в магазин. Покрасить комнату.» and the expected result is exactly three tasks: «Купить молоко», «Сходить в магазин», «Покрасить комнату».

## Clarifications

### Session 2026-09-05

No question was put to the founder in this session: elicitation was closed with «просто доделай». Each entry records the decision taken in place of the question and who took it.

- Q: Should spec 002 be rewritten in place to reflect that the browser preview no longer produces tasks, or should the change be recorded as a new feature? → A: **New feature number; 002 untouched ("path A")** — 002's normative files stay hash-frozen as delivered history; this spec narrows 002 US1, required outcome 2 and SC-004 in prose, and the ADR-0002 amendment of 2026-09-05 is the architecture record. *Decided by the founder, 2026-09-05 («путь A»).*
- Q: After a terminal processing failure, how may the owner recover a recording that still holds browser preview text — by extracting tasks from that text, or by typing tasks in by hand? → A: **Reconciler-based extraction from the browser transcript, not manual task entry** — the same task-extraction step that normally reads the accurate transcript runs once over the preview text, and its result enters the normal review as provisional. *Decided by the founder («у нас превью же текст, почему нельзя восстановить?», then «просто доделай» after the options were laid out).*
- Q: How often may the browser-transcript recovery run on one recording, and what bounds its cost? → A: **One attempt per recording, bounded by the existing spend ceilings** — offered at most once per recording whether it succeeds or fails, charged against the existing per-step and per-recording ceilings, never chosen automatically; no new spend path. *Decided by the agent under the founder's directive.*
- Q: Should the processing screen offer "leave and come back later" next to "Cancel processing"? → A: **No leave/return affordance** — there is no in-app list of in-flight recordings to return to, so a leave button would orphan the recording. Processing continues on the server while the screen stays open, and reopening the app resumes the recording where it is. *Decided by the agent (derived from the UX audit; not raised by the founder).*
- Q: Should the destructive-exit confirmations be nested dialogs or inline confirmations? → A: **Inline confirmation in place of the trigger** — the brain dump already runs as an overlay, and a dialog inside an overlay is hard to make accessible (focus trapping, lost screen-reader context). The inline confirmation puts focus on the safe choice, and Escape restores the trigger with focus. *Decided by the agent.*
- Q: When a recording is reopened, where does the resumed timer start? → A: **From the captured audio duration, pauses excluded** — the timer shows how much speech has been captured, which is what the owner was counting, not the wall-clock time since the recording began. *Decided by the agent.*
- Q: Are the interview and the design sign-off human gates required for this feature? → A: **Waived by the founder** — «просто доделай» closed elicitation; the waiver is recorded in intake.md so the acceptance auditor and the delivery report can see it. *Decided by the founder.*
- Q: Does the destructive-exit confirmation (FR-007) bind the mobile client, which had none? → A: **Yes, with the platform dialog** — the design stage found that mobile's "Discard everything", "Discard all" and a review header control named "Close" all deleted the recording on one tap; they now confirm through the platform dialog, the header control is renamed, and SC-004 counts both clients. *Decided by the agent under the founder's directive (data-loss risk; constitution Principle V).*
- Q: Does FR-006 (transcript and "Cancel processing" on the processing screen) bind the mobile client? → A: **Web only** — mobile keeps naming the stage; its transcript readout and cancel affordance are recorded as out of scope rather than half-built. *Decided by the agent.*
- Q: What does the owner see when a browser-transcript recovery is refused? → A: **The reason and a reference id** — the server's refusal (consent, spend ceiling, unavailable state) is shown in words with the request's reference id, never a bare status word such as "Forbidden". *Decided by the agent after the design review (FR-009).*

## User Scenarios & Testing *(mandatory)*

<!--
  BrainBuddy callouts — consent/local-first behaviour, mobile-first capture and
  review impact, observability/correlation-ID behaviour, data-loss risks and
  responsiveness targets — are addressed under "Cross-cutting constraints" in
  Requirements. Primary loop impact: capture -> atomic items only; no impact on
  routing, Weekly Review or evidence.
-->

### User Story 1 - Clean next actions from a natural dump (Priority: P1)

The owner records a natural, hesitant brain dump — «Так, надо купить молоко. Сходить в магазин. Покрасить комнату.», with a two-second pause between thoughts — presses Stop, and after processing sees a review of exactly three next actions, «Купить молоко», «Сходить в магазин» and «Покрасить комнату», in the language they spoke. Save is available immediately; nothing has to be deleted or retyped, and saving creates exactly those three Inbox tasks.

**Why this priority**: This is the founder's ask and the reason the feature exists. Today the same utterance produced nine review entries, six of them junk or duplicates, and Save stayed disabled until six cards were deleted by hand. The capture loop ("speak, review, save") is worthless if review means cleaning up machine noise.

**Independent Test**: Record (or replay) the reference utterance on a consented recording, press Stop, wait for processing, compare the review list against the three expected titles, then press Save without editing and count the Inbox tasks. Delivers value on its own even if nothing else in this specification ships.

**Acceptance Scenarios**:

1. **Given** a consented recording, **When** the owner speaks the reference utterance with pauses and presses Stop, **Then** the review lists exactly «Купить молоко», «Сходить в магазин», «Покрасить комнату» — no filler title («Так», «Надо»), no fragment («Надо купить моло»), no whole-utterance title, no duplicate.
2. **Given** that review, **When** the owner presses Save without editing or deleting anything, **Then** Save is enabled, exactly three Inbox tasks with those titles are created, and each saved task records that it came from the accurate transcript.
3. **Given** a dump that restates the same action twice («Купить молоко… и да, купить молоко»), **When** processing completes, **Then** one task «Купить молоко» appears and its evidence shows both utterances.
4. **Given** an English dump "So, I need to call the dentist and, um, book the car service", **When** processing completes, **Then** the review shows "Call the dentist" and "Book the car service" — in English, not translated, without the "I need to" scaffolding.
5. **Given** a dump containing a self-correction («Надо купить моло… Купить молоко»), **When** processing completes, **Then** one task «Купить молоко» appears; the abandoned fragment is visible only in the transcript.

---

### User Story 2 - Raw text is a status, never a task (Priority: P2)

While the owner speaks, the screen shows what has been heard as a transcript readout: the still-forming hypothesis beside the microphone, settled utterances in a labelled region. No draft task card exists before Stop. During processing the screen shows the stage and the transcript so far. If nothing actionable was said, the review says so, shows what was heard, and cannot be saved.

**Why this priority**: It is the founder's first numbered point («Не надо показывать просто сырой текст как задачи. Сырой текст хорошо, как статус») and the root cause of the junk: every preview fragment used to be minted into a card that later stages could not retire. Removing cards before Stop is what makes User Story 1 possible; the empty-review honesty prevents a zero-task save from ever being offered.

**Independent Test**: Start a recording in a browser with speech preview, speak several utterances, and assert that no task card is rendered at any point before Stop while the transcript region fills; then process a filler-only dump and assert the review offers no Save.

**Acceptance Scenarios**:

1. **Given** a recording in progress in a browser with speech preview, **When** the owner speaks, **Then** the hypothesis still being formed appears beside the microphone, each settled utterance appears once in a region labelled as the transcript, and zero task cards are shown.
2. **Given** the owner has pressed Stop, **When** processing runs, **Then** the screen shows the current stage in plain words and the transcript so far, shows no task cards, and offers "Cancel processing".
3. **Given** a dump that contains only fillers («Так… ну… надо…»), **When** processing completes, **Then** the review states that no tasks were proposed, shows what was heard, offers discard or record again, and offers no Save.
4. **Given** a browser without speech preview, **When** the owner records and stops, **Then** the recording screen does not claim a preview is coming, the processing screen does not promise one, and the review shows the accurate transcript.
5. **Given** the owner deletes every task in a review, **When** they look for Save, **Then** Save is unavailable and the review offers discard or record again.

---

### User Story 3 - Recover a failed recording from the browser transcript (Priority: P3)

When processing ends in a terminal failure, no task survived, and the recording still holds browser transcript text, the owner may explicitly ask to "Extract tasks from the browser transcript". One attempt runs, within the existing spend ceilings and only while external-processing consent stands; the result opens the normal review, visibly labelled as coming from the browser transcript, and can be saved as provisional. Mobile renders the same action and label when the recording is opened there.

**Why this priority**: The founder's follow-up («у нас превью же текст, почему нельзя восстановить?»). Once the preview stopped producing fallback drafts, a terminal failure left only "cancel" although readable text sat in the recording. It is third because it depends on the first two stories (there must be no preview-derived cards to fall back on) and because it is a recovery path rather than the main loop.

**Independent Test**: Force a terminal failure on a recording that has browser transcript text; assert the action is offered exactly once, that it is absent after consent withdrawal or when the spend ceiling is reached, and that the resulting review and saved tasks are marked provisional on web and mobile.

**Acceptance Scenarios**:

1. **Given** a terminal failure, browser transcript text present, consent standing and spend ceilings not reached, **When** the owner presses "Extract tasks from the browser transcript", **Then** exactly one extraction runs and its result opens the normal review, labelled as provisional and as coming from the browser transcript.
2. **Given** that provisional review, **When** the owner saves, **Then** Inbox tasks are created and each saved task records a provisional, browser-transcript origin.
3. **Given** the recovery has already been used once on this recording (whether it succeeded or failed), **When** the owner returns to the failure screen, **Then** the action is not offered again and cancel remains available.
4. **Given** the owner has withdrawn external-processing consent, **When** they view the failure screen, **Then** the action is not offered, a request made anyway is refused because the withdrawal stands, and cancel remains.
5. **Given** the recording's spend ceiling is already reached, **When** the owner requests the extraction, **Then** it is refused before any external call, the reason is stated, and cancel remains.
6. **Given** a recording started on the web and reopened on mobile after a terminal failure, **When** the owner views it, **Then** mobile offers the same action and shows the same provisional label on the result, whether or not the result can be saved.
7. **Given** a terminal failure on a recording with no browser transcript text (mobile-only capture, or a browser without preview), **When** the owner views the failure screen, **Then** only cancel is offered, as today.

---

### User Story 4 - Safe destructive exits and faithful resume (Priority: P4)

Every destructive exit — discard a recording, discard all reviewed tasks, delete a failed recording, cancel processing — asks for an explicit second confirmation whose safe choice has keyboard focus; Escape or the safe choice leaves everything as it was. Reopening an in-progress recording restores the last utterance beside the microphone and a timer that continues from the captured duration.

**Why this priority**: The UX-audit items the founder asked to act on («нет отмены на экране обработки, нет подтверждения Discard, при resume не восстанавливаются хвост и таймер»). They protect the recording from accidental loss and make resume trustworthy; they are last because the earlier stories deliver value without them.

**Independent Test**: Trigger each of the four destructive exits and assert a confirmation appears with focus on the safe choice, that Escape and the safe choice leave the recording unchanged, and that only the explicit confirmation destroys; reload the page mid-recording and assert the last utterance and the timer on first render.

**Acceptance Scenarios**:

1. **Given** a recording in progress, **When** the owner presses Discard, **Then** a confirmation appears with focus on the safe choice ("Keep recording"); Escape or the safe choice leaves the recording exactly as it was; only the explicit confirm discards it.
2. **Given** a review with tasks, **When** the owner presses Discard all, **Then** the same pattern applies; nothing is saved and nothing is deleted until confirmed.
3. **Given** a failed recording, **When** the owner presses Delete recording, **Then** the same pattern applies; audio and transcript are removed only after the explicit confirm.
4. **Given** processing in progress, **When** the owner presses Cancel processing, **Then** the same pattern applies; processing continues undisturbed while the confirmation is open, and only the explicit confirm cancels it.
5. **Given** a recording in progress with three settled utterances and 42 seconds of captured audio, **When** the page is reloaded and the recording reopened, **Then** on the first render of the recording screen the last utterance is shown beside the microphone and the timer reads 0:42 and keeps counting; no task cards appear.
6. **Given** a confirmation shown on a stale screen (the recording was saved or discarded from another tab meanwhile), **When** the owner confirms, **Then** the action applies to the recording's current state: saved Inbox tasks are never removed, an already-discarded recording reports as discarded, and no error destroys anything further.

---

### Edge Cases

- **Filler-only dump** («Так… ну… надо…»): no task survives; the review says no tasks were proposed, shows what was heard, and cannot be saved (FR-005).
- **Self-correction** («Надо купить моло… Купить молоко»): the abandoned fragment carries no complete action and is dropped; one task «Купить молоко» survives; the fragment stays visible in the transcript (FR-003, FR-004).
- **Same action restated twice**: folded into one task; the evidence of both utterances is kept (FR-004).
- **Restatement of a task already in review**: counted as an affirmation of that task, not minted as a twin (FR-004).
- **Owner deleted a task, then extraction restates it with different punctuation or quotes**: the deletion stands; the task is not revived (FR-004).
- **Dropped-item record**: a dropped filler title or folded duplicate appears in the recording's processing record as a fixed reason only; neither the title nor any transcript text is recorded (FR-004).
- **Consent withdrawn before recovery is requested**: the browser-transcript extraction is not offered; a request made anyway is refused; cancel remains (FR-009).
- **Spend ceiling already reached**: the extraction is refused before any external call, with the reason; cancel remains (FR-009).
- **Recovery attempted once and failed**: not offered again; cancel remains (FR-009).
- **Page reload mid-recording**: the reopened recording shows the last utterance beside the microphone and a timer continuing from the captured duration; no task cards; consent state and language settings are unchanged (FR-008).
- **Discard confirmed on a stale revision**: the confirmation applies to the recording's current state; saved Inbox tasks are never removed by a discard; an already-discarded recording is reported as discarded, not treated as an error that deletes more (FR-007).
- **Browser without speech preview**: the recording screen does not claim a preview will appear, the processing screen copy does not promise one (it shows the accurate transcript when it arrives), and no browser-transcript recovery is offered because there is no preview text (FR-001, FR-006, FR-009).
- **Recording resumed on mobile after a web start**: mobile shows the server-held transcript readout, offers the browser-transcript recovery when the server offers it, and shows the provisional label on any provisional result (FR-009, FR-010).
- **Mixed-language utterance** («Позвонить Наташе про production smoke»): the task keeps the words as spoken, code-switch included; nothing is translated (FR-003).
- **Operation recorded before this change with untouched provisional proposals**: today's rules apply — each must be edited or deleted before saving (FR-011).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: While recording, the system MUST show browser-preview text only as a status readout: settled utterances appear once each in a region labelled as the transcript, the still-forming hypothesis appears beside the microphone, and no draft task card exists before the owner stops.
- **FR-002**: The system MUST persist browser-preview text as transcript only; preview text MUST never become a task proposal. Owner edits, locks and lineage rules for proposals that already exist (legacy operations, seeded proposals) are unchanged.
- **FR-003**: The system MUST produce tasks once, from the accurate transcript, as GTD next actions: verb first, in the language spoken (never translated), discourse fillers and modal scaffolding dropped, one task per distinct action, every task grounded in the spoken words.
- **FR-004**: Independently of the model, the system MUST drop a title that carries no action or object (e.g. «Так», «Надо»), fold restated duplicates into one task while keeping the evidence of both, treat a restatement of an existing task as an affirmation of it rather than a twin, and never revive a task the owner deleted under a punctuation variant of its title. Dropped items MUST be recorded by reason, never by content.
- **FR-005**: For a fresh recording the reviewed result MUST be saveable immediately with zero manual cleanup. A review with no surviving task MUST NOT be saveable: it says that no tasks were proposed, shows what was heard, hides the save control, and its only exit is to discard the recording, which returns the owner to a fresh recording. On mobile the same empty review says nothing was proposed and hides the confirm control.
- **FR-006**: The web processing screen MUST show the current stage in plain words and the transcript so far, and MUST offer "Cancel processing". The mobile processing screen names the stage (existing behaviour); its transcript readout and cancel affordance are out of scope here.
- **FR-007**: Every destructive exit MUST require an explicit second confirmation, and the safe choice MUST leave everything as it was. On the web — discard a recording, discard all reviewed tasks, delete a failed recording, cancel processing — the confirmation is inline, its safe choice has keyboard focus, and Escape keeps everything. On mobile — discard everything on the failure screen, discard all reviewed tasks, and the review header's discard control — the confirmation is the platform dialog with a cancel choice first. No control that discards a recording may be named "Close", and a control that deletes only retained audio must say so.
- **FR-008**: Reopening an in-progress recording MUST restore the last utterance beside the microphone and a timer that continues from the captured duration.
- **FR-009**: After a terminal processing failure with no surviving task and with browser transcript text present, the owner MUST be able to explicitly request "Extract tasks from the browser transcript"; the point of choice names where the text is sent. The system MUST allow one attempt per recording, only while the recording's external-processing consent stands (never after withdrawal), within the existing spend ceilings, and MUST never choose it automatically. The result enters the normal review and is saveable as provisional. A refused request MUST state its reason in the owner's words (consent, spend ceiling, or an unavailable state) together with the request's reference id, never only a bare status word.
- **FR-010**: Provisional results MUST be visibly labelled as coming from the browser transcript on web and mobile whenever they are shown, whether or not they can be saved, and MUST never be presented as accurate.
- **FR-011**: Operations recorded before this change that still carry provisional proposals MUST keep today's rules: an untouched provisional proposal must be edited or deleted before saving.

### Cross-cutting constraints *(inherited; this feature changes none of them)*

- **Consent and local-first**: no audio or transcript text reaches an external provider without the owner's standing external-processing consent. The browser-transcript recovery is a further explicit choice under that same consent, and its point-of-choice copy names where the text is sent; withdrawal makes the recovery unavailable.
- **Feature flag**: the voice brain-dump flag gates new capture only; reading a recording, cancelling it, withdrawing consent and deleting raw audio stay reachable when the flag is off.
- **Primary loop impact**: this feature lives in capture → atomic items. Capture now yields clean next actions instead of raw fragments, so clarify/approve starts from the owner's intent rather than from cleanup. No impact on routing, Weekly Review or evidence.
- **Mobile-first**: mobile has no browser preview lane and captures nothing new; it must render the browser-transcript recovery when the server offers it and the provisional label whenever a provisional result is shown. Web behaviour is specified at the 390 px viewport of the founder's screenshots.
- **Observability**: every response keeps its correlation ID; processing attempts, dropped items and refusals are recorded by stage and fixed reason, never by transcript content or task text.
- **Data loss**: destructive exits confirm first (FR-007); a resumed recording loses neither its transcript nor its captured duration (FR-008); nothing reaches the Inbox without an explicit Save.
- **Retention, export and purge**: unchanged; the recovery adds no new kind of durable record.

### Key Entities

- **Recording (operation)**: one voice capture from start to saved or discarded. Owns the owner's consent (including its withdrawal), the current status, the captured duration, its transcript segments, task proposals, processing attempts and spend so far. It is the unit the spend ceilings and the one-attempt recovery rule apply to.
- **Transcript segment**: one utterance as heard. Carries its order, its kind — browser preview or accurate — its state — still-forming or settled — and, when a later segment replaces it, a superseded-by link so only surviving text is read out. Preview segments are status only and never a task source.
- **Task proposal**: a candidate task shown in review. Carries its title, its status, the owner's edits (title changes, deletion, keep-mine-versus-accept choices) and its provenance: which segments it cites and whether it came from the accurate transcript or from the browser transcript.
- **Processing attempt**: one run of a processing stage over a recording — accurate transcription, task extraction from the accurate transcript, or the one-shot extraction from the browser transcript. Carries the stage, the outcome (succeeded, retryable failure, terminal failure, cancelled) and its cost reservation against the ceilings.
- **Saved-task receipt**: the record that a reviewed proposal became an Inbox task. Records whether the task's origin was accurate or provisional (browser transcript), so the origin stays inspectable after the working artifacts expire.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Recording the reference utterance «Так, надо купить молоко. Сходить в магазин. Покрасить комнату.» yields a review of exactly 3 tasks, 0 junk or duplicate entries, and 0 manual deletions before Save is available (baseline: 9 entries, 6 junk or duplicate, 6 deletions).
- **SC-002**: In 100% of recordings, 0 task cards are shown before the owner presses Stop (baseline: one card per preview fragment).
- **SC-003**: A filler-only dump never yields a saveable task: across the filler-only test corpus, 0 reviews offer Save.
- **SC-004**: Web: 4 of 4 destructive exits (discard recording, discard all, delete recording, cancel processing) require a second explicit confirmation with focus on the safe choice (baseline: 0 of 4). Mobile: 3 of 3 destructive exits (discard everything, discard all, the review header's discard control) require a platform confirmation with a cancel choice (baseline: 0 of 3).
- **SC-005**: A resumed in-progress recording shows the last utterance and the captured duration on the first render of the recording screen in 100% of resumes (baseline: never).
- **SC-006**: From a terminal failure with browser transcript text present, the owner reaches a provisional review in one action plus processing time (baseline: no exit other than cancel).
- **SC-007**: The provisional label is present in 100% of provisional reviews on both web and mobile, including reviews that cannot be saved.

## Out of Scope

- Rewriting `specs/002-async-voice-workflows/` in place; its normative files stay hash-frozen (Clarifications, first decision).
- A "leave and come back later" affordance on the processing screen (Clarifications, fourth decision).
- Any automatic, non-owner-initiated fallback to browser-transcript extraction.
- Any new provider, model or spend ceiling; the recovery reuses the existing ceilings.
- Browser-preview capture on mobile (mobile has no preview lane).
- A transcript readout and a "Cancel processing" affordance on the mobile processing screen (mobile names the stage only; FR-006 binds the web screen).
- Changes to retention, export, purge, or to the consent model beyond reusing the standing consent.

## Assumptions

- Single-user deployment today (the founder). Every brain-dump surface is already owner-scoped and behind the voice brain-dump feature flag, and the requirements above hold unchanged for future users.
- Provider spend ceilings — per processing step and per recording — are unchanged; the browser-transcript recovery is one more extraction attempt counted against them.
- Mobile has no browser preview lane; it can only render what the server holds and offers.
- Spec 002 is frozen history; where 002 US1, required outcome 2 or SC-004 conflict with this document, this document and the ADR-0002 amendment of 2026-09-05 win.
- Browser speech preview is best-effort and may be absent; the accurate transcript is the only authoritative source of tasks.
- Browser transcript text exists in a recording only because external-processing consent was granted before the first preview segment was accepted; it is therefore available for recovery only under that same consent.
- Retention, account export and purge already cover recordings, transcripts and receipts; this feature adds no new kind of durable record.
