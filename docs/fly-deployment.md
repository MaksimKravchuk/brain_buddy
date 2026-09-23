# Fly.io Deployment Runbook

> **Production release policy:** [ADR-0008](decisions/0008-verified-trunk-serial-landing.md),
> as amended by [ADR-0023](decisions/0023-proportionate-fast-lane-for-test-stage-ship-show.md),
> sends eligible SHIP/SHOW work through PR-less verified trunk: exact-SHA candidate CI,
> serial landing, deploy-time main-head proof, and authenticated production smoke. ASK
> work retains explicit approval, exact-SHA green CI, review evidence, and the audited
> landing intervention in the autonomous delivery runbook. The setup commands below are
> bootstrap/reference material, not authority for an agent or operator to perform an ad-hoc
> production deploy. Follow the
> [autonomous delivery runbook](autonomous-delivery-runbook.md) for release, incident, and
> rollback controls.

Deploy the Brain Buddy backend and frontend as separate Fly.io apps. The backend is private and reachable only over Flycast from apps in the same organization; the frontend remains public and proxies `/api` requests to the private backend. The steps below cover prerequisites, persistent storage, secret wiring, deployment, validation, and rollback.

## Prerequisites
- Install the Fly CLI (`flyctl`) from https://fly.io/docs/hands-on/install/ and run `flyctl auth login`.
- Ensure Docker is available locally or enable Fly's remote builder (`flyctl deploy --remote-only`).
- Decide on two app names: one for the backend API and one for the frontend (e.g., `brain-buddy-api` and `brain-buddy-web`).
- Confirm the GitHub Actions CI workflow is green before deploying (see "CI guardrails" below) so the images you ship match what was tested.

## CI guardrails
- **Workflow location:** `.github/workflows/ci.yml` runs on pushes/PRs to `main`. It lints and type-checks the backend (Ruff + mypy), runs backend pytest with coverage, executes frontend unit tests with coverage, builds the frontend bundle, and performs Docker image builds for both services.
- **Run locally:** `make test-backend` and `make test-frontend` mirror the CI steps. Optionally, `docker compose build` validates the Dockerfiles locally.
- **Deploy only after green:** Wait for the CI badge in the README or the Actions tab to go green. If CI is red, fix the failures locally before running any Fly deploys.

## Backend setup (API)
1. **Create the app (once):**
   ```bash
   flyctl apps create <backend-app>
   ```
2. **Provision persistent storage for tree and task data:**
   ```bash
   flyctl volumes create brain-buddy-data \
     --size 1 \
     --region <fly-region> \
     -a <backend-app>
   ```
   Mount the volume at `/app/data` (the backend's default data path) in your `fly.toml`:
   ```toml
   [mounts]
   source="brain-buddy-data"
   destination="/app/data"
   ```
3. **Configure secrets:** session auth needs no signing secret, but you almost certainly want to seed your own admin account so you can sign in without SSHing in to mint an invite.
   ```bash
   flyctl secrets set \
     BRAIN_BUDDY_ADMIN_EMAIL=you@yourdomain.com \
     BRAIN_BUDDY_ADMIN_PASSWORD='<a-long-random-password>' \
     BRAIN_BUDDY_API_PREFIX=/api \
     -a <backend-app>
   ```
   On startup the backend will create that account (or rotate its password to match the env var if it already exists). Rotate later by updating the secret and redeploying. See `docs/auth.md` for the full model.

## Data storage, backups, and seeding
The data directory (`BRAIN_BUDDY_DATA_DIR`, mounted at `/app/data` in production) holds multiple coordinated stores:

- **Trees** — one JSON file per tree plus an index file. Tree version snapshots, export/import, and `scripts/load_dataset.py` operate on these JSON files only.
- **Tasks, projects, tags, and brain-dump operations** — a single SQLite database, `tasks.sqlite3`, managed by the task module (`backend/app/modules/tasks/repository.py`).
- **CRT mutation receipts** — `crt_commands.sqlite3`, the 30-day Thinking/CRT replay/reconciliation store from ADR-0026. It must be restored with the tree JSON/index it coordinates.

Neither SQLite database is covered by tree JSON snapshots, tree export/import, or `scripts/load_dataset.py`. Quiesce writers/checkpoint SQLite before a filesystem copy, and include database `-wal`/`-shm` sidecars when copying a live store. Prefer backing up the entire data directory — e.g. a Fly volume snapshot (`flyctl volumes snapshots create <volume-id> -a <backend-app>`) or copying the whole mount via `flyctl ssh sftp` — over cherry-picking individual files. A CRT restore is valid only after a disposable restore/boot proves tree/index state and command receipts are coherent or that ADR-0026 pending reconciliation completes deterministically before traffic.

## Bootstrap/reference: deploy the backend
Run the deployment from the repository root so the Dockerfile path resolves correctly. The resulting app has no public `fly.dev` hostname; it listens on `http://<backend-app>.flycast:8000` for in-organization callers such as the frontend.
```bash
flyctl deploy \
  --dockerfile backend/Dockerfile \
  --app <backend-app> \
  --remote-only
```
When prompted for a volume, select `brain-buddy-data` to mount at `/app/data`.

## Bootstrap/reference: deploy the frontend
1. **Create the app (once):**
   ```bash
   flyctl apps create <frontend-app>
   ```
2. **Point the client at the backend (Flycast):**
   ```bash
   flyctl secrets set \
     BACKEND_ORIGIN="http://<backend-app>.flycast:8000" \
     VITE_API_BASE_URL="/api" \
     -a <frontend-app>
   ```
   The frontend proxies `/api/*` requests (including `Cookie` and `Set-Cookie` headers) to the private backend, preserving the session cookie end-to-end.
3. **Deploy:**
  ```bash
  flyctl deploy \
    --dockerfile frontend/Dockerfile \
    --app <frontend-app> \
    --remote-only
  ```

## Smoke verification
- **Backend health (via Fly SSH into the private app):**
  ```bash
  flyctl ssh console -a <backend-app> -C "curl -f http://127.0.0.1:8000/health"
  ```
- **Mint an invite for yourself:**
  ```bash
  flyctl ssh console -a <backend-app> -C "python -m app.cli create-invite"
  ```
- **Frontend reachability and backend wiring:**
  ```bash
  curl -I https://<frontend-app>.fly.dev
  curl -f "https://<frontend-app>.fly.dev/api/health"  # proxied to backend via Flycast
  ```
  Expect an HTTP 200 from Nginx. Open the URL in a browser, sign up with your invite on `/signup`, and confirm the canvas loads after authentication.

## Feature 019 CRT rollback (ordered operator procedure)

This is an operator checklist and a **local/synthetic drill contract**. It is not
release evidence and makes no claim that Feature 019 is deployed. Record a completed
drill in the scrubbed [rollback evidence template](../specs/019-miro-like-crt-canvas/evidence/rollback/feature-019-crt-rollback.template.json).
The persistence and image-order rules below are required by
[ADR-0026](decisions/0026-crt-revision-and-idempotency-protocol.md).

### Rollback invariants

- `crt_canvas` is a server-owned runtime flag. Do not use a client-side setting or an
  image rollback to turn exposure off.
- The **recorded Stage A compatibility SHA and image** are the oldest permitted image
  after any Stage B write. A pre-Stage-A image is forbidden after Stage B has written
  `revision`, `schema_version`, or command receipts.
- Set the flag OFF and prove the OFF read-back before touching an image. Do not begin an
  image rollback while a pending CRT receipt is unresolved.
- Checkpoint/backup the **entire** `BRAIN_BUDDY_DATA_DIR` after writers are quiesced,
  including tree JSON and index files, `tasks.sqlite3`, `crt_commands.sqlite3`, and
  any SQLite `-wal`/`-shm` sidecars. A tree export is not a backup.
- A failed read-back is an abort, not a warning. Remain on the current image with CRT
  exposure OFF, or use an approved forward fix/restore path; never guess a target image.

### Ordered procedure

1. **Declare and freeze the exact target.** Obtain the incident/approval record and
   capture the running candidate SHA, backend/frontend release identifiers, and the
   previously recorded Stage A compatibility SHA/image. Verify the candidate SHA is the
   release being contained and that Stage A evidence predates every Stage B write. If
   either Stage A identifier is absent, ambiguous, or not an exact image digest, abort.
   Do not record credentials, cookies, graph text, idempotency keys, or raw local drafts.
2. **Quiesce CRT writers without destroying recovery state.** Stop new CRT save/create/
   import/delete attempts and drain in-flight requests using the platform's approved
   maintenance procedure. Tell operators not to clear browser/site storage. Do not
   sign users out, discard queued commands, or delete pending local drafts; preserve
   owner/origin/tree scope, generation, and pending-request metadata for the drill.
3. **Turn the server flag OFF first.** Through the authenticated admin path, write the
   existing managed flag endpoint (no new rollback endpoint is implied):
   ```bash
   curl --fail-with-body --cookie "$OPERATOR_COOKIE" \\
     -H 'Content-Type: application/json' \\
     -X PUT "$BACKEND_ORIGIN/api/admin/feature-flags/crt_canvas/mode" \\
     --data '{"mode":"off"}'
   ```
   Never place the cookie or any other secret in the evidence file.
4. **Read back the OFF state and fail closed.** Read `GET /api/admin/feature-flags`,
   `GET /api/auth/me`, and the content-free `GET /api/crt/exposure` using the same
   authenticated operator/test identity. Require the managed mode to be `off`,
   `auth.me.feature_flags.crt_canvas` to be `false`, and exposure to be HTTP `404`
   with `detail.reason=crt_canvas_disabled`. Read representative `/api/crt/*` list/
   load routes as well; they must be `404`, must not contain tree/card/relation content,
   and must retain a correlation ID. A `503`, `200`, missing reason, or any CRT content
   is an abort.
5. **Prove no CRT content mutation after OFF.** In the synthetic drill, issue one
   disabled-route mutation against a disposable fixture only (never create a new
   production write). Read the canonical fixture before and after and record only
   opaque fixture identity, revision, schema version, request status, and content-free
   booleans. Require zero successful CRT mutations, the disabled mutation to be `404`,
   and unchanged revision/schema/content-preservation read-backs. Do not infer this
   from the flag write alone. Any revision advance, changed canonical content, or
   successful CRT mutation aborts the rollback.
6. **Prove local draft preservation.** Before and after the OFF transition, enumerate
   only the active authenticated owner's browser-local CRT recovery records. Compare
   opaque record IDs, generation/count metadata, and queued-command counts; do not put
   graph text or a content fingerprint in evidence. Require every pending draft and
   exact in-flight request/key to remain recoverable, with no clear/discard operation
   and no cross-owner/origin read. If storage enumeration, scope verification, or
   preservation fails, abort and do not claim recovery.
7. **Reconcile pending receipts before changing the image.** Read the pending count in
   `crt_commands.sqlite3`, run the release's supported CRT startup/maintenance
   reconciliation while writers remain quiesced, then read the count again and capture
   the number reconciled plus any error. Require deterministic reconciliation of every
   pending row and a final pending count of zero. A malformed receipt store, an
   unreconcilable marker, an unknown count, or any remaining pending row is an abort;
   do not use a Stage A image over it. Do not purge receipts as a substitute for
   reconciliation.
8. **Checkpoint the complete data directory and verify its identity.** After the
   receipt read-back is clean, checkpoint/backup the full `BRAIN_BUDDY_DATA_DIR` with
   SQLite writers stopped and sidecars included. Use the resulting snapshot/checkpoint
   identity in the evidence and read it back from the platform. A missing identity,
   failed snapshot/read-back, incomplete directory, or unverified disposable restore
   aborts the image rollback.
9. **Prove Stage A compatibility on the checkpoint, then and only then roll back.**
   Boot a disposable restore with the exact recorded Stage A compatibility image.
   Read a representative tree through the legacy owner-scoped API and verify that
   top-level `schema_version` and positive `revision` are readable and preserved, the
   tree/index and reconciled receipts are coherent, and the public response omits the
   internal `last_command_id`. Do not use any pre-Stage-A image. If Stage A cannot
   read the checkpoint without dropping fields or if the image/digest differs from the
   recorded target, abort and remain OFF.
10. **Apply only the approved exact Stage A target.** With explicit exact-target human
    authority, use the recorded Stage A backend image/release (and its paired frontend
    image if the frontend must be reverted); do not substitute a release number whose
    image was not read back. Reconcile `main` through the normal reviewed path after
    incident containment. This procedure does not authorize an ad-hoc deploy.
11. **Verify the rolled-back state before declaring recovery.** Read back health and
    release/image identity, the server flag (`off`), `/api/auth/me` (`crt_canvas=false`),
    `/api/crt/exposure` and representative CRT routes (`404`, disabled reason, no
    content), the unchanged fixture revision/schema/content proof, zero pending
    receipts, the preserved local drafts, and the checkpoint identity. If any
    read-back fails, keep exposure OFF, do not claim rollback success, and escalate
    for forward-fix or restore handling.
12. **Complete the evidence record.** Mark the result only after all read-backs pass.
    The record must remain scrubbed and explicitly identify the drill as synthetic or
    the real operator record as applicable; it must never imply that this repository's
    template is proof of production deployment.

### Mandatory abort conditions

Abort and stop at the first occurrence of any of the following: missing exact candidate
or Stage A SHA/image; a pre-Stage-A rollback target; inability to set or read back
`crt_canvas=off`; any CRT route other than content-free disabled `404`; a successful
CRT mutation or changed revision/content after OFF; lost, cleared, or cross-scope local
drafts; an unknown, malformed, or unreconciled pending receipt; a non-zero final pending
count; a missing/incomplete/unreadable full-data-directory checkpoint; a Stage A
schema/revision compatibility failure; an image digest mismatch; or any failed
post-rollback read-back. In every abort case, leave the flag OFF and use only an
approved forward fix or a verified backup restore—never a guessed older image.

## Rollback guidance
- For normal changes, use a reviewed revert PR and the standard `main` release path. Use a
  Fly release revert only to contain an active incident under explicit, exact-target human
  authority, then reconcile `main` immediately. See the autonomous delivery runbook.
- List recent releases for either app:
  ```bash
  flyctl releases -a <app-name>
  ```
- Revert to a previous release number if needed:
  ```bash
  flyctl release revert <release-version> -a <app-name>
  ```
  After a rollback, re-run the smoke checks above to confirm the restored version is healthy.
