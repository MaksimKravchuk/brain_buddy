# Tasks: Verified trunk delivery

**Input**: `specs/004-verified-trunk-delivery/spec.md`, `plan.md`
**Tests**: Required and written failing-first for every slice.
**Execution**: Hermes Kanban owns implementation/review; this file is planning input only.

## Phase 1: Server-owned feature flags (backend, TDD)

- [x] T001 Add failing tests in `backend/tests/test_feature_flags.py`: allow-list,
  defaults OFF, fail-closed parsing (unknown/duplicate/malformed/invalid state,
  non-email cohort), OFF/INTERNAL/ON evaluation, `/auth/me`–`/auth/login`–`/auth/signup`
  exposure, 401 without session, no stage/cohort leakage.
- [x] T002 Implement `FeatureFlagState`, `KNOWN_FEATURE_FLAGS`, frozen
  `FeatureFlagSettings` with validators and `effective_flags`, env parsing
  (`BRAIN_BUDDY_FEATURE_FLAGS`, `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`) in
  `backend/app/core/config.py`; wire `AppConfig.feature_flags`.
- [x] T003 Extend `MeResponse.feature_flags` and populate via `_me_response` in
  `backend/app/api/auth.py`; add Allure taxonomy mapping; document env vars in
  `.env.example`.

## Phase 2: Authenticated production smoke (TDD)

- [x] T004 Add deterministic stub-server contract tests in
  `scripts/test_production_smoke.py` (happy path, redaction, missing/wrong credentials,
  missing flag payload, unverified cleanup).
- [x] T005 Implement `scripts/production_smoke.sh` (env credentials, temp cookie jar +
  trap, `/auth/me` flag verification, unique temp tree create/delete/verify, logout,
  fail closed, no secret output).

## Phase 3: PR-less serial landing (TDD)

- [x] T006 Add git-fixture contract tests in `scripts/test_submit_to_trunk.py` (clean
  tree, current base, single non-merge commit, unique candidate ref, idempotent
  resubmit, no force/main push).
- [x] T007 Implement `scripts/submit_to_trunk.sh`.
- [x] T008 Add `scripts/validate_trunk_delivery.py` + mutation-based
  `scripts/test_validate_trunk_delivery.py` covering landing and deploy guards.
- [x] T009 Extend `.github/workflows/ci.yml`: `trunk-candidate/**` push trigger running
  the identical required job set; wire new validators/tests into workflow-lint and
  `make validate-ci`. (The originally in-CI `promote` job was removed again in T021:
  candidate-controlled CI must never promote.)

## Phase 4: Production deploy and rollback

- [x] T010 Extend `.github/workflows/deploy-fly-production.yml`: `production`
  environment, smoke-secret preflight, pre-deploy rollback image capture with
  fail-closed validation, authenticated smoke, verified frontend-first rollback that
  keeps the workflow failed.

## Phase 5: Governance

- [x] T011 Add `docs/decisions/0008-verified-trunk-serial-landing.md` (supersedes the
  PR-mandatory parts of ADR-0003; defines Ship/Show/Ask); annotate ADR-0003.
- [x] T012 Update `docs/autonomous-delivery-runbook.md`, `AGENTS.md`, and README for the
  verified-trunk path and required GitHub `production` environment secrets
  (`BRAIN_BUDDY_ADMIN_EMAIL`, `BRAIN_BUDDY_ADMIN_PASSWORD`,
  `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`; no PAT — promotion uses the job-scoped
  `GITHUB_TOKEN` and deploys consume the completed candidate CI run).

## Phase 6: Release-review hardening (TDD)

- [x] T013 Make the deploy's exact-main verification unconditional (candidate AND main
  runs) so stale main CI cannot redeploy an older SHA; forbid re-gating it via
  `scripts/validate_trunk_delivery.py` and its mutation tests.
- [x] T014 Make candidate-ref deletion non-blocking (`continue-on-error`) cleanup after
  the `main` mutation; document leftover-ref cleanup in the runbook.
- [x] T015 Add the deterministic Ship/Show/Ask path classifier
  (`scripts/classify_path_risk.py` + `scripts/test_classify_path_risk.py`) and wire it
  into `submit_to_trunk.sh` (non-skippable preflight) and the promote job (trusted
  `origin/main` copy, before pushing `main`).
- [x] T016 Skip rollback-capture releases whose present status is not a known
  successful terminal state (complete/succeeded/success) in
  `scripts/capture_fly_release_image.py`, with tests.
- [x] T017 Add `scripts/check_smoke_identity_cohort.py` +
  `scripts/test_check_smoke_identity_cohort.py`: fail the deploy before any remote
  mutation unless the normalized admin email is in the normalized internal cohort.
- [x] T018 Make `FeatureFlagSettings.states` genuinely read-only
  (`MappingProxyType`) and prove item mutation raises in
  `backend/tests/test_feature_flags.py`.
- [x] T019 Correct concurrency wording everywhere: GitHub concurrency is safety
  serialization with at most one pending run (extras may be cancelled), and
  cancellation fails closed.
- [x] T020 Add the production-smoke EXIT-trap best-effort tree cleanup with a
  stub-server test proving an interrupted smoke still sends the cleanup DELETE
  without masking the original failure; reconcile smoke secret naming
  (`BRAIN_BUDDY_ADMIN_*` GitHub secrets only; `BRAIN_BUDDY_SMOKE_*` stay
  script-internal).

## Phase 7: Second-review hardening (TDD)

- [x] T021 Remove the `promote` job and every write permission from
  candidate-controlled `.github/workflows/ci.yml`; move landing into a secret-free
  `land` job of the default-branch `deploy-fly-production.yml` (job-scoped
  `contents: write` — later replaced by the T025 deploy-key identity —
  single-fresh-parent check, trusted `origin/main` classifier,
  plain fast-forward, best-effort candidate-ref deletion, universal landing proof)
  with the production `deploy` job behind `needs: land` under `contents: read`;
  rewrite `validate_trunk_delivery.py` + mutation tests for the new contract and
  document the ASK bootstrap path.
- [x] T022 Feed the path classifier NUL-separated `git diff --no-renames
  --name-only -z` output at both gates via an explicit `--null` stdin-buffer mode
  (surrogateescape decoding); newline mode fails closed as ASK on quoted or
  backslash-escaped listings. Tests: non-ASCII workflow path, quoted/backslash
  input, rename from an ASK path showing delete+add classification.
- [x] T023 Extend `scripts/check_smoke_identity_cohort.py` to mirror backend
  startup validation (email-shaped admin and cohort entries, 12–128 character
  password policy, case-insensitive membership; names only, never values), with
  tests.
- [x] T024 Mark the smoke `TREE_CLEANED` only after the 404 read-back so the EXIT
  trap retries an accepted-but-ineffective DELETE, with a stub-server test; fix the
  spec's claim that CI reruns on `main` after landing; Black-format
  `backend/tests/test_feature_flags.py`; document the Full CI required-status
  recommendation and bootstrap evidence in the runbook.

## Phase 8: Final-review hardening (TDD)

- [x] T025 Replace the land job's `GITHUB_TOKEN` write with a dedicated landing
  identity: job permissions `contents: read`, `environment: landing`, and an
  `actions/checkout` SSH deploy-key push (`ssh-key: TRUNK_LANDING_SSH_KEY`,
  `persist-credentials: true`) used only to fast-forward the exact tested SHA and
  delete the candidate ref. Mutation-test the new contract in
  `validate_trunk_delivery.py`: no `contents: write` anywhere, the key scoped to the
  land job only, and candidate CI forbidden from referencing the key or the landing
  environment. Document as MUST (not recommendation): `landing` environment branch
  policy `main`, `main` ruleset `restrict_updates` with the deploy key as sole
  bypass actor, required `Full CI` + `Docker Images` checks, the corrected
  deploy-key-push-retriggers-main-CI semantics, the precise bootstrap order, and
  that emergency direct admin landings need a recorded temporary ruleset
  intervention.
- [x] T026 Classify `backend/app/api/{dependencies,middleware,routes,tasks}.py`
  (session auth and per-owner privacy enforcement) as explicit exact-path ASK
  surfaces in `classify_path_risk.py`, with classifier tests (siblings stay SHIP)
  and ADR/runbook/spec/AGENTS documentation, preserving the NUL-separated
  `--no-renames` rename/quoting safeguards.
- [x] T027 Codify the live production controls as MUSTs and bootstrap verification
  items (ADR-0008, runbook, spec/plan, AGENTS, README): `FLY_API_TOKEN` exists only
  as a `production` environment secret (no repository-level copy), and the
  `production` environment holds the token/admin/cohort secrets behind a custom
  `main`-only deployment branch policy (mirroring `landing`). Add validator
  defense-in-depth with mutation tests: candidate-controlled CI may request neither
  `environment: landing` nor `environment: production`. Resolve the
  reviewed-PR/`restrict_updates` contradiction without weakening the ruleset:
  retain `restrict_updates` with the deploy key as sole bypass; document that a PR
  carries ASK review evidence but cannot merge while the deploy key is the sole
  bypass, so ASK landings require explicit approval + green exact-SHA CI + an
  audited temporary ruleset intervention (or a separately accountable human
  reviewer in the future); routine SHIP/SHOW stays deploy-key auto landing.
