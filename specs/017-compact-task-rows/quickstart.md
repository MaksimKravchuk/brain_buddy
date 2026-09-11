# Quickstart: Validate Compact Task Rows

## Prerequisites

- Node dependencies already installed under `frontend/`.
- A purpose-created authenticated BrainBuddy account seeded only with synthetic Task,
  Tag, Project and agent names. Never use real user content in screenshots or evidence.
- For agent checks, `external_agent_relay` enabled and at least two tested eligible
  connections with purpose-created synthetic hostnames. Keep every real address,
  credential, token and fingerprint out of frame.

## Automated checks

Run the smallest behavior suite first:

```bash
cd frontend && npm test -- --run src/features/tasks/__tests__/TaskListPage.test.tsx src/features/tasks/__tests__/TaskAgentControl.test.tsx src/features/tasks/__tests__/taskAgentPreference.test.ts src/features/agents/__tests__/agentCopy.test.ts
cd frontend && npm run test:e2e -- tests/e2e/compact-task-rows.spec.ts
```

Then run the required frontend gate and production build:

```bash
make test-frontend
cd frontend && npm run build
```

Before delivery, run repository specification validation and the full required chain:

```bash
make check-specs
make verify-all
```

## Manual D-01 / D-03 desktop check — 1440 × 900

1. Open a Task list containing at least ten Tasks.
2. Confirm ten collapsed headers are visible and each measures 44 px.
3. Confirm title, short Tags, and right-side agent controls stay on one line.
4. Confirm no Project/List text or Delete action appears.
5. Compare Queued, Running, Needs you, Reported, and Failed controls: each must be
   184 × 28 px with aligned agent/status columns and no arrow.
6. Tab through completion, title, split controls, menu, and assigned control; confirm
   visible focus and useful accessible names.
7. Run the Axe scan and confirm there are no serious or critical violations on the
   changed surface.

## Manual D-02 inline-detail check

1. Open a Task by its title and by non-control row space.
2. Confirm detail appears directly below the row with no sheet, scrim, modal role, or
   inert list.
3. Edit title/details, exercise adjacent navigation, add a subtask/comment, and inspect
   run detail.
4. Click/select plain text inside detail and confirm nothing collapses. Close with the
   control, same row header, and Escape outside nested controls; verify route collapse
   and focus restoration. With a hand-off review open, one Escape closes only review.
5. Reload a Task URL and use Back/Forward to confirm route restoration.
6. Open filtered/paginated URLs for valid Tasks outside the rendered rows. Confirm the
   exact precedence: matching current route after filter clearing → resolvable Project
   → open lifecycle route → Next actions for terminal/no-Project; cancelled fallback
   carries `showCancelled=1`. Confirm one redirect, a ten-page automatic bound,
   cancellation on route change, and Retry/Load more on failure/exhaustion.
7. Open a missing and another-owner ID; confirm the same non-leaking list-level error,
   no invented row, and no redirect loop.
8. Edit a field and immediately close; confirm the pending save finishes or remains
   recoverable. Complete an expanded Task; confirm detail collapses, the row moves to
   Completed, and focus follows the moved row (or the documented fallback).

## Manual hand-off consent check

1. On an unassigned Task, activate the robot shortcut. Confirm review opens with the
   remembered eligible connection, or the first eligible connection if none is valid.
2. Close review without confirming; confirm no run was created and the remembered ID
   did not change.
3. Choose a different agent from the arrow menu; confirm that exact ID is preselected.
4. Complete review and confirmation; confirm the row changes to the one assigned
   control, focus follows that replacement, and the confirmed connection becomes the
   next shortcut elsewhere.
5. Repeat a confirmed hand-off from the existing inline-detail action; confirm it also
   becomes the remembered shortcut. Close or fail a review and confirm it does not.
6. Turn relay rollout OFF: new split controls disappear, existing run controls remain.
7. Go offline before assignment: the split still opens review, the review remains
   readable, Send is disabled, and copy states that nothing is queued.

## Browser preference lifecycle check

1. Confirm storage contains only `{connectionId, confirmedAt}` under an API/owner key.
2. Exercise logout, 401 session loss, account deletion, and A→B transition; the
   departing owner's key is removed before the next Task surface paints.
3. Seed malformed and >30-day keys for multiple identities, then launch/focus the app;
   the cross-identity sweep removes them. Confirm unavailable storage fails closed.
4. Verify the privacy page/retention schedule state that the record never reaches the
   server/export, is ineligible after 30 days, is swept when BrainBuddy runs, and may
   require browser site-data deletion if the app is never run again.

## Manual D-04 responsive/resilience check — 390 × 851

Confirm no page-level horizontal scroll, 44 px collapsed rows, reachable 44 px target
slots, progressive metadata hiding, inline one-column detail, and usable loading,
filtered-empty, fetch-error, partial-summary, and cached/offline presentations.

## Post-deploy evidence

Against the exact deployed SHA, retain synthetic/redacted screenshots at 1440 × 900,
768 × 900, and 390 × 851; record CI/release/smoke links and relay-flag read-back. Do
not claim overall Done if the separately governed relay-ON state cannot be exercised.
Using the synthetic smoke identity, actually scan ten rows, edit/open/close inline
detail, verify canonical recovery/focus, and inspect the rollout-appropriate agent
control; the generic production smoke is necessary but not sufficient.
