# Design: Admin Users CRUD and two-tab portal

## Screen inventory

`/admin` remains direct-URL and renders no admin controls until `GET /admin/status` confirms the operator. Once confirmed, the page has a `tablist` with `Users` and `Feature flags`; Users is selected on every fresh mount.

| ID | State | Observable contract |
|---|---|---|
| U-01 | Access check | Existing checking/denied/unverified states remain unchanged; no tabpanel mounts before authorization. |
| U-02 | Users loading | Users tab selected; `Loading users…` status; no stale table. |
| U-03 | Users table | Compact rows ordered by email/id. Visible columns: Email, Display name, Deletion requested, Actions. |
| U-04 | Empty | Exact status `No accounts to manage yet.` when the confirmed response contains zero accounts. |
| U-05 | List unavailable/recovery | Retryable exact `Couldn't load users. Ref: <correlation-id>` when available, otherwise `Couldn't load users.`. An initial failure may have no table; a refetch failure preserves the last confirmed table. `Retry` performs a real refetch, and a successful retry clears the prior list error and renders the recovered response. |
| U-06 | Create | `Create user` opens a form for email, optional display name, initial password. Password uses `type=password`, is never prefilled and is cleared on success/cancel. |
| U-07 | Create saving/result | Submit disables once. Success closes/clears the form, refetches and focuses the created row; validation/conflict uses sanitized existing feedback. |
| U-08 | Edit | Row `Edit` opens email + display-name fields populated from server state. Save sends the full mutable projection. Configured operator email input is disabled/read-only in UI, but server refusal is authoritative. |
| U-09 | Revoke confirm | Existing feature-009 dialog/copy/focus behavior remains a row action. |
| U-10 | Delete confirm | Row `Delete` opens a distinct danger dialog: `Permanently delete {id} ({email}) and all owned data? This cannot be undone.` Cancel/Escape restores focus and sends nothing. |
| U-11 | Delete saving/result | Confirm disables once. Success removes only after server confirmation and announces `Account permanently deleted.` Failure keeps the row and refetches. Self/configured-operator delete is unavailable in UI and refused by server. |
| U-12 | Feature flags | Feature flags tab mounts the unchanged `AdminFeatureFlagsSection`, including its existing F-01…F-13 states. Switching tabs does not mutate flag state. |

## Interaction and accessibility

- Native tab semantics: two buttons with `role=tab`, `aria-selected`, `aria-controls`; panels use `role=tabpanel`. Left/Right arrows move and select; Tab enters the selected panel.
- Each action's accessible name includes the row identity (`Edit member@example.com`, `Revoke sessions for member@example.com`, `Delete member@example.com`).
- Create/edit/delete/revoke overlays follow existing `Overlay` focus trap, Escape and focus-restoration patterns. Destructive default focus is Cancel, never Delete.
- Mutation feedback is textual (`role=status` or `role=alert`) and never color-only. Raw server internals are not rendered.
- The list `Retry` control remains available after a confirmed response so the operator can initiate a real refetch; on failure the confirmed rows remain visible alongside the alert, and on success the alert is removed.
- At 390px, the table becomes stacked row cards or a horizontally safe grid: email and display name wrap, actions wrap vertically, controls retain at least 44px targets, and no page-level horizontal scrolling is introduced.
- Password value is never placed in success copy, DOM after form close, query cache, screenshot fixture or test attachment.

## Production browser evidence

Use one purpose-created unique `@example.com` member and a generated password that is never printed or captured. Capture only redacted/synthetic screens for: Users default/list, edit result, delete confirmation before submit, list after deletion, and Feature flags tab. Record the deployed exact SHA and browser/check timestamp separately. Verify target login failure after deletion without recording request/response bodies or credentials.
