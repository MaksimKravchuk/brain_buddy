# Business Intake: Completed Task Profile Count

**Feature**: `specs/018-completed-task-profile-count/`
**Interviewed**: 2026-09-05
**Interviewee**: Max

The optional assessment stage was skipped because this is a small, explicitly
requested profile readout with a narrow acceptance path and no new product
domain.

## The ask, as given

> давай добавим счетчик выполненых задача в профиль пользователя. Простая строка текста и чимло

## 1. Problem

- **Whose problem**: an authenticated BrainBuddy user checking their own profile.
- **How it shows up today**: the Profile card exposes the display name but no summary of finished work.
- **What it costs**: the user cannot confirm completed-task progress from the profile and must inspect task lists instead.
- **If we build nothing**: the profile remains silent about completed tasks.

## 2. Customer and persona

- **Primary**: the signed-in owner of the account and tasks being counted.
- **Secondary**: none for this slice.
- **Deployment shape**: multi-tenant; every count must remain owner-scoped.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| Supported profile-count acceptance cases | 0 of 4 (zero, nonzero, complete +1, reopen -1) | 4 of 4 | acceptance of this feature |
| Cross-owner tasks included in the count | not exposed | 0 | every request |

These delivery KPIs grade the observable slice; adoption is not claimed before release.

## 4. Scope boundary

**In scope**

- [x] Show the exact text `Completed tasks: N` in the signed-in Web Profile card.
- [x] Count the current user's top-level tasks whose current state is `completed`.
- [x] Reflect completion and reopening so the value moves by +1 and -1 respectively.

**Out of scope — explicitly confirmed by the human**

- [x] Lifetime-completion history, cancelled tasks, subtasks, per-project or time-period breakdowns.
- [x] Mobile UI, charts, badges, goals, gamification, a new persisted counter, and release/deployment.

**Confirmed by**: Max in the task conversation on 2026-09-05.

## 5. Constraints

- **Deadline**: none stated.
- **Platform**: web profile only.
- **Offline behavior**: not applicable; the profile already requires its authenticated account request.
- **Must not break**: authentication, owner isolation, successful profile editing, account data rights, task complete/reopen behavior, or existing API consumers. The one intentional availability change is explicit: if the Tasks count query fails, profile/email mutation fails before writing rather than returning an Account response with an unknown count.
- **Budget / provider cost limits**: no AI/provider call and no new external service.

## 6. Compliance obligation

- **New durable records**: none; the value is derived from existing owner-scoped task state.
- **Consent**: no new consent; no data leaves BrainBuddy.
- **Retention**: unchanged because no new record is stored.
- **Export**: unchanged; the existing export already includes the underlying tasks.
- **Purge**: unchanged; account purge already removes those tasks.
- **Residency / other obligations**: none added.

## 7. Existing-system dependencies

- **Backend surfaces**: authenticated account projection and the native task repository.
- **Frontend surfaces**: the existing Account settings Profile card and account API type.
- **Mobile**: unaffected.
- **AI providers**: not used.
- **Primary loop impact**: no impact on capture → atomic items → clarify/approve → route or CRT candidate → Weekly Review → evidence/results; this is a read-only profile projection of existing task outcomes.

## 8. Definition of done

- [x] A signed-in user sees `Completed tasks: 0` when no current top-level task is completed.
- [x] The line shows the exact nonzero total for that user and excludes another user's tasks and subtasks.
- [x] Completing one top-level task changes the next observed profile value by +1; reopening it changes the value by -1.
- [x] Focused backend, frontend and browser tests plus the repository's required verification gates pass with Allure taxonomy.

## Deferred to /speckit-clarify

- [x] None. The user fixed the platform, copy shape, current-state semantics and non-goals.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| none | none | no contradiction | Max |
