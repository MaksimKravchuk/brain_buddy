# Business Intake: Weekly Review

**Feature**: `specs/020-weekly-review/`
**Interviewed**: 2026-10-05
**Interviewee**: Max (product owner)

<!--
  Produced by /speckit-interview before /speckit-specify. Stage 0 assessment
  (`/speckit-assess-*`) was not run as a separate campaign: the owner-reviewed
  concept `.specify/assessments/weekly-review/concept.md` (PR #262) already
  covers problem, research, options and four owner decisions; there is no
  `decision.md`, so no kill / needs-clarification verdict exists to obey.
  Weekly Review is a named stage of the constitution's primary loop and the
  owner explicitly asked to build it.
-->

## The ask, as given

> Давай сделаем в iOS приложение, ну и в целом мы ее сначала разработаем, концепцию еженедельного ревью по задачам. Что мне важно? Нужно, чтобы пользователю дать хороший и удобный инструмент для того, чтобы следовать жизни практике еженедельного ревью задач. В идеале в Next Action у пользователя должно на неделю быть там, ну не знаю сколько, Разумное ограничение это 35 задач, не больше, а то и меньше, потому что ты не можешь 5 задач в день делать. Ну, хз, короче, э, давай мы количество задач не важно, но важно, что задача не висит с одним и тем же неймом, с одним и тем же названием в Next Action больше, чем э, две недели. Мне кажется, две недели это уже прям очень долго. Если задача за две недели не сделана, и она next action, тогда ее надо перенести или в someday как-то, или переименовать. Еще э, что нам нужно? Вообще, посмотри, у нас там был где-то анализ конкурентных э, проектов, в том числе хаос контроля. И давай подумаем, под GT практика, как это все рекомендуют вести. Uh, еще помним о когнитивно-поведенческой терапии и о том, что основные пользователи это СДВГшники, uh, они тоже могут факапить с этим совсем.

## Owner decisions already taken (2026-10-05, before the interview)

| # | Question | Decision |
|---|---|---|
| D1 | Review skipped, task 14+ days in Next | Auto-park to Someday on day 21, with a visible "while you were away" screen and one-tap return |
| D2 | Keep a stalled task unchanged | Once per formulation, with a reason, +7 days |
| D3 | Number of tasks in Next | Capacity mirror (throughput-based), no limit |
| D4 | AI navigator (first-step suggestions) | In the MVP |

## 1. Problem

- **Whose problem**: people who run GTD on Brain Buddy, primarily users with ADHD (owner statement), starting with the owner.
- **How it shows up today**: Next Actions accumulates tasks the person has mentally let go of; the same formulation sits for weeks; no review exists (web and iOS show a disabled "coming soon" row). The macOS POC has local Waiting/Someday review only.
- **What it costs**: backlog rot → guilt → avoidance → abandonment of the system (research synthesis F1/F2; competitor brief: review is the weakest point of Chaos Control and Todoist).
- **If we build nothing**: the primary loop stops at "organize"; the constitution's "smart Weekly Review" stage stays a placeholder.

## 2. Customer and persona

- **Primary**: a broad audience of GTD practitioners and newcomers, with ADHD users as the design centre (short steps, one decision at a time, no shame mechanics). Owner chose "broad audience" over "owner + invite beta": the feature must make sense to someone who has never done a GTD weekly review.
- **Secondary**: the owner as first daily user.
- **Deployment shape**: multi-tenant (per-owner data, invite-gated signup today). Positioning is not "an ADHD app" (competitor brief); the ADHD focus is a design constraint, not a marketing label.

## 3. Business objective and KPI

Measured per active user after 8 weeks of use. No baseline exists: there is no review today, and Next-age cannot be measured until the formulation clock ships.

| metric | baseline today | target | by when |
|---|---|---|---|
| Weeks with at least a partial review | n/a (no review exists) | ≥ 3 of every 4 weeks | 8 weeks after the user's first review |
| Next formulations older than the user's threshold **without a decision**, immediately after a completed review | unknown (no clock) | 0 | every completed review |
| "Clear how to start the week?" answered "yes" at the end of a review | n/a | ≥ 70% of answered reviews | 8 weeks after the user's first review |

Supporting (not gating): distribution of decisions and stall reasons; re-stall rate after reformulation; share of auto-parked tasks later returned to Next; median formulation age in Next.

## 4. Scope boundary

**In scope**

- [ ] **Formulation clock and age markers** in Next (fresh / ageing / asks for a decision / moves to Someday tomorrow) — iOS and web.
- [ ] **Decision card** for a task past the threshold: done, reformulate, find a first step (old title kept in notes), waiting, Someday, cancel, or keep +7 days once per formulation with a reason; optional stall reason that highlights a fitting action; reachable from task detail on any day, not only during the review.
- [ ] **Configurable threshold** 7 / 14 / 21 / 28 days (default 14); **auto-park** to Someday 7 days after the threshold; "while you were away" with one-tap return; shame-free restart after 3+ weeks without a review; a grace period for tasks already old at release.
- [ ] **AI navigator**: 1–3 first-step suggestions for a stalled task and a first step for a project without a next action; never writes without confirmation.
  - **Apple platforms (iOS, macOS)**: Apple's on-device model (Foundation Models) — data does not leave the device, works offline.
  - **Fallback on Apple platforms** (device without Apple Intelligence, Apple Intelligence off, or task language not supported on device): honestly say the on-device model is unavailable and offer the server provider under a separate one-time, revocable consent with the provider named.
  - **Web**: server provider under one-time, revocable consent with the provider named and cost caps.
- [ ] **Guided review**, quick (~5 min) and full (~20 min): wins of the week, mind sweep, Inbox to zero, decisions, rest of Next with the capacity mirror, Waiting, projects without a next action, Someday, upcoming dates, summary with "clear how to start the week?". Every step skippable, resumable; a partial review counts.
- [ ] **Schedule and cue**: review day/time (default Friday 16:00, local), one notification, iOS widget badge; one onboarding screen before the first review.
- [ ] **History**: review sessions, decisions and reasons stored per account, in ZIP export, removed by account purge.
- [ ] **Full parity** iOS ↔ web on a shared backend; iOS offline-first (including on-device AI).
- [ ] **macOS**: the same review on the Mac app, over the same synced tasks as iOS and web. **Prerequisite**: the Mac app must first sync with the backend (today it is a local-only POC). Mac sync is a separate, larger capability; the Mac part of this feature is delivered after it.

**Out of scope — explicitly confirmed by the human**

- [ ] "Weekly focus" (pick up to 5 tasks for the week) — an agent proposal, never agreed.
- [ ] Any hard or soft cap on the number of Next tasks (capacity mirror only).
- [ ] Streaks, points, badges or other gamification.
- [ ] Voice-led review (ADR-0002 `weekly_review_voice`) — later phase.
- [ ] Review of work delegated to external agents (relay 007) — later phase.
- [ ] Defer/start dates ("tickler"), time blocking, calendar integration, time estimates.
- [ ] Any automatic task change other than Next → Someday auto-park; AI never changes a task without confirmation.
- [ ] Repeated or escalating reminders.
- [ ] Full app localisation and a GTD course.
- [ ] ~~Changes to the local macOS POC~~ — **reversed**: macOS is in scope after Mac sync (see contradictions table).

**Confirmed by**: Max on 2026-10-05. Out-of-scope list confirmed as read back (with the macOS item later reversed). In-scope list confirmed after two amendments: on-device Apple AI; macOS after Mac sync. Mac↔backend sync is a **separate spec**; the Mac part of this feature depends on it and ships last. iOS and web do not wait for Mac.

## 5. Constraints

- **Deadline**: none. One spec, delivered in self-useful increments: (1) the N-day rule, decision card, auto-park and age markers on backend + iOS + web; (2) AI navigator; (3) the full guided review. Exact slice boundaries are fixed at `/speckit-tasks`.
- **Platform**: full parity — iOS and web both get the complete feature (owner chose "full parity" over "iOS first, web markers only"). Backend is required for both.
- **Offline behavior**: required on iOS for everything, including AI suggestions via the on-device model (the app already works offline and without an account). Only the server fallback needs a network; it is honestly unavailable offline.
- **Language**: same as the rest of the product today; AI answers in the language of the task (RU/EN as in brain dump). Full localisation is a separate initiative.
- **Threshold**: user-configurable, chosen from 7 / 14 / 21 / 28 days, default 14; auto-park always fires 7 days after the threshold (D1 generalised). The one-time extension (D2) is +7 days.
- **Onboarding**: one short screen before the first review explaining why the review exists, the N-day rule and auto-park; review day/time is chosen there. Afterwards, short inline hints on the steps. No GTD course.
- **Must not break**: idempotent, owner-serialized task commands; iOS offline-first outbox/replay sync; ADR-0006 four open lists (no fifth list); consent gating for AI; GDPR account management.
- **Default review time**: Friday 16:00 in the user's local time zone (owner choice: close the working week while it is fresh); changeable during onboarding and in settings.
- **Budget / provider cost limits**: AI navigator stays within the existing provider cost-cap mechanism (`.env.example`); exact per-call budget deferred to clarify.

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management. This feature adds:

- **New durable records**: per-task formulation clock and park markers; review sessions with summaries; per-task review decisions including an optional stall reason (one of which, "aversive / no energy", is behavioural and personally sensitive) and optional reason text; review settings (threshold, day, time, time zone); AI consent state for the navigator.
- **Consent**:
  - On-device navigator (Apple platforms): no data leaves the device; the product still says plainly that suggestions come from the on-device model.
  - Server navigator (web, and Apple-platform fallback): asks once, before the first server suggestion, showing what is sent (title, notes, project, chosen reason) and to which provider; revocable in settings. Every request requires *current* consent (constitution I) — a revoked consent stops requests immediately.
  - Without AI the review works fully.
- **Retention**: same as tasks — kept for the life of the account.
- **Export**: included in the existing ZIP export.
- **Purge**: removed by the existing account purge.
- **Residency / other obligations**: logs and metrics carry only IDs, decision/reason codes and counts — never task titles, reason text or AI output (constitution I, IV).

## 7. Existing-system dependencies

- **Backend surfaces**: tasks module (`backend/app/modules/tasks/`) — new formulation clock and park markers on tasks, server-side auto-park job; new review records and settings; AI suggestion endpoint behind consent and cost caps; account export/purge.
- **Frontend surfaces**: web app — age markers in Next, decision card, auto-parked list with return, full guided review, onboarding, settings; replaces the disabled "Weekly review — Coming soon" entry.
- **Mobile**: must change — iOS gets the same feature set; offline-first except AI; replaces the deferred "Weekly review" row in the Lists hub; Next Actions widget shows the "asks for a decision" count.
- **AI providers**: Apple on-device Foundation Models on iOS/macOS (requires iOS 26 / macOS 26 and an Apple Intelligence-capable device with Apple Intelligence enabled); server provider, consent-gated and named, on web and as the Apple-platform fallback.
- **macOS**: `macos/` is a local-only POC today; the Mac part of this feature depends on a separate Mac↔backend sync capability.
- **Primary loop impact**: implements the "smart Weekly Review" stage of the constitution's loop for native tasks; feeds back into clarify (reformulation / first step) and organize (Someday, Waiting). Voice-led review (ADR-0002) stays a later phase.
- **Decision records to supersede/amend**: ADR-0006 and the design skill ("Weekly Review deferred, no cadence, no due state"); open decision D-11 in `docs/vnext-cloud-design-build-contract.md`; ADR-0001's capture-based review model, and the macOS POC principle "review never changes GTD state automatically" (auto-park is the first automatic state change).

## 8. Definition of done

- [ ] The owner completes the review on iOS (TestFlight) for three consecutive weeks on real tasks: quick review fits in ~5 minutes, full review in ~20, and afterwards no Next formulation older than the threshold is left without a decision.
- [ ] Auto-park is visible and reversible: after a skipped review the task shows "moves to Someday tomorrow" a day before, is parked on schedule, and the next review opens with "while you were away" where one tap returns it to Next — on both iOS and web.
- [ ] The AI navigator actually helps: on the owner's own stalled tasks at least half of the first-step suggestions are accepted (as is or edited), and no suggestion invents facts about the owner's life.
- [ ] Offline and parity: a review done on iOS in airplane mode (with on-device AI where available) syncs, and the same decisions and the review summary are visible on web; a review started on the phone shows its summary on web.

## Deferred to /speckit-clarify

- [ ] Per-call AI budget and which existing server provider/model serves the navigator on web and as fallback.
- [ ] **Risk:** whether Apple's on-device model supports Russian. Public sources checked on 2026-10-05 do not confirm it unambiguously. If it does not, Russian-language tasks always use the server fallback on Apple platforms.
- [ ] Whether to use iOS 27 Foundation Models additions (larger on-device model, provider-swappable LanguageModel protocol) or stay on the iOS 26 baseline the app targets today.
- [ ] Exact semantics of a "substantive" title change (what counts as reformulation vs. a cosmetic edit).
- [ ] Whether changing the threshold re-evaluates existing tasks immediately (e.g. 28 → 7 could mark many tasks at once) and how that is softened.
- [ ] Behaviour of the "while you were away" bulk return and of the post-release restart for already-old tasks (concept §2: auto-park counted no earlier than 14 days after release).
- [ ] Whether Waiting and Someday review steps reuse the macOS POC receipts as-is (7-day Waiting, 30-day Someday).

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| "Reasonable limit is 35 tasks" | "The number of tasks does not matter" (same message) | Capacity mirror, no limit (D3) | Max, 2026-10-05 |
| Concept recommended a fixed 14/21-day threshold | Interview: threshold is user-configurable | Configurable wins | Max, 2026-10-05 |
| Scope playback: "changes to the macOS POC" confirmed out of scope | Same playback: "AI navigator on iOS/macOS on Apple local models"; then "macOS also in scope", then "Mac sync first" | macOS in scope; Mac review delivered after Mac↔backend sync, which is a prerequisite capability | Max, 2026-10-05 |
| Concept / intake: AI via server provider, unavailable offline | Playback: AI on Apple's on-device models | On-device on Apple platforms, server provider with consent on web and as fallback | Max, 2026-10-05 |
| Concept listed "Weekly focus" (phase 1.5) | Interview: "not sure we agreed on weekly focus — what is that?" | It was an agent proposal, never agreed; removed from scope | Max, 2026-10-05 |
