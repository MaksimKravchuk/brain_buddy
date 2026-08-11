# Brain Buddy mobile — agent guide

Expo SDK 57 / React Native 0.86 / TypeScript strict / expo-router. Expo APIs
changed across SDK majors: verify against the local type definitions in
`node_modules/expo-*/build/*.d.ts` (or https://docs.expo.dev/versions/v57.0.0/)
before writing expo-audio / expo-file-system code — do not trust memory.

## Commands (also as root Makefile targets `*-mobile`)

```bash
npm run typecheck     # tsc --noEmit — must stay clean
npm run lint          # eslint — every eslint-config-expo rule is on; do not turn any off
npm test              # jest unit tests
npm test -- --coverage  # also what the coverage floor is measured from
npm run integration   # real client vs disposable local backend (needs backend pip deps)
npm run mutation      # report-only Stryker campaign (ADR-0015 scope)
npx expo export --platform ios   # Metro bundle integrity check
```

## Testing

Unit tests run against a fake backend installed over `global.fetch`
(`src/test/fakeBackend.ts`) and the real `SessionProvider`, React Query client
and screens — no product module is ever mocked. Only device boundaries are:
the recorder, the file system, crypto, navigation and safe-area insets, each
stubbed in `jest.setup.js` with a stand-in under `src/test/` that records what
the product code asked it to do.

`mobile/coverage-floor.json` may only ratchet upward; CI checks a branch that
edits it against the base branch's copy.

## Non-negotiable contracts

- `src/braindump/manifest.ts` must stay byte-identical with the backend's
  `_brain_dump_manifest_hash` (`backend/app/workflows/voice_brain_dump/service.py`).
  The golden vectors in its test were computed with Python `hashlib`/`json` —
  if you change either side, regenerate both.
- Audio chunks: strictly sequential numbers, `X-Content-SHA256` per chunk,
  ≤ 896 KiB each (prod nginx caps bodies at 1 MiB), and the cumulative byte
  prefix must parse as the declared mime — hence WAV on iOS, never m4a for
  multi-chunk uploads.
- Every mutation sends `Idempotency-Key` + `expected_revision`; request
  bodies must not carry extra keys (backend models are `extra="forbid"`).
- Lifecycle guards (`src/lifecycle/guards.ts`) mirror ADR-0006 — the UI
  never offers a transition the server would reject.
- Design tokens come from `.claude/skills/brain-buddy-design/` (the
  `/brain-buddy-design` skill). Sentence case, Lucide icons only, ambient
  animation only inside the brain dump, 44pt hit targets.

## Style

Follow the repo conventions (`../AGENTS.md`): TypeScript strict, PascalCase
component files, conventional commits (`feat(mobile): …`).
