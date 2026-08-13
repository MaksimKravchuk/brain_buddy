# Requirements Checklist

Quality gate for [spec.md](spec.md) itself: is it written well enough to build
from and to accept against? Ticked at authoring time; re-checked at acceptance.

## Clarity

- [x] Every requirement is testable by a mechanical check or a real command.
- [x] No requirement names a solution the spec has not justified (the
      operator allow-list, exact-match lookup, and reuse of the session
      bulk-delete are all named directly by the founder's frozen slice).
- [x] Out-of-scope items are enumerated rather than implied — a later reader
      can tell "declined" from "forgotten".
- [x] The one screen this feature adds is stated explicitly, not left to
      inference ([design.md](design.md)).

## Coverage

- [x] Every requirement has a task in [tasks.md](tasks.md).
- [x] Every success criterion has a way to observe it: 009-SC-001..003 by
      API/service tests, 009-SC-004 by a log-content assertion.
- [x] The failure mode that motivated the feature — no way to find or
      recover an account without direct data-store access — is covered by
      an executable check (lookup + revoke tests), not only by review.

## Consistency

- [x] The four returned fields in 009-FR-004 match the fields named in the
      founder's frozen slice, verbatim: account ID, canonical email,
      optional display name, deletion-requested state.
- [x] The revoke mechanism (009-FR-007) names the exact existing capability
      it reuses (`SessionRepository.delete_all_for_user`), not a new one.
- [x] No requirement contradicts an existing repository gate; none is
      weakened. `/api/account` and `/api/auth/me` responses are pinned
      unchanged (009-FR-010).

## Risk

- [x] Authorization denial cannot leak target-account existence: 009-FR-002
      requires the allow-list check before any lookup or mutation runs, and
      009-SC-002 is tested against both an existing and a non-existing
      target.
- [x] The allow-list has no self-service path: it is server-owned
      configuration, not a database table or request field (009-FR-001).
- [x] Every explicit non-goal in [spec.md](spec.md) doubles as a rejection
      criterion for scope creep introduced by later review.
