# ADR-0030: Narrow the ASK class while there are no real users

Date: 2026-10-08
Status: Accepted by the product owner, 2026-10-08
Amends: ADR-0008 (which paths are ASK), ADR-0023 (which work leaves the fast lane)
Preserves: ADR-0008 landing mechanics, exact-SHA CI, the verified deploy smoke and rollback

## Context

ADR-0008's path classifier made a wide set of surfaces ASK:
- CI workflows, every delivery script and the `Makefile`;
- Docker, Compose and Fly configuration;
- every path carrying an auth, session, user, invite, login or password token;
- the four API modules that wire session auth.

ASK is not only a landing rule. Through ADR-0023 and `spec_kit_planning_review.py`
it also decides the planning path:
- any ASK outcome leaves the fast lane;
- a spec that merely names an ASK path derives `high` risk;
- `high` risk needs a run-bound human sign-off record before implementation.

Most product work touches routes, auth or CI, so most of it took the full path
and stopped for the owner.

BrainBuddy runs on Fly as a test environment with no real users and no valuable
data. The owner asked for speed: "PrintBuddy пока не имеет реальных пользователей…
можно быть более агрессивным в деплоях" (2026-10-08). In that state a bug in auth
or CI costs a fix and a redeploy, not harm to a person.

## Decision

While there are no real users, ASK covers only what cannot be undone after a mistake,
plus the machinery that enforces this boundary:

- persisted data and migrations: `backend/data/`, and `migration`/`migrations`/`alembic` tokens;
- secrets: `.env`/`.env.*`, and `secret`/`secrets`/`credential`/`credentials` tokens;
- every GitHub workflow and action under `.github/`: any of them can read repository
  secrets, and which ones a new or edited workflow reaches cannot be decided from its path;
- GDPR account deletion and export: `backend/app/services/account_service.py`;
- the Allure quality-gate rules: `allurerc.mjs`;
- the landing gate itself:
  - `scripts/classify_path_risk.py`;
  - `scripts/check_gate_integrity.py`;
  - `.specify/gate-integrity.json`;
  - `.github/workflows/deploy-fly-production.yml`, which is already covered by `.github/`.

The landing-gate paths stay ASK because a candidate that could change them could
widen SHIP for itself and every change after it.

The following are SHIP:
- delivery scripts and the `Makefile`;
- Docker, Compose and Fly configuration;
- auth, session, user and permission code, including the four API modules ADR-0008
  listed by exact path.

These still pass exact-SHA CI, the review the change's risk selects, and the
authenticated production smoke with verified rollback.

Because derived risk and ADR-0023 eligibility both read the same classifier, the
change carries through on its own. The human sign-off record is now required only
for work whose artifacts name a surface on the list above. The risk machinery itself
is unchanged:
- default risk stays `medium`;
- derivation can still only raise risk;
- the sign-off record and its digest binding still apply wherever `high` is reached.

## Re-tightening trigger

Before the first real (non-owner, non-test) user is invited, or before any valuable
data is stored, restore the ADR-0008 ASK scope:
- auth/session/user code and the four API privacy modules;
- Docker/Fly configuration and delivery scripts.

This ADR then becomes superseded. Treat a missed trigger as a defect, not a judgement call.

## Consequences

- Most feature work is eligible for the ADR-0023 fast lane, and `submit_to_trunk.sh`
  accepts it.
- An auth or delivery-script regression can reach the test environment faster. CI, review and the
  deploy smoke are the only guard on those surfaces until the trigger fires.
- Data loss, leaked secrets, workflow changes and changes to the gate itself still need
  the owner.
