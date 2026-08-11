# Quickstart: validating feature 006

## Prerequisites

```bash
make install-mobile
make install-backend        # the integration run needs a disposable local backend
```

The rollout flag defaults OFF. With it off, the task screen is exactly today's
read-only screen (M-01c) — that is the correct observation, not a failure.

## Automated evidence

```bash
make test-mobile            # pure modules: queue reducer, conflict decision, sync status
make integration-mobile     # real API client against a disposable local backend
make typecheck-mobile
make build-mobile           # Metro bundle
```

What each is actually evidence of, stated honestly because the acceptance stage
will be asked to grade it:

| command | proves | does not prove |
|---|---|---|
| `make test-mobile` | coalescing, identity binding, conflict outcomes, staleness | that any of it is wired to a screen |
| `make integration-mobile` | the wire behaviour, including a real stale-revision rejection | anything about rendering |
| `make typecheck-mobile` | the components compile against the contracts | that they behave |
| `make build-mobile` | the bundle builds | that it looks right |

There is no component-render test library in `mobile/`. Nothing above closes
that gap, and an acceptance verdict must not read as though it does.

## Manual end-to-end check

This is the criterion the human named, and it is manual by nature.

1. Turn the flag on for the test account.
2. On the phone, open a task with no project and no Tags.
3. Set a project and add two Tags. **Count every interaction it took.** Write
   the number down and compare it against the web client's count for the same
   triage, stated in `design.md`'s affordance map before implementation began.
   Mobile must not exceed it. *(SC-006)*
4. Refresh the web client. The same project and the same Tags appear. *(SC-002)*
5. Force the create call to fail while typing a new project name. The task's
   existing classification is unchanged and the typed name is still in the
   field — you can retry without retyping. *(User Story 2, scenario 4)*

## Manual offline check

1. Put the device in airplane mode.
2. Change the project. It shows as made, with no marker anywhere. *(FR-007)*
3. Note the footer's last-synced time. *(SC-004)*
4. Leave airplane mode. The change arrives and the footer advances. *(FR-006)*
5. Force-quit and reopen before step 4 to confirm the change survives. *(FR-009)*
6. **Cold-launch in airplane mode with a valid session.** You must land on the
   task screen, not sign-in; the classification rows must be editable, not the
   flag-OFF presentation; the pickers must open from cached lists; and the queue
   from step 2 must still be there. Three separate mechanisms — the session
   probe, the rollout flag, and the list cache — each break this on their own.
   *(FR-019, FR-020, SC-009)*
7. **Force-quit while a change is mid-send** (leave airplane mode, then kill the
   app within the send window). Reopen: the change is sent, not stranded. *(FR-021)*

## Manual expiry check

Needs a seeded backdated entry — there is no waiting 30 days.

1. Seed a queued change with `lastEditedAt` 31 days in the past and open its task.
2. The row shows the server's value again **and a notice names which field
   reverted and to what** — not merely a count. *(FR-018, SC-003)*
3. Confirm the entry is recoverable until dismissed, then dismiss it.
4. Seed one with `lastEditedAt` at 29 days 23 hours. It must survive.
5. Seed one with a timestamp in the **future** and confirm it is clamped rather
   than becoming immortal. *(FR-018)*
6. Coalesce a new edit into a 29-day-old entry and confirm it survives past
   day 31 — the bound runs from the last edit, not the first. *(FR-018)*

## Manual conflict check

1. Airplane mode on. Change the project on the phone.
2. From the web client, change the same task's project to something else.
3. Airplane mode off. **Read back all three values and record them** — what
   your phone last showed (with its age), what you set, what the server holds
   now. Then run the multi-change variant: change the project twice offline
   before reconnecting, and confirm the sheet still names the *original* value,
   not the intermediate one. *(FR-010)*
3b. The conflict sheet names what you changed and when, and
   offers both outcomes. Neither is chosen for you. *(FR-008, SC-005)*
4. Background the app instead of answering. Reopen: the sheet returns and
   nothing was decided. *(M-04 dismissed)*

## Manual identity check

1. Airplane mode on. Make two changes.
2. Switch server or sign out. The warning states the count and that continuing
   discards them. *(FR-011, SC-007)*
3. Cancel. The changes are still queued.
4. **Involuntary end, same account.** Invalidate the session server-side with
   entries queued, reopen the app, sign in as the *same* account. The entries
   are still there and drain with no prompt. *(FR-011, SC-008)*
5. **Involuntary end, different account.** Repeat, signing in as a *different*
   account. Nothing of the first account's is shown or sent — and its stored
   keys are gone from the device, not merely unread. Check storage directly;
   this is the half that key-scoping alone does not deliver. *(FR-011, SC-007)*
6. **Sign out with an empty queue.** No warning appears, correctly — then
   confirm the cached project and Tag lists were cleared anyway. Those are the
   names the person wrote, and they must not outlive the account. *(FR-011)*
