# External-agent relay production release

This runbook covers the minimum BYOA relay on the web service and Expo iOS app. Brain Buddy relays task/context and reports connector events; it does not guarantee external execution or validate the agent's result.

## Preconditions

- Release commit is reviewed and contains no credentials or live connector endpoints.
- The required `Full CI` **and** `Docker Images` checks are green for the exact commit SHA being landed — not for a rebased, amended, or merged variant of it.
- GitHub `landing` and `production` environments retain their existing main-only policies and secrets.
- Production has `BRAIN_BUDDY_AGENT_RELAY_KEYS` configured with an active encryption key; never print or commit its value.
- `BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS` is absent/false in production.
- Rollout begins with `external_agent_relay` enabled only for the internal cohort. `.github/workflows/deploy-fly-production.yml` stages `external_agent_relay=internal` authoritatively on every production deploy, so do not set the flag out of band — the next release reverts it.
- EAS is authenticated, the Expo project is linked, and Apple Developer/App Store Connect agreements and credentials are valid.

## Web: exact-SHA landing and Fly deployment

This release changes ASK-class auth/config/API surfaces, so it never lands through automatic promotion. Follow the ASK landing procedure in `docs/autonomous-delivery-runbook.md`; the steps below are that procedure applied to this release. Do not bypass `scripts/classify_path_risk.py`, do not commit or push directly to `main`, and do not weaken the `main` ruleset beyond the bounded window in step 4.

1. **Review evidence.** Open a PR carrying the reviewed diff for the candidate SHA. The PR carries the review record; it cannot itself land, because the landing deploy key is the only `restrict_updates` bypass actor, so no PR merge and no human push can update `main`.
2. **Explicit recorded approval.** Record, in the evidence packet, the named approver, what they approved (this exact SHA and this ASK scope), and when. Landing without a recorded approval is not permitted.
3. **Exact-SHA required CI.** Record the candidate SHA and the run URLs proving both required checks — `Full CI` **and** `Docker Images` — succeeded for that exact SHA. A green run on any other SHA is not evidence for this one.
4. **Short, audited, temporary ruleset intervention.** Because the deploy key is normally the sole bypass actor, the maintainer temporarily grants themselves bypass on the `main` ruleset for the minimum window needed to land. Record who made the change, why, the exact start time, and the approval and CI run URLs from steps 2–3. Change nothing else about the ruleset: `restrict_updates` stays enabled, required checks stay required, and force pushes and deletions stay rejected.
5. **Land.** Fast-forward `main` to the exact approved SHA (never force, no merge commit, no amend). If the fast-forward is rejected because `main` moved, restore the ruleset immediately and restart from step 3 with a rebased candidate and fresh exact-SHA CI.
6. **Immediate restoration and redacted verification.** Restore the `main` ruleset to the landing deploy key as the **only** bypass actor as soon as the push completes — before the deploy is observed, not after. Then verify and record, with values redacted (names only, never secret values): `restrict_updates` enabled; deploy key sole bypass; `Full CI` and `Docker Images` still required; `landing` and `production` environments still restricted to branch `main`; and the ruleset window closed with its end time. Record the intervention as closed only after this verification.
7. **Production deploy and smoke.** Let the `main` push CI run drive `.github/workflows/deploy-fly-production.yml`: it must prove `origin/main` equals the CI-tested SHA before any Fly mutation, capture rollback images, stage the smoke identity and the authoritative flag rollout, deploy backend/frontend, and run its authenticated smoke. Do not substitute a manual `fly deploy` for failed or missing exact-SHA evidence.
8. Internal smoke, with the rollout flag enabled:
   - sign in and verify Connected agents is visible on web and iOS;
   - add a disposable HTTPS test connector and run connection verification;
   - open a task, review exactly what will leave Brain Buddy, and dispatch once;
   - verify duplicate confirmation does not create a second outbound start;
   - submit authenticated accepted/running/blocked/completed events and verify the task shows them verbatim;
   - answer the blocked question and verify the answer stays on the same run;
   - confirm the UI says **Agent reported complete**, not that Brain Buddy completed the task;
   - disconnect and verify credentials are not returned or logged.
9. Expand the flag only after smoke evidence is attached to the exact production SHA. Widening `external_agent_relay` beyond `internal` is a separate, separately approved change to the staged rollout in `.github/workflows/deploy-fly-production.yml`.

### Web rollback

- Disable `external_agent_relay` first to stop new user hand-offs while preserving inbound reporting for already-dispatched runs.
- Use the production workflow's captured rollback images/procedure; do not rewrite history.
- Preserve agent/run/audit records for diagnosis. Rotate `BRAIN_BUDDY_AGENT_RELAY_KEYS` only through the documented key-ring procedure; removing the active old key can make stored connection credentials undecryptable.

## iOS: TestFlight to App Store

Run from `mobile/` only after the web API for the same compatible release is live:

1. `npx eas-cli whoami`
2. Link/verify the project: `npx eas-cli init` or `npx eas-cli project:info`. This may add Expo owner/project metadata; review it before commit.
3. Verify locally: `npm test -- --runInBand`, `npm run typecheck`, `npm run integration`, and `npx expo export --platform ios`.
4. Build the exact release commit: `npx eas-cli build --platform ios --profile production`. Record build ID, git SHA, app version, and build number.
5. Submit that build to TestFlight: `npx eas-cli submit --platform ios --profile production --id <BUILD_ID>`.
6. Internal TestFlight smoke the connection, reviewed hand-off, run states, blocked reply, stopped-reporting text, disconnect, and feature-flag-off behavior.
7. Complete App Store metadata/privacy answers and submit the tested build for Apple review. Production availability is not claimed until App Store Connect shows the release available and a clean-device install succeeds.

### iOS rollback

- Immediately disable `external_agent_relay` server-side if the relay is unsafe; the app fails closed and existing task behavior remains.
- Stop phased release/remove the affected version from sale in App Store Connect as appropriate, then ship a corrected incremented build. Installed App Store binaries cannot be remotely rolled back.

## Manual gates and secrets

- Required human/authority gates: reviewed ASK PR with explicit recorded approval, the audited temporary ruleset intervention and its recorded restoration, Apple Developer/App Store Connect access, Apple review, and production rollout decision.
- Secret names only: `BRAIN_BUDDY_AGENT_RELAY_KEYS`, `FLY_API_TOKEN`, `TRUNK_LANDING_SSH_KEY`, `BRAIN_BUDDY_ADMIN_EMAIL`, `BRAIN_BUDDY_ADMIN_PASSWORD`, and App Store Connect/EAS credentials.
- Never place endpoint credentials, webhook signing secrets, Apple keys, or API tokens in issues, logs, commits, screenshots, or chat.
