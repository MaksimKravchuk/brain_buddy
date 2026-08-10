---
name: verify-live
description: APPROVAL-GATED, COSTS MONEY. Build/launch/drive recipe for verifying BrainBuddy backend changes end-to-end against the live API with real Deepgram and OpenAI traffic. Use only when a human has explicitly approved a live drive. For the free deterministic chain use the self-verify skill instead.
user-invocable: true
disable-model-invocation: true
---

# Verifying BrainBuddy end-to-end (live)

> **Cost and approval gate.** This recipe drives the real Deepgram and OpenAI
> providers and spends money on every run. **No unattended agent may invoke
> it** — not `feature-implementer`, not `delivery-verifier`, not a scheduled
> or background session. A human must explicitly approve each live drive.
>
> The free, deterministic, key-free equivalent for everyday verification is
> the **`self-verify`** skill; `make integration-mobile` covers the real API
> client against a disposable local backend with no paid provider involved.
> Reach for this skill only when the thing under test *is* the live provider
> integration.

# Verifying BrainBuddy end-to-end

## Launch

```bash
cd backend && <venv>/bin/python -m uvicorn app.main:app --port 8000
```

- `load_dotenv()` in `app/core/config.py` picks up repo-root `.env` (voice provider
  config + API keys live there, gitignored). `BRAIN_BUDDY_DATA_DIR=/app/data` falls
  back to `backend/data` automatically when unwritable.
- The voice provider sweep runs in-process (thread started from `app/main.py`), so
  sealed brain-dump operations progress without extra workers.
- Health: `GET /health`.

## Auth

Signup needs a one-shot invite: `cd backend && python -m app.cli create-invite`.
Then `POST /api/auth/signup {email, password, invite_code}` and
`POST /api/auth/login` (session cookie; use one `httpx.Client` for the whole flow).

## Voice brain-dump drive (the full pipeline)

1. `GET /api/brain-dump-providers` → `{"accurate_stt": ..., "reconciler": ...}`.
2. `POST /api/brain-dump-operations` with consent naming BOTH role providers
   (`providers: [stt, reconciler]`). **All POST commands under /api/tasks &
   /api/brain-dump-operations require an `Idempotency-Key` header** (400 without).
3. `PUT .../audio/0` — raw audio bytes, `Content-Type: audio/mp4` (or webm/wav),
   `X-Content-SHA256: <hex sha256 of body>`.
4. `POST .../seal` with `expected_revision`, `expected_chunks`, and
   `manifest_hash` = sha256 of the compact JSON
   `[{"chunk_number":N,"sha256":...,"size_bytes":N}]` (sorted keys, `(",",":")`
   separators) — mirrors `_brain_dump_manifest_hash` in the service.
5. Poll `GET .../{id}` until `awaiting_confirmation` (~30-60s for a 4-min file:
   Deepgram STT ~5s + gpt-4o reconcile ~20s) — inspect `provider_runs` for
   per-role status/error codes.
6. `POST .../commit` then `GET /api/tasks` to see the committed tasks.

A working scripted drive exists from 2026-07-29 (session scratchpad
`e2e_drive.py`) — reuse its shape.

## Gotchas

- Sample audio: any m4a works; `~/Downloads/Jekerstraat 35-3.m4a` was the
  reference multilingual (RU + EN terms) corpus matching
  `~/Downloads/founder_ru_reading_script.md`.
- Consent must name the configured vendors or the run fails closed with
  `STT_CONSENT_PROVIDER_MISMATCH` / `RECONCILER_CONSENT_PROVIDER_MISMATCH`.
- Test suite is hermetic against `.env` (conftest scrubs `BRAIN_BUDDY_VOICE_*`
  and provider keys) — a dev `.env` cannot break pytest, and pytest proves
  nothing about the live wiring; verify live wiring via this drive.
