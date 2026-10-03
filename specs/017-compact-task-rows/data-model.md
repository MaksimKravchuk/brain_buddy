# Data Model: Compact Task Rows

No backend domain entity or persisted server schema changes.

## CollapsedTaskRow projection

Derived from existing `TaskResponse`, Tag resolution, and optional
`AgentRunSummaryResponse`.

| field | source | rule |
|---|---|---|
| `taskId`, `title`, `state` | `TaskResponse` | Title is one visual line; full title remains the accessible name |
| `tags` | `task.tag_ids` + Tag query | Render short Tag labels; progressively hide overflow; never render Project/List |
| `due`, `subtaskProgress` | `TaskResponse` | Compact optional indicators; yield before title/control wraps |
| `selected` | route `taskId` | Controls inline detail and `aria-expanded` |
| `agentRun` | latest summary map | Replaces pre-assignment control when present, independent of rollout flag |

## LastUsedAgentPreference

Browser-local, not a server record.

| field | type | validation |
|---|---|---|
| storage version | literal version in key | Allows a future incompatible preference shape to fail closed |
| API origin | normalized string in key | Prevents local/staging/production crossover |
| owner ID | authenticated ID in key | Prevents account crossover |
| connection ID | string in JSON value | Used only when it exactly matches a current `ready_for_handoff` connection |
| confirmed at | ISO timestamp in JSON value | Expires the record 30 days after last successful confirmed dispatch |

Transition rules:

1. No stored ID → first eligible connection.
2. Stored ID matches eligible connection → that connection.
3. Stored ID absent/ineligible/expired or storage malformed → erase it and use first eligible connection.
4. Confirmed hand-off succeeds → replace stored ID with `run.connection_id`.
5. Preview close/failure → preference unchanged.
6. A production-wired auth subscription observes logout, server-driven 401 session
   loss, account deletion, and A→B identity transition → erase the departing owner's
   key synchronously before another identity can use the Task surface.
7. Application startup, window focus, and the bounded in-process sweep interval scan
   every feature-key identity, not just the current owner, and remove malformed or
   `confirmedAt`-expired records. A record becomes logically ineligible at 30 days;
   if BrainBuddy is never run again, browser site-data deletion is the physical-removal
   control and that limitation is disclosed rather than hidden.

The preference is deliberately excluded from `GET /api/account/export`: the server
never receives or holds it. The browser lifecycle above is the compensating control
for a device record that server-side account purge cannot reach.

## AgentControl projection

Mutually exclusive states:

- **Absent**: no latest run and any of: terminal Task, relay OFF, connections
  unresolved, or no eligible connection.
- **Ready**: non-terminal Task, no latest run, relay ON, and at least one eligible
  connection. Two buttons: shortcut and chooser. Offline does not change this state:
  either button may open the readable existing review, while confirmation remains
  disabled and nothing is queued.
- **Assigned**: latest run exists. This state takes precedence over every Absent
  condition, including terminal Task and rollout OFF. One 184 × 28 button with agent
  name and compact visible state; no chooser or popup semantics.

The assigned projection never transitions the Task. `Agent reported complete` maps to
visible `Reported`; only the existing Task lifecycle transition changes Task state.

The trustworthy-stale summary source is only the existing in-memory React Query cache.
It may survive a failed refresh in the currently loaded application, but it does not
survive reload; this feature adds no persisted run-summary cache.

## InlineTaskDetail projection

Existing `TaskDetailPanel` data and autosave controller, placed beneath the route-
selected row. Its loading/error/edit/recovery/run state machines remain unchanged.
The layout mode changes presentation only; it creates no second Task record or editor
state.
