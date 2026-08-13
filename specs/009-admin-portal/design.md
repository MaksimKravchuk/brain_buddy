# Design: Minimum Admin Portal

## Screen and state inventory

**One screen: `/admin`.** No other route is added or changed.

| # | State | Trigger | Copy contract |
| --- | --- | --- | --- |
| 1 | Lookup form (default) | operator opens `/admin` | one text input (account ID or email) + submit; no other affordance |
| 2 | Found | exact match returned | renders exactly account ID, canonical email, optional display name, deletion-requested state (009-FR-004), plus a "Revoke sessions" action |
| 3 | Not found | no exact match | generic "No account found." — same copy for either lookup kind, no hint about which field was checked |
| 4 | Confirm revoke | operator clicks "Revoke sessions" | a second, explicit confirmation step naming the account ID before the mutation fires (009-FR-006) |
| 5 | Revoked | mutation succeeds | "Revoked N session(s)." — N may be 0 (009-FR-007) and that is still success styling, not an error |
| 6 | Access denied | caller is authenticated but not on the allow-list | generic denied state, no form, no account data (009-FR-002) |
| 7 | Signed out | no valid session | the existing app-wide sign-in redirect; `/admin` adds no bespoke unauthenticated state |

## Interaction notes

- The lookup input accepts either an account ID or an email; the client does
  not pre-classify it; the server tells the two apart the same way FR-003
  requires (exactly one of `account_id` or `email` is sent, chosen by
  whether the input parses as an email).
- Revoke is only reachable from state 2 (Found) — there is no way to revoke
  without a prior successful lookup in the same session.
- No result list, no pagination control, no bulk selection: only ever one
  account on screen, matching the non-goals in [spec.md](spec.md).

Accessibility is inherited from the existing form/button/confirmation
components already used on `AccountSettingsPage` — this feature does not
introduce new interaction patterns.
