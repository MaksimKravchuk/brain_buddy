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

### Storage key

`bb.pendingClassification.<serverUrl>.<accountId>`

Identity is in the key rather than in a filter. An entry belonging to another
account or server is not hidden from a query — it is in a different key that is
never read while this identity is active. FR-011 and SC-007 become properties of
the structure instead of rules someone has to remember to apply.

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

## State transitions

```
        (person edits)
   ─────────────────────────▶ queued
                                │
              drain attempt ────┤
                                │
          accepted ─────────────┴──▶ removed, last-synced advances
          rejected on revision ─────▶ conflicted  (M-04)
          rejected otherwise ───────▶ error surfaced with correlation id, stays queued

   conflicted ── person keeps theirs ──▶ re-queued with the current revision
   conflicted ── person abandons ──────▶ removed
   conflicted ── app backgrounded ─────▶ stays conflicted; the sheet returns

   any state ── identity transition ───▶ warned (M-05), then discarded
```

`conflicted` is deliberately a state and not a modal side effect: backgrounding
the app must not resolve it, and with no per-change marker on the task screen
the returning sheet is the only thing that will remind the person it is there.
