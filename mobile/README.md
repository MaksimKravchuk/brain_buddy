# Brain Buddy mobile (iOS-first)

React Native (Expo SDK 57) client for Brain Buddy: the four GTD lists
(Inbox / Next actions / Waiting for / Someday), projects & tags, task detail
with the full lifecycle, quick capture, and the voice **brain dump**
(record → upload → review proposals → confirm to inbox).

The app talks to the same backend as the web app, with the same cookie
session (`brainbuddy_session` rides iOS's native cookie jar) and the same
optimistic-concurrency contract (`Idempotency-Key` header +
`expected_revision` on every mutation).

## Run it on your iPhone (Expo Go)

> Never used Node or Expo before? Follow **[GETTING_STARTED.md](./GETTING_STARTED.md)** — it assumes nothing.

```bash
cd mobile
npm install
npx expo start            # scan the QR code with the iPhone camera
```

- **Against production** (default): sign in with your Brain Buddy account.
  The server URL defaults to `https://brain-buddy-frontend.fly.dev/api`. The
  first request after idle may be slow — the Fly machines cold-start.
- **Against a local backend**: run `make dev-backend` on your machine with
  `--host 0.0.0.0` (or `uvicorn app.main:app --app-dir backend --host 0.0.0.0`),
  then open *Server settings* on the sign-in screen and set
  `http://<your-lan-ip>:8000/api`. Phone and laptop must share a network.
  Outside production the session cookie is not `Secure`, so plain HTTP works.
- **Voice brain dump** requires the `voice_brain_dump` feature flag for your
  account (`BRAIN_BUDDY_FEATURE_FLAGS="voice_brain_dump=on"` locally); the
  mic button hides itself when the flag is off or no STT provider is
  configured.

Everything in the app runs inside Expo Go — no dev build needed for v1.

## Verify on Linux/CI (no Xcode required)

```bash
make typecheck-mobile     # tsc --noEmit
make test-mobile          # jest unit tests (manifest golden vectors, guards, uploader, machine, client)
make integration-mobile   # boots a disposable test backend (deterministic AI providers)
                          #   and runs the REAL api client end-to-end:
                          #   auth → tasks/transitions/409 → projects/tags →
                          #   brain-dump seal protocol (text fixture + multi-chunk WAV)
make build-mobile         # expo export --platform ios (Metro bundle integrity)
make lint-mobile          # eslint, with every eslint-config-expo rule enforced
make mutation-mobile      # report-only Stryker campaign over the deterministic core
```

`integration-mobile` needs the backend Python deps (`make install-backend`).

`test-mobile` also enforces `mobile/coverage-floor.json`, which may only ratchet
upward. `mutation-mobile` is report-only and scoped by ADR-0013 — see
`docs/decisions/0013-mobile-deterministic-core-mutation-scope.md` for what is
mutated, what is not, and what promoting it to a blocking gate would require.

## Architecture

```
src/app/                 expo-router routes
  list/[state]           the four GTD lists (drawer navigation, per the mobile design)
  task/[id]              detail: check row + chips, edit fields, complete/move/reopen/cancel
  brain-dump/index       capture (mic badge + timer head, waveform sheet, stop & review)
  brain-dump/[operationId]  processing → review proposals → confirm (bottom sheet)
  sign-in, settings, history, project/[id], tag/[id]
src/components/shell/    TopBar (hamburger · mic · avatar), Drawer (GTD nav + projects
                         + tags + history), PaneHead, AddTaskRow — the design's mobile shell
src/api/                 client.ts (port of frontend/src/api/client.ts), types, React Query hooks
src/auth/                SessionProvider (cookie session, /me probe, 401 → sign-in)
src/braindump/           manifest hashing, chunk uploader, capture state machine, recorder config
src/lifecycle/guards.ts  ADR-0006 transition matrix (UI never offers invalid commands)
src/theme/tokens.ts      design tokens from .claude/skills/brain-buddy-design/colors_and_type.css
src/components/          BBText, Button, TaskRow, Sheet, chips, toasts, brain-dump animations
integration/             Node harness + scenarios (real client, real backend)
```

The mobile IA follows the "Brain Buddy Mobile" design (Claude Design project
`40b1b752…`, drawer-nav variant), translated to the shipped contracts: Tags
instead of `@contexts`, no agent/executor chips (Execution is deferred),
"Weekly review · coming later", and the provisional brain-dump language
required by ADR-0006 (B-37).

### Contracts the client honors

- **ADR-0006 GTD lifecycle** — four open states; `move` to a *different*
  open state; `reopen` names an explicit destination; anything entering
  Waiting requires a non-blank `waiting_for`; 409 → refetch, keep the user's
  input, explicit retry.
- **ADR-0002 voice operations (shipped subset)** — audio uploads as
  strictly-sequential numbered chunks with `X-Content-SHA256`; the seal
  `manifest_hash` is byte-identical to the backend's
  (`_brain_dump_manifest_hash`, golden-tested in
  `src/braindump/__tests__/manifest.test.ts`); proposals are edited through
  serialized PATCHes; nothing becomes a task before the explicit confirm.
- **Recording format** — WAV (LINEARPCM 16 kHz mono) on iOS: the server
  ffmpeg-inspects the cumulative byte prefix of uploaded chunks, which m4a
  cannot satisfy (its moov atom is written at EOF). Chunks are 896 KiB to
  stay under the production nginx proxy's 1 MiB default body cap. Android
  falls back to m4a (single-chunk only) and is untested in v1.

## Known v1 limitations

- **No live capture stack while speaking** (the centerpiece of the "Brain
  Buddy Mobile Prototype" design: rolling transcript, forming card,
  proposals growing live). The backend already supports it — posting
  preview segments to `POST …/transcript` drives live server-side
  provisional extraction, exactly as the web app does — but live iOS
  speech recognition needs `expo-speech-recognition`, a native module that
  cannot run in Expo Go. Phase B = dev build (EAS; free-Apple-ID builds
  expire weekly, the paid Apple program removes that), live transcript
  strip + "Provisional · N" stack per `app/dump-core.jsx` / `dump.css` in
  the design project. Until then the flow is record → stop → review.
- Project/tag *assignment* and subtask/comment editing are read-only in the
  app (create/manage them on the web); quick add does attach the current
  project/tag context.
- No task search or date views yet; no relaunch-resume for an in-flight
  brain dump (reopening the app returns to the lists; the operation stays
  recoverable server-side).
- Android runs but is unpolished and its recording path is limited (see
  above).
