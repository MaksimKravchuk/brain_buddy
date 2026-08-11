@AGENTS.md

## Mobile (Expo / React Native, iOS-first)

Targets live in the repo `Makefile` (`install-mobile`, `typecheck-mobile`,
`lint-mobile`, `test-mobile`, `integration-mobile`, `build-mobile`,
`mutation-mobile`); `cd mobile && npx expo start` runs on an iPhone via Expo Go.
Only the things those files don't tell you:

- `make integration-mobile` needs `make install-backend` first — it drives the
  real api client against a disposable local backend.
- `make mutation-mobile` (report-only Stryker, ADR-0015 scope, ~5 min) is **not**
  part of `ci-mobile`.
- `make lint-mobile` enforces every `eslint-config-expo` rule.
- `make build-mobile` is `expo export --platform ios` — a Metro bundle check.

Mobile unit tests run the real screens, hooks and api client against a fake
backend installed over `global.fetch` (`mobile/src/test/fakeBackend.ts`); only
device boundaries are stubbed, in `mobile/jest.setup.js`.

See `mobile/README.md` for the device runbook and `mobile/AGENTS.md` for the
wire-protocol contracts the client must keep (chunk hashing, manifest hash,
lifecycle guards).
