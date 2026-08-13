# Requirements Checklist

Quality gate for [spec.md](spec.md) itself: is it written well enough to build
from and to accept against? Re-checked after review campaign
`009-admin-portal-campaign-1`. Three boxes that were ticked before the
campaign were **not true**; each has since been reopened, fixed at the
planning level, and re-ticked with the original failure recorded in place — a
checklist that flatters the package is worse than no checklist. Every box here
grades planning quality only.

**Branch state, corrected after campaign 2.** The pre-campaign-2 version of
this preamble said the feature was "not implemented" and that the lane B–H
tests "do not exist yet". Both were false: the admin backend, the `/admin`
page, the hooks, the client methods and the route were already committed
(`bc28485`, `a2eaf25`) along with substantial tests. As of the campaign-2
repair pass, lanes A–I in [tasks.md](tasks.md) are implemented and their
checkpoints run green — backend `pytest` for the admin, auth, config, export
and CI-contract modules, and the focused frontend Vitest files. Lane J is
open: J1's full `make verify-all` chain has not been run on this tree, and J2
is the human ASK landing.

## Clarity

- [x] Every requirement is testable by a mechanical check or a real command.
- [x] No requirement names a solution the spec has not justified (the
      operator allow-list, exact-match lookup, and reuse of the session
      bulk-delete are all named directly by the founder's frozen slice).
- [x] Out-of-scope items are enumerated rather than implied — a later reader
      can tell "declined" from "forgotten". PD-1 (no menu discoverability) and
      the rejected dedicated operator identity (PD-2/PD-5) are now among them.
- [x] The one screen this feature adds is stated explicitly, with stable
      state ids `D-01`…`D-10` an acceptance test can cite ([design.md](design.md)).
- [x] Every observable choice the code made outside the spec is now decided
      in the spec: unknown-account revoke (PD-3), the capability check
      (009-FR-011), and who classifies the lookup input (design.md).

## Coverage

- [x] Every requirement has a task in [tasks.md](tasks.md), including the
      three added after the campaign (009-FR-011, 012, 013).
- [x] Every success criterion has an executable observation **named**:
      [tasks.md](tasks.md) gives each of 009-SC-001…007 a concrete test file
      and a runnable checkpoint command (e.g. 009-SC-004 → the sentinel and
      canary assertions in `backend/tests/test_admin_api.py` under
      `pytest tests/test_admin_service.py tests/test_admin_api.py -k lookup`
      and `-k revoke`; 009-SC-007 → the flag-off case in `test_admin_api.py`).
      Every one of the seven now has a test that names it and asserts
      something — `python3 scripts/check_requirement_coverage.py
      specs/009-admin-portal` reports 20/20 traced, and 009-SC-005's
      observation is an executable export assertion (tasks.md I8), not the
      documentation edit an earlier version of this box pointed at. It
      replaces a pre-campaign tick that pointed at a
      log-content assertion which captured lookup and revoke together, planted
      no display-name or raw-body sentinel, and so could pass with lookup
      logging removed.
- [x] The failure mode that motivated the feature — no way to find or
      recover an account without direct data-store access — is covered by
      an executable check (lookup + revoke tests), not only by review.
- [x] Every ticked task corresponds to a real change in the tree. Lanes A–I
      are ticked because the code, tests and documents exist on disk and their
      named checkpoints were run green; lane J is unticked because
      `make verify-all` has not been run here and the ASK landing has not
      happened. This box grades the *honesty of the ticks*. The pre-campaign
      failure it replaces: T008 was ticked for an `.env.example` edit that was
      never made — that variable is documented as of this pass.

## Consistency

- [x] The four returned fields in 009-FR-004 match the fields named in the
      founder's frozen slice, verbatim: account ID, canonical email,
      optional display name, deletion-requested state.
- [x] The revoke mechanism (009-FR-007) names the exact existing capability
      it reuses (`SessionRepository.delete_all_for_user`), not a new one.
- [x] The changed-surface tables in [plan.md](plan.md) name the symbols that
      actually exist (`getAdminStatus`, `lookupAdminAccount`,
      `revokeAdminAccountSessions`, `adminHooks.ts`, `GET /admin/status`, the
      deploy workflow) and mark what is still outstanding.
- [x] No requirement contradicts an existing repository gate — **resolved by
      decision, not by the original claim.** This feature *does* contradict
      ADR-0001's owner-scoping assumption; that conflict is now narrowly
      authorized by accepted
      [ADR-0017](../../../docs/decisions/0017-operator-account-administration-narrow-owner-scoping-exception.md),
      which keeps member content owner-scoped and admits only operator
      account-identity reads plus session revoke. `/api/account` and
      `/api/auth/me` responses remain pinned unchanged (009-FR-010). No spec
      requirement now stands against an unamended gate. `/api/auth/me`,
      `/login` and `/signup` really are pinned unchanged: the `admin_portal`
      flag is declared in `PRIVATE_FEATURE_FLAGS`, deliberately outside the
      `KNOWN_FEATURE_FLAGS` tuple that `effective_flags` projects into every
      member's payload, and a test asserts the exact key set before and after.
      The one bounded member-facing exception is 009-FR-012's signup and
      email-change rejection, which 009-FR-010 now states explicitly.

## Risk

- [x] Authorization denial cannot leak target-account existence: 009-FR-002
      requires the allow-list check before any lookup or mutation runs, and
      009-SC-002 is tested against both an existing and a non-existing
      target — now including the *effect*, not only the response.
- [x] The allow-list has no self-service path: it is server-owned
      configuration (009-FR-001), and 009-FR-012 closes the indirect path of
      moving an account onto a listed address.
- [x] The feature's risk class is recorded: **ASK / high** under ADR-0008,
      with the landing constraints and the rollback story (including the
      irreversibility of session revoke) written down in [plan.md](plan.md).
- [x] The privacy disposition of the records this feature creates is decided
      rather than inherited by omission (PD-4, `docs/data-retention.md`).
- [x] Manual acceptance uses a purpose-seeded non-real account and requires
      redaction, so ASK-class PR evidence cannot carry a member's email or
      account id (constitution Principle I).
- [x] Every explicit non-goal in [spec.md](spec.md) doubles as a rejection
      criterion for scope creep introduced by later review.
