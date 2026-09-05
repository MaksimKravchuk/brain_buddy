# Business Intake: Transcript-first voice brain dump

**Feature**: `specs/015-transcript-first-brain-dump/`
**Interviewed**: 2026-09-05
**Interviewee**: Maksim Kravchuk (founder, repository owner). No interview session was
held: the founder reported the defect with screenshots, answered the follow-up
review in the same conversation, and then directed the agent to complete the
work without further elicitation («просто доделай»). This intake is the record
of what the founder actually said, in their own words, plus the decisions they
took in that conversation. Where a heading was not discussed, the answer below
is derived from the shipped code and repository governance and is marked
*derived*.

<!--
  Produced from the 2026-09-05 conversation instead of /speckit-interview. The
  founder explicitly waived the interview gate; that waiver is itself recorded
  here so the acceptance auditor and the report can see it.
-->

## The ask, as given

> Работает погано. Вот пример на текст: Так, надо купить молоко. [2 сек тишины]
> Сходить в магазин. [2 сек тишины] Покрасить комнату. Результат на фото.
> 1. Не надо показывать просто сырой текст как задачи. Сырой текст хорошо, как
> статус. 2. Задачи уже должны быть очищены от говна и дубликатов. И
> перефразированны под гайды GTD. Надо починить

Follow-up in the same conversation, after the fix was reviewed:

> Ретрай по инициативе владельца из terminal_error: превью больше не даёт
> «запасных» черновиков, так что терминальный сбой до реконсиляции оставляет
> только cancel. у нас превью же текст, почему нельзха восстановить?

> Из UX-аудита: нет отмены на экране обработки, нет подтверждения Discard, при
> resume не восстанавливаются хвост и таймер. добавь

> просто доделай

English gloss (not a substitute for the quotes): «It works badly. Example: "So,
need to buy milk. [2 s silence] Go to the shop. [2 s silence] Paint the room."
Result in the screenshots. 1. Do not show raw text as tasks; raw text is fine as
a status. 2. Tasks must already be cleaned of junk and duplicates, and rephrased
per GTD guidance. Fix it.» — «We do have the preview as text, why can't it be
recovered?» — «From the UX audit: no cancel on the processing screen, no Discard
confirmation, resume does not restore the tail and the timer. Add them.» —
«Just finish it.»

## 1. Problem

- **Whose problem**: the recording owner using the web brain dump (the founder
  today; every future user of the voice capture).
- **How it shows up today**: recording the reference utterance produced nine
  "tasks" in review — `Так`, `Надо`, `Надо купить моло`, `Купить молоко`,
  `Молоко`, the whole utterance as one title, and more — and **Send to inbox
  stayed disabled** until six cards were deleted by hand. Every browser-preview
  fragment had been minted into a draft task the reconciler could not retire.
- **What it costs**: the capture loop's promise ("speak, review, save") breaks
  at review; the owner cleans up machine junk instead of reviewing their own
  intent; abandoned dumps; distrust of the feature.
- **If we build nothing**: every recording with natural fillers or a
  self-correction produces junk cards and a disabled Save; a terminal provider
  failure leaves the owner with cancel as the only exit even though the browser
  transcript text is sitting in the operation.

## 2. Customer and persona

- **Primary**: the recording owner on the web client (mobile viewport included:
  the screenshots are 390px wide).
- **Secondary**: the same owner resuming an operation on mobile; the mobile
  client must render whatever recovery the server offers.
- **Deployment shape**: single-user (founder) today, multi-user capable — every
  brain-dump route is owner-scoped behind the session cookie and the
  `voice_brain_dump` feature flag.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| Review entries for the reference utterance («Так, надо купить молоко. Сходить в магазин. Покрасить комнату.») | 9 entries, 6 junk or duplicate | exactly 3 next actions, 0 junk, 0 duplicates | 2026-09-05 |
| Manual deletions before Save is enabled, same utterance | 6 | 0 | 2026-09-05 |
| Draft task cards shown while still speaking | one per preview fragment | 0 (raw text shown only as a transcript status) | 2026-09-05 |
| Owner-reachable exits from a terminal provider failure when preview text exists | 1 (cancel) | 2 (cancel, or extract provisional tasks from the browser transcript in one action) | 2026-09-05 |
| Destructive exits (discard, discard all, delete recording, cancel processing) that require a second, explicit confirmation | 0 of 4 | 4 of 4 | 2026-09-05 |
| Resumed recording shows the last utterance and the captured duration on reopen | never | always, on first render of the recording screen | 2026-09-05 |

## 4. Scope boundary

**In scope**

- [x] Browser-preview text is a transcript readout (a status), never a source
  of draft tasks, on the recording and processing screens.
- [x] Tasks are produced once, by the reconciler over the accurate transcript,
  as GTD next actions: verb first, in the language spoken, discourse fillers
  and modal scaffolding dropped, one task per distinct action, duplicates
  folded. Guards independent of the model enforce the same rules.
- [x] A review with no surviving task is not saveable; it shows what was heard
  and offers discard or record again.
- [x] Explicit confirmation before every destructive exit; a cancel affordance
  on the processing screen; resume restores the live tail and the timer.
- [x] Owner-initiated, one-shot recovery from a terminal provider failure by
  extracting provisional tasks from the browser transcript text, visibly
  labelled provisional on web and mobile, within the existing cost caps and
  consent.

**Out of scope — explicitly confirmed by the human**

- [x] Rewriting spec `002-async-voice-workflows` in place. Its normative files
  stay hash-frozen as delivered history; this feature narrows 002 US1, required
  outcome 2 and SC-004 and records the change (decided in the 2026-09-05
  conversation: "путь A", new feature number).
- [x] A "leave and come back later" affordance on the processing screen: there
  is no in-app list of in-flight brain dumps to return to, so a leave button
  would orphan the operation. *Derived from the UX audit; not raised by the
  founder.*
- [x] Automatic (non-owner-initiated) fallback to preview-text extraction. The
  recovery is an explicit choice, never silently selected (ADR-0002).
- [x] Any new provider, model or spend ceiling. The recovery reuses the
  reconciler's per-role cap and the operation's cumulative cap.
- [x] Mobile browser-preview capture (mobile has no preview lane).

**Confirmed by**: Maksim Kravchuk on 2026-09-05 — the scope-in items are the
founder's numbered asks; the scope-out list was stated to the founder in the
same conversation and closed by «просто доделай».

## 5. Constraints

- **Deadline**: 2026-09-05 (the fix is already in review on PR #194; this
  record follows it).
- **Platform**: web first (recording, processing, review, recovery); mobile
  must render the new recovery action and the provisional label.
- **Offline behavior**: not applicable beyond today's behaviour (the operation
  is server-durable; the browser preview is best-effort and only a status).
- **Must not break**: ADR-0002 invariants (patch log, no silent overwrite,
  lineage and lock rules for pre-existing proposals, two-database commit saga,
  idempotent commands, owner scoping, `X-Correlation-ID`); grounding (every
  proposal cites real segments) and language fidelity of the reconciler;
  consent gating; the `voice_brain_dump` flag semantics (reads, cancel,
  withdraw-consent and raw-audio deletion stay reachable when OFF).
- **Budget / provider cost limits**: no new spend path. The preview-text
  extraction is one reconciler call bounded by the reconciler role cap and
  the cumulative operation cap; it is offered at most once per operation.

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management and is
never feature-flagged. What this feature adds:

- **New durable records**: none of a new kind. The preview-text recovery adds a
  provider run of the existing kind to the existing operation document, with a
  new checkpoint name; task receipts already carry `reconciliation_quality`.
- **Consent**: the browser transcript is sent to the task-extraction provider
  only when the owner explicitly asks and only while the operation's external
  processing consent stands; the text exists in the operation only because
  that consent was granted before the first preview segment was accepted. After
  consent withdrawal the recovery is unavailable. The point-of-choice copy
  names the destination.
- **Retention**: unchanged — raw audio 24 h after reconciliation, uncommitted
  working artifacts 7 days, cancel deletes audio immediately.
- **Export**: unchanged; brain-dump operations are already part of the account
  export.
- **Purge**: covered by account purge; no extension needed.
- **Residency / other obligations**: none new.

## 7. Existing-system dependencies

- **Backend surfaces**: `app/workflows/voice_brain_dump/` (service, domain,
  reconciler adapter), `app/api/tasks.py` brain-dump routes, response schemas.
- **Frontend surfaces**: the brain-dump overlay (recording, processing, review,
  recovery, saved states).
- **Mobile**: must change minimally — render the new recovery action when the
  server advertises it; the provisional label already exists.
- **AI providers**: used — accurate STT (unchanged) and the text reconciler
  (prompt revised to GTD next actions; also used for the preview-text
  recovery).
- **Primary loop impact**: capture → atomic items is where this lives. Capture
  now yields clean next actions instead of raw fragments, so clarify/approve
  starts from intent rather than from cleanup. No impact on routing, Weekly
  Review or evidence.

## 8. Definition of done

- [x] Recording the reference utterance and pressing Stop shows a review of
  exactly «Купить молоко», «Сходить в магазин», «Покрасить комнату», Send is
  enabled without deleting anything, and saving creates exactly those three
  inbox tasks.
- [x] While speaking, the screen shows what was said as a transcript status and
  no task cards; interim hypotheses appear beside the microphone, settled
  utterances in the readout.
- [x] A dump that contains only fillers ends in a review that says no tasks
  were proposed, shows what was heard, and cannot be saved.
- [x] Discard, Discard all, Delete recording and Cancel processing each ask
  for confirmation; the safe choice has focus; Escape keeps the recording.
- [x] Reopening an in-progress recording shows the last utterance beside the
  microphone and a timer that continues from the captured duration.
- [x] After a terminal provider failure with browser transcript present, the
  owner sees "Extract tasks from the browser transcript", one press leads to a
  review labelled provisional on web and mobile, and saving creates inbox
  tasks whose receipts record the provisional origin. The action is offered
  once per operation and never after consent withdrawal.

## Deferred to /speckit-clarify

- [ ] None. The founder closed elicitation with «просто доделай»; open choices
  were decided by the agent and are listed in the spec's Clarifications
  section as decisions, each attributed.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| ADR-0002 (2026-07): "If audio is intact, offer an accurate-transcript retry from that audio — not a retry over fast text." | Founder, 2026-09-05: «у нас превью же текст, почему нельзя восстановить?» | Owner-initiated, one-shot, visibly-labelled, provisional-only extraction from preview text is allowed after a terminal failure; automatic or silent fallback stays forbidden. Recorded as a dated ADR-0002 amendment. | founder (ask) + agent (design), 2026-09-05 |
| Agent, 2026-09-05: "the recording can no longer be salvaged as provisional junk; terminal failure offers cancel only" | Founder: «просто доделай» after the recovery options were laid out | The reconciler-based recovery (not manual task entry) is built. | founder, 2026-09-05 |
