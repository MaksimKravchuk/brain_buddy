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
   Keep private relay destinations disabled unless separately governed. Also
   before deploy — while the running image is still the previous one — carry out
   **Pre-deploy: count the bespoke connection rows** below and record the number
   with the release evidence. The 014 image performs a one-way migration at
   startup; counting afterwards asks the migration to grade itself.
4. Let the exact landed `main` SHA run
   `.github/workflows/deploy-fly-production.yml`. Historically the workflow
   staged the relay's rollout in the flag string; staging that name crashed
   the image the automatic rollback restored in deploy run 31775660872,
   because a staged secret survives the image swap and that image rejects an
   unknown flag at startup. That rollback-compatibility blocker has since been
   cleared — the captured rollback target is now a 009 image that parses the
   name — but rollout is no longer granted through this workflow line at all:
   `external_agent_relay` is one of the three Admin Portal SQLite-managed
   flags (ADR-0019), evaluated as two independent axes AND'd together — the
   *rollout* (OFF/ON/SELECTED_USERS, set at `/admin`, effective within about
   fifteen seconds, no deploy required) and the *capability* (whether step
   3's `BRAIN_BUDDY_AGENT_RELAY_KEYS` actually constructed a secret box at
   boot). Either being unfavorable fails closed. Do not widen the cohort as
   part of this release; that is a separate, audited Admin Portal action, not
   a workflow or environment edit — and from spec 014 onward, one that
   **Rollout gate: the refreshed iOS build must be the only distributed build**
   below decides is permitted at all.
5. Smoke the deployed image over the A2A wire, using a disposable agent you
   operate behind public HTTPS and an internal account, through the **web**
   client. This is the one named exception to the rollout gate below, and it
   carries its own guard: the flag goes ON for that one internal account only,
   the operator first confirms no pre-014 iOS build is signed in to it, and the
   cohort is emptied again the moment the smoke ends. Record both facts with the
   evidence. Verify, in order:

   - the agent card is fetched from the address's well-known location and the
     agent's name, version, protocol version and declared capabilities are shown
     as inert text — no anchor, no interpreted markup;
   - **Test connection** succeeds, the guarantee tier is disclosed, and a
     best-effort agent demands the one-time duplicate acknowledgement before its
     first hand-off;
   - the hand-off review lists exactly what will be sent — Task title, details
     and the supporting items, each one removable — with the cancellation
     disclosure and the external-copy notice for the push callback address;
   - one confirmed hand-off shows **Queued** while it waits for a free exchange
     worker and only becomes **Sent** once the exchange has actually started;
   - the run reaches **Agent reported complete** from Brain Buddy's own
     authenticated observation, not from anything the agent pushed;
   - a reply and a cancel behave as the agent's declared support allows: an
     agent that refuses cancellation says so instead of the run pretending to be
     cancelled;
   - **Check again** on a **Delivery unconfirmed** run looks the run up by its
     correlation ID and adopts an existing task rather than sending again;
   - disconnect destroys the credential and the card summary and stops
     observation and push registration for that connection's runs.

   Then confirm the negative half: no credential, no per-run push token and no
   token fingerprint appears in any response, error envelope, audit row or log
   line — including the access log — and every error surfaces its correlation
   ID. Attach the smoke evidence to the deployed SHA under the same disclosure
   rule as **Hermes live evidence** below.

### Pre-deploy: count the bespoke connection rows

Spec 014 replaces the bespoke relay wire with A2A, and the replacement is
one-way. At startup the 014 image runs the ledgered migration
`a2a_wire_contract_v1`, which disconnects every connection whose stored payload
does not carry `wire: "a2a"`, destroys its credential and its inbound signing
secret, stamps its in-flight runs, and writes one `wire_superseded` audit row
per rewritten connection. The spec assumes there are no such rows in
production. An assumption is not evidence, so count them.

Run this **before** the 014 image starts, against the running previous image:

```bash
flyctl ssh console --app "${BACKEND_APP}"
```

then, on the machine (`BRAIN_BUDDY_DATA_DIR` is `/app/data`, and the connection
between `mode=ro` and creating nothing is the point — an empty file left behind
would look like an answer):

```bash
python - <<'COUNT'
import os, sqlite3

path = "/app/data/agents.sqlite3"
if not os.path.exists(path):
    print("bespoke_connection_rows=0 (no relay database on the volume)")
    raise SystemExit
db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
if db.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_connections'"
).fetchone() is None:
    print("bespoke_connection_rows=0 (no agent_connections table)")
    raise SystemExit
total = db.execute("SELECT COUNT(*) FROM agent_connections").fetchone()[0]
bespoke = db.execute(
    "SELECT COUNT(*) FROM agent_connections "
    "WHERE COALESCE(json_extract(payload, '$.wire'), '') <> 'a2a'"
).fetchone()[0]
print(f"total_connection_rows={total} bespoke_connection_rows={bespoke}")
COUNT
```

Record the number with the release evidence, whatever it is.

- **Zero** is the expected result and the one that lets the release proceed
  unchanged.
- **Not zero** means real owners configured connections on the old wire, and
  every one of them is about to be irreversibly disconnected with the reason
  `superseded_wire_contract`, its credential destroyed. That is a product
  decision, not a deploy detail: stop, say what will happen to those
  connections, and get the call made before the image starts.

After the deploy, cross-check that the image's own ledger recorded the same
number — the durable half of the evidence, and the reason the count sits on the
ledger row rather than in someone's notes:

```bash
python - <<'LEDGER'
import sqlite3

db = sqlite3.connect("file:/app/data/agents.sqlite3?mode=ro", uri=True)
print(db.execute(
    "SELECT rewritten_rows, applied_at FROM agent_schema_migrations WHERE name = ?",
    ("a2a_wire_contract_v1",),
).fetchone())
LEDGER
```

`backend/tests/test_agent_repository_migration.py` is what proves the migration
behaves this way — it is the suite `quickstart.md` §9 runs, and it is what this
step trusts when it reads that number.

### Rollout gate: the refreshed iOS build must be the only distributed build

**`external_agent_relay` MUST NOT be turned ON for any user until the refreshed
iOS build is the only distributed build — TestFlight and App Store phased
release complete.** This gate is the migration note constitution Principle III
requires for 014. It is recorded in
`specs/014-a2a-relay-wire-contract/contracts/api-deltas.md` (§Compatibility) and
repeated here because a runbook step is the only place it can be enforced.

Why a runbook step is the mechanism. The 014 API is breaking for a strict
client: two routes removed, `endpoint_url` renamed to `agent_address`,
`context_items` renamed to `supporting_items`, `inbound_signing_secret` and
`capabilities.progress` removed, `auth_scheme` newly required, new response
types and label values, `destination_endpoint` renamed to
`destination_interface` on the hand-off manifest — which both clients render
today — and `protocol_version` redefined from the bespoke `2026-08-09` to the
A2A `1.0`. The web client ships lockstep with the backend behind the Fly
frontend proxy, so it is never the exposure. The iOS client is
store-distributed: an installed App Store binary cannot be rolled back
remotely, and the client sends no build header, so there is no minimum-build
check to fall back on. What protects a stale build is the flag itself — while
`external_agent_relay` is OFF, a pre-014 build sees exactly the OFF surface it
sees today, the gated routes answering the same fail-closed 404 and the ungated
reads returning empty collections, because no relay record exists for any user.
Turning the flag ON while an older build is still installed is the single action
that turns a compatible deploy into a broken client.

So, in order:

1. Ship **TestFlight and App Store** below through its step 6 — App Store
   Connect reports the build available, phased release is complete, and a
   clean-device install succeeds.
2. Attach **Hermes live evidence** below to the release SHA.
3. Only then widen the cohort, one audited Admin Portal action at a time
   (ADR-0019). Rollout is never a deploy, a workflow line or an environment
   edit.

The only exception is step 5's internal smoke, and it is narrow by
construction: one internal account, on the web client, with no pre-014 iOS build
signed in to it, and the cohort emptied again when the smoke ends.

### Fly rollback

Use the images captured by the failed release run. With `BACKEND_APP`,
`FRONTEND_APP`, `PREVIOUS_BACKEND_IMAGE`, `PREVIOUS_FRONTEND_IMAGE`, and
`TESTED_SHA` (the failed release's exact tested SHA) set to that run's
recorded values, contain and roll back directly. The staged flag string must
name only flags the restored image can parse — naming a flag it does not know
fails its startup, which is how run 31775660872 turned a rollback into a
crash loop. Do not hardcode or guess that string: derive it exactly the way
the deploy workflow's own rollback step does, by reading it from the
PREVIOUS revision of the deploy workflow — `${TESTED_SHA}^`, the parent of the
failed release — through the unit-tested `scripts/extract_staged_feature_flags.py`
parser, which fails closed on anything malformed or ambiguous and never prints
a flag name or value. Ordinarily that previous revision staged only
`delivery_canary`; the restage always restores that exact captured previous
revision string as-is, which may include legacy managed flags such as
`voice_brain_dump` — that is intentional, since the restored old image needs
its own previous contract, not the current one. Stage the derived
rollout before restoring the previous backend image — that image is the
release which applies the pending secret, so staging after it would leave the
restored image running the failing release's flags — while the frontend image
is still restored first:

```bash
if ! PREVIOUS_FEATURE_FLAGS=$(git show "${TESTED_SHA}^:.github/workflows/deploy-fly-production.yml" \
  | python3 scripts/extract_staged_feature_flags.py); then
  echo "Could not derive the previous feature-flag rollout from TESTED_SHA's" >&2
  echo "parent revision of the deploy workflow. Refusing to roll back the" >&2
  echo "images — restoring an old image under an unknown or guessed rollout" >&2
  echo "is exactly the crash loop this contract exists to prevent. Contain" >&2
  echo "and escalate per the incident procedure in" >&2
  echo "docs/autonomous-delivery-runbook.md; do not substitute a hardcoded" >&2
  echo "delivery-only rollout." >&2
  exit 1
fi
if [ -z "${PREVIOUS_FEATURE_FLAGS}" ]; then
  echo "Derived an empty previous feature-flag rollout. Refusing to roll" >&2
  echo "back the images; contain and escalate instead." >&2
  exit 1
fi
flyctl secrets set --stage --app "${BACKEND_APP}" \
  BRAIN_BUDDY_FEATURE_FLAGS="${PREVIOUS_FEATURE_FLAGS}"
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

### Rollback consequences once a 014 run exists

The procedure above restores the previous images, and for spec 014 that is
safe — but only because of a mitigation that had to be built on purpose. State
it rather than inherit it.

With the flag OFF, a 007 image keeps working on 014 rows: connection reads, the
run projection, the GDPR export, content expiry and purge. Storage keeps the
`endpoint_url` key (the API is what renames it to `agent_address`),
`auth_header_name` is stored only for API-key connections and never holds a
reserved name, and `StorageBaseModel` ignores unknown fields, so a frozen copy
of the 007 `AgentConnectionDocument` validates a 014 connection payload
(`test_frozen_007_connection_document_validates_a_014_payload`).

Run rows were the real boundary, and the failure they would have caused is
worth naming because it is silent. The 007 `AgentRunManifest` requires the
bespoke `reporting` and `reporting_instructions` keys; `AgentRepository._model`
raises on any row that fails validation; and the 007 image's
`expire_due_content` validates every due run row inside one `BEGIN IMMEDIATE`
transaction *before* nulling anything. Unmitigated, the first 014 run to reach
its 30-day boundary would make that sweep raise and roll back on every pass —
no content expiring for **any** owner, the sweeps that run after it skipped, and
the exception swallowed once a minute — and `export_owner_data`, which also
validates every run row, would fail the always-on GDPR export for any owner
holding a 014 run.

The mitigation, verified rather than assumed:

- every 014 manifest also writes `reporting` and `reporting_instructions` with
  inert placeholder values in the frozen 007 shape, so a 014 run row validates
  under a 007 image
  (`test_frozen_007_run_event_and_command_documents_validate_014_payloads`);
- the 014 `expire_due_content` skips and logs an unparseable row — correlation
  ID, no content — instead of aborting the transaction for every owner, so the
  same failure class cannot recur in the other direction.

What rollback still cannot do, and what to tell people:

- A 007 image **cannot observe a 014 run.** The observer does not exist there
  and the bespoke event route has no secret, so every run dispatched under 014
  freezes at its last observed state until the 014 image returns. After the
  first 014 dispatch, rollback is a decision with a user-visible consequence,
  not a silent redeploy.
- The migration is **one-way.** Restoring the previous image does not bring back
  a superseded bespoke connection or the credential that was destroyed with it.

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

## Hermes live evidence

Approval-gated exactly like the `verify-live` skill: it spends real provider
money against a real installation. **Never** run it in CI, from a subagent, or
on a schedule. A human runs it, with explicit human approval, and attaches the
result to the release SHA. Rollout stays OFF until that evidence exists
(FR-017; `quickstart.md` §8 is the walk-through).

The run: configure a real Hermes gateway with the A2A platform enabled and a
bearer token behind public HTTPS, add it as a connection in a staging Brain
Buddy, hand off one Task, answer one question, and cancel one run. What you are
proving is that the wire works against an installation nobody adapted for us —
the plugin is unmodified and there is no BrainBuddy-specific code on the agent
side.

The evidence is a **closed field list**. Only these may be recorded:

- the agent's name and version, as its card declares them;
- the protocol version and the declared capabilities;
- the guarantee tier disclosed at the hand-off review;
- the correlation IDs of the requests;
- the run id;
- the resulting `primary_state_label` sequence.

And this half is closed too — none of it may appear in the evidence, in any
form, including inside a screenshot:

- the agent address or `interface_url`;
- the credential;
- the per-run push token or its fingerprint;
- the card description, or any skill name or skill description;
- the handed-off Task's title, its details, or its supporting items;
- artifacts, result text, or any of the agent's model output.

The tension is deliberate. Real model output is what makes this run worth doing
and is exactly what must not survive it: read it on the screen, confirm it
renders inertly — no clickable link, no interpreted markup — and keep it out of
the file. If a screenshot would carry a single field from the second list, it is
not evidence, it is a leak.
