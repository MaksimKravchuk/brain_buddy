# Verified trunk delivery — specification quality checklist

**Purpose**: Verify the slice is implementation-ready and bounded.
**Created**: 2026-07-22
**Feature**: `specs/004-verified-trunk-delivery/spec.md`

## Requirement completeness

- [x] Delivery model is explicit: no persistent staging; candidate CI → serialized
      fast-forward + landing proof (default-branch release workflow) → exact-SHA
      deploy → authenticated smoke → flag rollout. No CI rerun happens on `main`
      after a landing; the consumed candidate CI run is the evidence.
- [x] Fail-closed behavior is specified for every mutation path (invalid flag config,
      write-permission-free candidate CI, stale/merge/multi-commit candidates,
      missing or policy-violating smoke secrets, uncaptured rollback images, failed smoke).
- [x] Ship/Show/Ask classes are enumerated with the ASK triggers.
- [x] Non-goals stated: no staging, no new Kanban board, no self-approval, no weakening
      of CI/mutation/preview policies, preview workflow deprecated but not deleted.

## Safety and privacy

- [x] Flags are exposure control only, never authorization.
- [x] Only effective booleans are exposed to the authenticated user; stages, cohort
      membership, and configuration stay server-side.
- [x] Smoke script never prints credentials, cookies, or response bodies; temp cookie
      jar with trap cleanup; unique temporary tree verified deleted.
- [x] Landing never force-pushes and cannot create a PR; candidate-controlled CI
      holds no write permission; main CI is never cancelled.
- [x] Production credentials are environment-scoped MUSTs and bootstrap verification
      items: `FLY_API_TOKEN` exists only in the `production` environment (no
      repository-level copy), the `landing` and `production` environments each carry
      a custom `main`-only deployment branch policy, and candidate-controlled CI may
      request neither environment (validator-enforced defense-in-depth).
- [x] The ASK/`restrict_updates` interaction is stated honestly: a PR carries review
      evidence but cannot merge while the landing deploy key is the sole bypass
      actor; an ASK landing requires explicit recorded approval, green exact-SHA CI,
      and a short audited temporary ruleset intervention — the ruleset is never
      weakened, and routine SHIP/SHOW stays deploy-key auto landing.

## Testability

- [x] Every guard has a deterministic offline test (backend pytest, git-fixture script
      tests, HTTP-stub smoke tests, workflow mutation tests).
- [x] Existing gates (coverage 95% line+branch, Allure taxonomy, artifact contract,
      mutation policy, preview policy) still pass unchanged.
