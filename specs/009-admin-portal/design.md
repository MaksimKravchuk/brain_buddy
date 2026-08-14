# Design: Minimum Admin Portal

## Screen and state inventory

**One screen: `/admin`, reached by typing the URL.** No other route is added
or changed, and — per PD-1 in [spec.md](spec.md) — no navigation entry, menu
item or other affordance points at it from anywhere in the app. State IDs are
stable and citable by acceptance tests (`D-01` … `D-10`), matching the
convention feature 006 uses for interactive screens.

| ID | State | Trigger | Copy contract |
| --- | --- | --- | --- |
| D-01 | Checking access | the route-scoped operator capability check is in flight (009-FR-011) | "Checking access…" — no form, no denial copy yet; this is the first thing an operator sees on every visit |
| D-02 | Lookup form (default) | capability check confirms the caller is an operator | one text input (account ID or email) + submit; no other affordance |
| D-03 | Found | exact match returned | renders exactly account ID, canonical email, optional display name, deletion-requested state (009-FR-004), plus a "Revoke sessions" action |
| D-04 | Not found | no exact match | generic "No account found." — same copy for either lookup kind, no hint about which field was checked |
| D-05 | Confirm revoke | operator clicks "Revoke sessions" | a second, explicit confirmation step that names the account and the consequence: "Every current session for account **{id}** ({email}) will be signed out immediately." Cancel and confirm are both present; Escape cancels (009-FR-006) |
| D-06 | Revoked | mutation succeeds | "Revoked N session(s)." — N may be 0 for an existing account (009-FR-007) and that is still success styling, not an error |
| D-07 | Request failed | any non-404 lookup or revoke failure (5xx, network, unexpected) | the generic `Feedback` error banner, retryable by resubmitting the form or reopening the dialog; never renders raw server internals. A revoke that 404s (the target was purged between lookup and confirm) uses the D-04 copy, not a raw error |
| D-08 | Access denied | the capability check **succeeded** and reported the caller is not an operator, or a data route answered 403 | generic denied state, no form, no account data, no retry affordance (009-FR-002) |
| D-09 | Access could not be verified | the capability check itself failed (network, 5xx, timeout) — *not* a confirmed 403 | "Couldn't verify access. Try again." with a retry action. A transient network failure must not tell a legitimate operator they are unauthorized |
| D-10 | Signed out | no valid session | the existing app-wide sign-in redirect, applied to the real `/admin` route; `/admin` adds no bespoke unauthenticated state |

With the `admin_portal` rollout flag OFF (009-FR-013) authorization is still
evaluated first: an unauthenticated visitor gets D-10, a non-operator gets the
same 403 as always, and an allow-listed operator's capability check answers
404. The client maps **both** confirmed answers — 403 and 404 — to **D-08**,
and everything else (network, timeout, 5xx) to **D-09**. No separate "feature
disabled" copy is added: an operator who cannot use the portal sees the same
generic denial either way, which together with the flag-invariant non-operator
response is what keeps the rollout state from being disclosed. The 404 that
means "flag off" arrives only on `GET /admin/status`; the 404 that means "no
such account" arrives only on lookup/revoke and maps to D-04, so the two are
never confused.

## Interaction notes

- **Input classification is a client contract, stated once here.** The single
  text input accepts either an account ID or an email. The **client** decides
  which request field to send: if the trimmed value matches the client's email
  pattern it is sent as `email`, otherwise as `account_id`. The server does
  not re-classify — it accepts exactly one of the two fields and matches each
  exactly (009-FR-003). Consequences that must be pinned by test:
  - a canonical email that the server-side normalization accepts but the
    client pattern rejects (for example `admin@localhost`) would be sent as an
    account ID and report "No account found." for an account that exists. The
    client pattern must therefore be at least as permissive as what
    `seed_admin` and `AdminSettings` accept;
  - malformed email-like input (`a@`, `@b`) is sent as an account ID and
    yields D-04, which is correct — there is no separate validation error;
  - the submitted value is sent **as typed**, never trimmed. Trimming would
    turn a whitespace variant of a real address into the canonical one and
    manufacture a match the server is required to refuse (009-FR-003);
  - an account ID is never sent as an email, so a lookup can never
    accidentally match a different account by the other key.
- Revoke is only reachable from D-03 (Found) — there is no way to revoke
  without a prior successful lookup in the same session.
- Revoking the operator's **own** account signs the operator out everywhere,
  including the portal tab, which is the correct reading of scenario 4. The
  confirm dialog must say so when the target ID is the operator's own account,
  so the operator is not surprised by losing the session mid-task.
- No result list, no pagination control, no bulk selection: only ever one
  account on screen, matching the non-goals in [spec.md](spec.md).

## Accessibility

Accessibility is inherited from the existing form/button/confirmation
components already used on `AccountSettingsPage` — this feature introduces no
new interaction pattern. Two behaviors are named explicitly because
inheritance does not cover them:

- **Focus on open/close (D-05).** Opening the confirm dialog moves focus into
  the dialog panel (existing `Overlay` behavior). Closing it — Cancel, Escape,
  or after a successful revoke — returns focus to the "Revoke sessions"
  button that opened it. Nothing in `components/ui/` records or restores the
  previously focused element today, so this is new work, not inheritance. It
  is implemented **locally in `AdminPage`**, holding a ref to the trigger:
  `Overlay` is shared by the capture and task screens, and changing its
  unmount behavior app-wide is a regression surface this bounded slice has no
  evidence for.
- **Non-color feedback.** D-04, D-06, D-07, D-08 and D-09 all carry text plus
  the existing `role="alert"`/`role="status"` semantics; none is distinguished
  by color alone.
