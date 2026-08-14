# External-agent relay release

This is the release procedure for the web relay and Expo iOS client. It does
not authorize landing, deployment, rollout expansion, or App Store submission.

## ASK candidate and production web release

1. Open an ASK PR for the focused candidate. Record both independent reviews
   and the required CI results against the same exact candidate SHA. A rebase,
   amend, or follow-up commit invalidates that evidence.
2. Obtain separate explicit ASK landing authority and follow the existing ASK
   landing procedure in `docs/autonomous-delivery-runbook.md`. Do not weaken
   checks, push directly, or substitute evidence from another SHA.
3. Before deploy, configure `BRAIN_BUDDY_AGENT_RELAY_KEYS` in the production
   secret store with an active encryption key. Never print or commit key bytes.
   Keep private relay destinations disabled unless separately governed.
4. Let the exact landed `main` SHA run
   `.github/workflows/deploy-fly-production.yml`. The workflow authoritatively
   stages the flag string, and it no longer names `external_agent_relay`:
   staging that name crashed the image the automatic rollback restored in
   deploy run 31775660872, because a staged secret survives the image swap and
   that image rejects an unknown flag at startup. The relay therefore ships
   default OFF by omission — it stays that way until a successful deployment
   of a backend that knows the name has become the captured rollback target,
   at which point naming it in that workflow line is an audited ASK edit. Do
   not widen the cohort as part of this release, and do not set the flag out
   of band: the next release restages the workflow's value regardless.
5. Using a disposable HTTPS connector and an internal account, verify connect
   and test, reviewed task/context hand-off, one dispatch under duplicate
   confirmation, authenticated run updates, reply/cancel when supported,
   **Agent reported complete** copy, disconnect, and absence of secrets in
   responses and logs. Attach smoke evidence to the deployed SHA.

### Fly rollback

Use the images captured by the failed release run. With `BACKEND_APP`,
`FRONTEND_APP`, `PREVIOUS_BACKEND_IMAGE`, and `PREVIOUS_FRONTEND_IMAGE` set to
that run's recorded values, contain and roll back directly. The staged flag
string must name only flags the restored image can parse — naming a flag it
does not know fails its startup, which is how run 31775660872 turned a
rollback into a crash loop:

```bash
flyctl secrets set --app "${BACKEND_APP}" \
  BRAIN_BUDDY_FEATURE_FLAGS='delivery_canary=internal,voice_brain_dump=on'
flyctl deploy --config fly.frontend.toml --app "${FRONTEND_APP}" \
  --image "${PREVIOUS_FRONTEND_IMAGE}"
flyctl deploy --config fly.backend.toml --app "${BACKEND_APP}" \
  --image "${PREVIOUS_BACKEND_IMAGE}"
curl --fail "https://${BACKEND_APP}.fly.dev/health"
work_dir=$(mktemp -d)
trap 'rm -rf "${work_dir}"' EXIT
python3 - >"${work_dir}/login.json" <<'PY'
import json, os
print(json.dumps({"email": os.environ["BRAIN_BUDDY_SMOKE_EMAIL"],
                  "password": os.environ["BRAIN_BUDDY_SMOKE_PASSWORD"]}))
PY
curl --fail --silent --cookie-jar "${work_dir}/cookies" \
  -H 'Content-Type: application/json' --data-binary @"${work_dir}/login.json" \
  "https://${FRONTEND_APP}.fly.dev/api/auth/login" >/dev/null
body=$(curl --fail --silent --cookie "${work_dir}/cookies" \
  "https://${FRONTEND_APP}.fly.dev/api/auth/me")
BODY="${body}" python3 - <<'PY'
import json, os
flags = json.loads(os.environ["BODY"]).get("feature_flags", {})
if flags.get("external_agent_relay") is not False:
    raise SystemExit("external_agent_relay is not effectively OFF")
print("external_agent_relay is effectively OFF")
PY
```

OFF blocks new relay setup and dispatch while preserving owner-scoped monitoring,
authenticated inbound reports, and safe supported reply/cancel for existing runs
as required by FR-019. Preserve relay records for diagnosis and keep every
encryption key needed to read them; an image rollback does not restore or rotate
secrets.

## TestFlight and App Store

From `mobile/`, after the compatible web API is live:

1. Verify EAS/Expo and Apple credentials with `npx eas-cli whoami` and
   `npx eas-cli project:info`; do not commit credentials.
2. Run mobile tests, typecheck, integration, and
   `npx expo export --platform ios` on the exact release SHA.
3. Build with
   `npx eas-cli build --platform ios --profile production` and record the build
   ID, git SHA, version, and build number.
4. Submit that build with
   `npx eas-cli submit --platform ios --profile production --id <BUILD_ID>`.
5. Smoke the TestFlight build with the internal rollout, including rollout-OFF
   behavior for an existing run. Complete App Store privacy/metadata and submit
   the tested build for Apple review.
6. Claim availability only after App Store Connect reports it available and a
   clean-device install succeeds.

For an iOS incident, set the server flag OFF, stop phased release or remove the
version from sale as appropriate, and ship an incremented corrected build;
installed App Store binaries cannot be remotely rolled back.