# Phase 1 data model

Server-side entities are unchanged. The only new structure is device-local.

## Unchanged (server)

| entity | relationship | note |
|---|---|---|
| Task | 0..1 Project, 0..n Tag | carries `revision`, which the server uses to detect a change made elsewhere |
| Project | referenced by 0..n Task | identity assigned by the server |
| Tag | referenced by 0..n Task | identity assigned by the server. ADR-0006: the term is Tag |

## New: PendingClassificationChange (device-local)

| field | type | why it exists |
|---|---|---|
| `taskId` | string | what the change applies to |
| `projectId` | `string \| null \| undefined` | `undefined` means untouched; `null` means deliberately cleared. The distinction is load-bearing — clearing a project is a supported outcome (FR-001) and must not be confused with "no opinion" |
| `tagIds` | `string[] \| undefined` | the whole intended set, not a delta. Coalescing a delta stream is where a queue loses data |
| `observedRevision` | number | the revision the person was looking at. Sent as `expected_revision`; a mismatch is the conflict of FR-008 |
| `queuedAt` | ISO string | shown in the conflict prompt, which must name what changed and when because nothing else does |
| `accountId` | string | FR-011. Part of the storage key, not merely a field |
| `serverUrl` | string | FR-011. Also part of the key |
| `idempotencyKey` | string | FR-017. Generated once when the entry is created and never regenerated, including on retry after a timeout and on a re-queue after a conflict is resolved in the person's favour |
| `sendState` | `'queued' \| 'sending' \| 'conflicted'` | FR-017. `sending` is what makes a second drain trigger a no-op rather than a duplicate send |

### Storage key

`bb.pendingClassification.<serverUrl>.<accountId>`

Identity is in the key rather than in a filter. An entry belonging to another
account or server is not hidden from a query — it is in a different key that is
never read while this identity is active. FR-011 and SC-007 become properties of
the structure instead of rules someone has to remember to apply.

**Both halves of the key must be readable with no connection.** `serverUrl`
already is — `mobile/src/config/serverUrl.ts` persists it. `accountId` is not:
its only source today is `/auth/me`. The account id is therefore persisted on
every successful `/auth/me` and read from storage, never from the live session.
Without that, a cold start offline cannot name its own key and FR-009 fails on
the exact path the feature exists for.

### Invariants

1. **At most one entry per `taskId` per key.** FR-010: several changes to one
   task coalesce to the net effect. Enforced by the reducer, table-tested.
2. **`observedRevision` is the revision seen when the *first* uncoalesced change
   was made**, not refreshed on coalescing. Refreshing it would silently swallow
   a concurrent edit — exactly what the conflict prompt exists to prevent.
3. **A tag added and then removed before the drain leaves no trace**, because
   `tagIds` is the intended set. If the net set equals the server's, the entry
   is dropped rather than sent as a no-op.
4. **Entries are never migrated across identities.** On any identity
   transition the key's contents are discarded after the FR-011 warning; they
   are not re-keyed.
5. **At most one drain in flight per entry.** FR-017. There are two drain
   triggers — app foreground and a successful request — so without this the
   ordinary case is two concurrent sends of one entry. An entry in `sending` is
   skipped by any further drain.
6. **`idempotencyKey` is stable for the life of the entry.** A 30 s timeout
   makes "the server applied it and the response was lost" a normal outcome, not
   an edge case; the backend already returns the stored result for a repeated
   key, so a retry that reuses the key is safe and a retry that mints a new one
   double-applies. Coalescing a new change into an existing entry keeps the
   existing key: the entry is still one intended outcome for one task.

## State transitions

```
        (person edits)
   ─────────────────────────▶ queued
                                │
              drain attempt ────┴──▶ sending   (a second trigger sees this and skips)
                                       │
          accepted ────────────────────┼──▶ removed, last-synced advances
          rejected on revision ────────┼──▶ conflicted  (M-04)
          rejected otherwise ──────────┼──▶ queued, error surfaced with correlation id
          timeout / connection lost ───┴──▶ queued, same idempotencyKey on the next try

   conflicted ── person keeps theirs ──▶ queued, current revision, key unchanged
   conflicted ── person abandons ──────▶ removed
   conflicted ── app backgrounded ─────▶ stays conflicted; the sheet returns

   deliberate identity transition ─────▶ warned (M-05), then discarded
   involuntary session loss ───────────▶ OPEN — see spec.md, open decision 2
```

The last line is not an omission. Session loss is reachable without anyone
choosing it: `SessionProvider` flips to signed-out on any 401 *and* on a plain
network failure, and the session token expires on its own after 30 days. Under
FR-011 as written that path discards unsent work with no warning shown, because
no one performed an action to warn about. What should happen is a product
decision and it is recorded as one rather than settled here.

`conflicted` is deliberately a state and not a modal side effect: backgrounding
the app must not resolve it, and with no per-change marker on the task screen
the returning sheet is the only thing that will remind the person it is there.
