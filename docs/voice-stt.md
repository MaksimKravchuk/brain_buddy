# Voice Brain Dump accurate STT

Voice Brain Dump records original browser audio and treats browser speech recognition only as a provisional preview. After Stop, the backend may send sealed audio to the configured accurate-STT provider only when the operation contains explicit external-processing consent.

## Configure OpenAI

Set these in the runtime environment (see `.env.example`):

- `BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER=openai`
- `BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL=gpt-4o-mini-transcribe` (or `gpt-4o-transcribe`)
- `BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV=OPENAI_API_KEY`
- set the named credential variable, e.g. `OPENAI_API_KEY`, outside source control

No-consent, disabled, authentication, cost-limit, oversized-audio,
retry-exhaustion, and invalid-response failures use redacted error codes;
provider response bodies, transcripts, vocabulary, audio, credentials, and
paths are not copied into errors or logs.

`deterministic` accurate STT is test-only. Production refuses that provider unconditionally.

## Runtime limits, retries, retention, and sweep

All Voice Brain Dump controls are server environment variables. The `.env.example`
file lists the current defaults for local Compose; production secrets stay in the
runtime secret store and are never placed in this repository.

### Provider controls

| Purpose | Accurate STT | Text reconciler |
|---|---|---|
| Enable/provider | `BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER` | `BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER` |
| Model | `BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL` | `BRAIN_BUDDY_VOICE_RECONCILER_MODEL` |
| Credential variable name | `BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV` | `BRAIN_BUDDY_VOICE_RECONCILER_API_KEY_ENV` |
| Endpoint | provider-defined | `BRAIN_BUDDY_VOICE_RECONCILER_ENDPOINT` |
| Deadline | `BRAIN_BUDDY_VOICE_ACCURATE_STT_TIMEOUT_SECONDS` | `BRAIN_BUDDY_VOICE_RECONCILER_TIMEOUT_SECONDS` |
| Retry count | `BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_RETRIES` | `BRAIN_BUDDY_VOICE_RECONCILER_MAX_RETRIES` |
| Retry delays (comma-separated seconds) | `BRAIN_BUDDY_VOICE_ACCURATE_STT_RETRY_BACKOFF_SECONDS` | `BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS` |
| Role cost ceiling | `BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_COST_USD` | `BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD` |
| Estimated cost rate | `BRAIN_BUDDY_VOICE_ACCURATE_STT_ESTIMATED_COST_USD_PER_MB` | `BRAIN_BUDDY_VOICE_RECONCILER_ESTIMATED_COST_USD_PER_MB` |

Set either provider to `disabled` to fail closed: the server does not make an
external call and returns a redacted disabled-provider result. Missing named
credentials, absent external-processing consent, or a consent/provider mismatch
also fail closed. `deterministic` accurate STT remains test-only and production
startup rejects it.

Each role checks its own retry/deadline/cost limits. The operation also enforces
`BRAIN_BUDDY_VOICE_MAX_CUMULATIVE_COST_USD` across all accurate-STT and
reconciler attempts, including retries and recovery. It stops retrying after
`BRAIN_BUDDY_VOICE_MAX_OPERATION_RECOVERIES`; the persisted runner uses
`BRAIN_BUDDY_VOICE_LEASE_RECOVERY_MARGIN_SECONDS` before reclaiming an expired
lease.

### Audio, retention, and runner controls

Uploaded audio is accepted only when it stays within these limits:

- `BRAIN_BUDDY_VOICE_AUDIO_ALLOWED_MIME_TYPES`
- `BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_BYTES`
- `BRAIN_BUDDY_VOICE_AUDIO_MAX_TOTAL_BYTES`
- `BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_COUNT`
- `BRAIN_BUDDY_VOICE_AUDIO_MAX_DURATION_SECONDS`
- `BRAIN_BUDDY_VOICE_AUDIO_ASSUMED_CHUNK_DURATION_SECONDS`

Raw uploaded audio is purged after
`BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS`; uncommitted transcript and
proposal working artifacts are purged after
`BRAIN_BUDDY_VOICE_WORKING_ARTIFACT_RETENTION_SECONDS`. The persisted runner
recovers due/expired provider runs and performs both retention sweeps every
`BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS`. A value of `0` disables its periodic
thread, while application startup still performs one synchronous recovery/purge
pass. `BRAIN_BUDDY_ENABLE_VOICE_SWEEP_IN_TEST=1` is test-only opt-in for that
periodic thread.

## Language and keyterm hints

Before recording, choose Russian, Russian + English, or English. The first declared hint controls the provisional browser recognizer locale (`ru-RU` or `en-US`). All declared hints and comma-separated keyterms are persisted with consent and passed to accurate STT. For RU + EN, OpenAI receives `language=ru` plus the English/Russian keyterms as a prompt.

## Real-audio evaluation

Founder audio and ground truth stay outside the repository. A corpus directory uses this shape:

```json
{
  "version": 1,
  "cases": [{
    "id": "founder-ru-en-1",
    "audio_file": "sample.webm",
    "ground_truth_transcript_file": "sample.transcript.txt",
    "expected_tasks_file": "sample.tasks.json",
    "language_hints": ["ru", "en"],
    "vocabulary": ["BrainBuddy", "production smoke"],
    "critical_terms": ["BrainBuddy", "production smoke"],
    "duration_seconds": 42
  }]
}
```

For title/count-only extraction scoring, `expected_tasks_file` may remain a JSON
string list. Boundary scoring requires labelled source provenance, for example
`{"title":"Починить BrainBuddy","source_spans":[[0,1500]],"structural_change":"split"}`.
Each span is a non-negative `[start_ms, end_ms]` pair. The semantic reconciler
receives the STT provider's actual segments plus the case language hints and
vocabulary; its `source_segment_ids` are resolved back to these spans. Boundary
precision/recall then matches source provenance only. Title equality and semantic
similarity remain separate metrics, so shared title tokens or matching task counts
cannot masquerade as labelled boundaries. Reconciler confidence and split/merge
labels continue to drive calibration and structural accuracy.

Run the credentialed STT-only track from the repository root:

```sh
cd backend
uv run python ../scripts/evaluate_voice_stt.py /absolute/path/to/corpus --consent-external-processing
```

The command prints aggregate CER, WER, critical-term recall, omission/hallucination counts, mean/p95 latency, and p95 latency grouped by duration, disjoint language cohort, and provider/model. Ground truth is read by the scorer after the provider call and is never included in `AccurateSttRequest`. Without consent or configured credentials, the report is explicitly `disabled` and makes no provider call.

Task-extraction metrics are a separate optional scorer input in `evaluate_real_audio_corpus`; STT output is never presented as proof of downstream extraction quality. No speech-accuracy threshold is claimed until the founder corpus produces a measured baseline.
