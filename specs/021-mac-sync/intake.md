# Business Intake: Mac ↔ backend sync

**Feature**: `specs/[###-mac-sync]/` (assigned by `/speckit-specify`)
**Interviewed**: 2026-10-06
**Interviewee**: Max (product owner)

<!--
  Produced by /speckit-interview before /speckit-specify. Stage 0 assessment was
  skipped: the owner already decided on 2026-10-05 (specs/020-weekly-review/intake.md,
  contradictions table) that Mac↔backend sync is a separate spec and a prerequisite
  for the Mac part of weekly review (020 US6, FR-041). The ask is a known gap, not a
  speculative idea.

  Interview mode: the owner asked for minimal involvement ("синхронизация достаточно
  простая история, и ты сам справишься, особо меня не привлекая") and stated the
  product shape in one message. Every other heading below is filled from that
  message, from the shipped iPhone behaviour (docs/native-ios-app.md) and from
  accepted ADRs, and was read back to the owner as defaults; the owner confirmed
  scope and non-goals (see "Confirmed by").
-->

## The ask, as given

> А выравнивание э, всех приложений на тему синхронизации было сделано? То есть э, клиент на macOS, он у нас перестанет быть только локальным?

> Да, давай делать. Но мне кажется, что синхронизация достаточно простая история, и ты сам справишься, особо меня не привлекая. Генерально я думаю, что э, все это должно быть фоново, как в других GTD-задачниках. Э, только в случае ошибки пользователь должен хоть как-то об этом быть уведомлен. То есть, например, мы не можем отправить и не можем загрузить. Тогда мы пользователю показываем какое-то сообщение компактное об ошибке. Сам процесс обновления данных показывается каким-нибудь маленьким лоадером, где-то не прерывая флоу пользователя, что-то такое. Ну и где-то мы пишем там рядом последний раз задачи были синхронизированы там столько-то минут назад, что-нибудь типа такого. То есть очень компактно все это должно быть, потому что это не должно бросаться в глаза пользователя, не должно об этом думать.

## 1. Problem

- **Whose problem**: anyone who uses Brain Buddy on a Mac and on another device (iPhone or web), starting with the owner.
- **How it shows up today**: the Mac app is a local-only workspace ("Stored on this Mac", `~/Library/Application Support/BrainBuddyMac/local-gtd.json`). A task captured on the Mac never reaches the iPhone or web and the reverse; the Mac's hidden sign-in path talks to the server only while online and has no offline queue, so it is not used.
- **What it costs**: two separate task systems, which breaks the GTD "one trusted system" premise; captures on the Mac (global quick-capture hotkey, voice) are stranded; weekly review on the Mac (020 US6) is blocked.
- **If we build nothing**: the Mac stays a demo; the owner cannot use it as a daily client; 020 US6 never ships.

## 2. Customer and persona

- **Primary**: Brain Buddy users with a Mac and at least one other client (iPhone, web), ADHD users as the design centre: sync must not ask for attention.
- **Secondary**: Mac-only users who never sign in (the Mac keeps working locally, as the iPhone does without an account).
- **Deployment shape**: multi-tenant, per-owner data, invite-gated signup (unchanged).

## 3. Business objective and KPI

No baseline exists for Mac (it does not sync today); iPhone ↔ web is the reference behaviour.

| metric | baseline today | target | by when |
|---|---|---|---|
| A change made on one signed-in device appears on another open, online device | never (Mac) | within 60 s in ≥ 95% of checks | at release |
| Changes lost across offline periods, app quit and relaunch | n/a | 0 in the offline/relaunch test matrix | at release |
| Local Mac data kept on first sign-in (tasks, projects, tags, subtasks, comments) | n/a | 100% present on the account afterwards; nothing duplicated by name for projects and tags | at release |
| Sync failures shown to the person | n/a | 100% shown as a compact, non-blocking message with a reference id; 0 modal dialogs or interruptions for routine sync | at release |

## 4. Scope boundary

**In scope**

- [ ] **Mac signs in and syncs** with the same account as iPhone and web: tasks (with subtasks and comments), projects, tags, all four lists, order, dates, priority, completion and cancellation.
- [ ] **Background, automatic sync** "as in other GTD apps": on launch, when the app becomes active, shortly after every local change, when the network comes back, and periodically while the app is open; no manual step needed. A "Sync now" command exists but is never required.
- [ ] **Offline-first Mac**: everything works offline (capture, quick capture hotkey, voice-to-draft, edits, reviews); changes queue and send later; quitting the app loses nothing.
- [ ] **Account-less Mac stays possible**: without signing in the Mac works locally as today. Signing in for the first time uploads the existing Mac data into the account, merging projects and tags by name, as the iPhone does.
- [ ] **Compact sync status** on Mac: a small activity indicator that never blocks work, and a quiet "Synced N min ago" line near the sidebar footer (where "Stored on this Mac" is today).
- [ ] **Compact sync errors**: when sending or loading fails (offline for long, server down, sign-in expired, a change rejected), one short message in the same place, with a reference id and a way to retry or sign in again; details on demand, never a modal.
- [ ] **Same behaviour on iPhone**: the iPhone already syncs in the background; its status and error presentation is aligned to the same compact pattern and wording (no new iPhone screens; existing Sync settings and Sync issues stay).
- [ ] **Mac features keep working after sign-in** (owner default, read back):
  - project archive keeps task membership and can be undone (unarchive) — implements accepted ADR-0020 on the backend, so it also works the same on iPhone and web;
  - a project's desired outcome syncs with the project (new project field on the account); other clients keep it intact and may show it later;
  - the Mac's Waiting / Someday / Project review "reviewed" receipts stay on this Mac until weekly review (020) replaces them.

**Out of scope — explicitly confirmed by the human**

- [ ] Weekly review on the Mac (020 US6) — follows this spec, separately.
- [ ] Sync while the Mac app is not running (no background agent or login item); real-time push (websockets); a change feed on the backend — periodic pull is enough at today's scale.
- [ ] Conflict-resolution UI: same rule as the iPhone (last pushed change wins per field; rejected changes go to Sync issues).
- [ ] Web offline mode or any web sync indicator: the web is online-only and already shows request errors with a reference id.
- [ ] Sharing, collaboration, multiple accounts at once on one Mac.
- [ ] Mac App Store distribution, signing and notarisation, auto-update.
- [ ] Moving voice-to-draft (WhisperKit) to the server: voice stays on the Mac.
- [ ] Changing what the iPhone syncs or how the server stores tasks beyond the ADR-0020 archive semantics and the project desired-outcome field.

**Confirmed by**: Max on 2026-10-06. Scope and non-goals confirmed as read back ("Подтверждаю"). Mac-only features: owner chose "complete the server" — implement accepted ADR-0020 archive semantics (keep membership, unarchive) on the backend for every client, and add the project desired-outcome field.

## 5. Constraints

- **Deadline**: none. Independent of 020; may be implemented in parallel with 020, but Mac code that 020 PR-06 touches (`macos/Sources/BrainBuddyMac/ContentView.swift` sidebar) is sequenced after PR-06.
- **Platform**: macOS 26 (current Mac target); iPhone presentation alignment only.
- **Offline behavior**: required on Mac for everything except sign-in itself.
- **Must not break**: the iPhone's offline-first outbox/replay sync and its account linking; idempotent, owner-serialized task commands; session auth (HttpOnly cookie; native clients keep the session token in the Keychain); ADR-0006 four open lists; existing Mac local data (no loss on upgrade, signed in or not).
- **Budget / provider cost limits**: no AI or paid provider is involved.

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management. This feature adds:

- **New durable records**: on the server, only the project desired-outcome field (exported and purged with the project). On the Mac, a local copy of the account's tasks and a queue of unsent changes (as on the iPhone), plus the session token in the macOS Keychain.
- **Consent**: none new — syncing is the purpose of signing in; signing in is the explicit act. Account-less use sends nothing.
- **Retention**: server data as today. Mac local copy: kept until sign-out or account switch; sign-out with unsent changes warns first (as on the iPhone).
- **Export**: desired outcome is included with projects in the existing ZIP export.
- **Purge**: covered by account purge; after purge or deletion the Mac's session fails and it shows "Sign in again", keeping its local copy until the person signs out.
- **Residency / other obligations**: logs and metrics carry only ids, counts and error classes, never task text (constitution I, IV).

## 7. Existing-system dependencies

- **Backend surfaces**: tasks module — ADR-0020 archive-keeps-membership and unarchive; project desired outcome field; existing task/project/tag endpoints, idempotency keys and session auth otherwise unchanged.
- **Frontend surfaces**: web project archive and unarchive follow ADR-0020; no sync UI.
- **Mobile**: iPhone — compact sync status and error wording aligned with Mac; uses the new archive semantics; keeps the project desired outcome intact.
- **macOS**: replaces the local-only store with the shared sync behaviour used by the iPhone (`ios/BrainBuddyKit`), migrates `local-gtd.json` without loss, adds sign-in, status and error UI.
- **AI providers**: not used.
- **Primary loop impact**: enables capture on the Mac (quick capture, voice) to feed the same clarify → organise → weekly review loop as iPhone and web; prerequisite for 020 US6.

## 8. Definition of done

- [ ] The owner signs in on the Mac with existing local data; every local task, project and tag is on the account afterwards, nothing duplicated, and the Mac keeps working.
- [ ] A task captured on the Mac with the global hotkey appears on the iPhone within a minute, and an edit on the iPhone appears on the open Mac within a minute, with no manual action.
- [ ] With the Mac offline (Wi-Fi off), the owner keeps working for a while, quits and reopens the app; after reconnecting, every change reaches the iPhone and web.
- [ ] During sync only a small indicator moves; "Synced N min ago" is visible in the sidebar footer; with the server unreachable a short message with a reference id appears there, without any dialog.

## Deferred to /speckit-clarify

- [ ] Periodic pull interval while the Mac app is open (iPhone pulls when the last pull is older than 60 s within a cycle).
- [ ] Exact wording and placement of the compact status on iPhone list screens versus the Mac sidebar footer.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| 020 intake: macOS POC principle "review never changes GTD state automatically", Mac reviews local | Mac now syncs | Mac's local review receipts stay device-local until 020 replaces them; no conflict with sync | Max, 2026-10-06 (scope confirmed) |
