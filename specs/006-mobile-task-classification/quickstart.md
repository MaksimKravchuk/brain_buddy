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
3. Set a project and add two Tags.
4. Refresh the web client. The same project and the same Tags appear. *(SC-002)*

## Manual offline check

1. Put the device in airplane mode.
2. Change the project. It shows as made, with no marker anywhere. *(FR-007)*
3. Note the footer's last-synced time. *(SC-004)*
4. Leave airplane mode. The change arrives and the footer advances. *(FR-006)*
5. Force-quit and reopen before step 4 to confirm the change survives. *(FR-009)*

## Manual conflict check

1. Airplane mode on. Change the project on the phone.
2. From the web client, change the same task's project to something else.
3. Airplane mode off. The conflict sheet names what you changed and when, and
   offers both outcomes. Neither is chosen for you. *(FR-008, SC-005)*
4. Background the app instead of answering. Reopen: the sheet returns and
   nothing was decided. *(M-04 dismissed)*

## Manual identity check

1. Airplane mode on. Make two changes.
2. Switch server or sign out. The warning states the count and that continuing
   discards them. *(FR-011, SC-007)*
3. Cancel. The changes are still queued.
