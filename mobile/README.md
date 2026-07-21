# Brain Buddy mobile

Expo Router mobile client for the approved first slice: opaque native session transport, canonical task lists, task detail/transition, and low-friction capture.

## Setup

```bash
cd mobile
npm install
EXPO_PUBLIC_API_ORIGIN=http://10.0.2.2:8000/api npm start
```

Use `http://10.0.2.2:8000/api` on Android emulators, `http://localhost:8000/api` for an iOS simulator, and a reachable HTTPS/LAN origin for physical devices. The public origin is configuration, not a secret; do not put credentials or tokens in `app.config.ts`, `eas.json`, or EAS public variables.

## Validation

```bash
npm run typecheck
npm run lint
npm test
npx expo export --platform web
```

Jest results use the Allure Jest environment and write `allure-results/`; artifacts are ignored by Git.

## API contract refresh

The committed `api/openapi.json` snapshot and `src/api/openapi.generated.ts` are generated
from an ephemeral in-process backend test app. Generation never calls a running backend,
an arbitrary URL, Fly, or production:

```bash
npm run api:generate
cd ../backend && python -m scripts.openapi_snapshot check --snapshot ../mobile/api/openapi.json
cd ../mobile && npm run typecheck && npm test
```

The backend owns API semantic versioning; it is distinct from persisted-data schema version.
The client attaches the opaque session credential as
`Authorization: Bearer <opaque-session-token>`; it is not a JWT. Expo SecureStore is the only
persistent credential store. The client clears
a credential on first-install marker absence, definitive `401`, or sign-out, but preserves it
for retry after transient network and `5xx` bootstrap failures. JSON API failures include
`X-Correlation-ID`, mirrored as `reference_id` in the standard error envelope.

## EAS profiles

`eas.json` contains development, preview, and production profiles. Set `EXPO_PUBLIC_API_ORIGIN` to the appropriate non-secret API origin for each build environment; release credentials remain in EAS-managed secrets.
