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

The committed `api/openapi.json` snapshot and `src/api/openapi.generated.ts` are generated from the backend OpenAPI document. Refresh only against an intended running backend:

```bash
EXPO_PUBLIC_API_ORIGIN=http://127.0.0.1:8000/api npm run api:generate
npm run typecheck && npm test
```

The client attaches the opaque credential as `Authorization: Bearer <token>`. Expo SecureStore is the only persistent credential store; the client clears stale credentials on first-install marker absence, unauthorized responses, or sign-out.

## EAS profiles

`eas.json` contains development, preview, and production profiles. Set `EXPO_PUBLIC_API_ORIGIN` to the appropriate non-secret API origin for each build environment; release credentials remain in EAS-managed secrets.
