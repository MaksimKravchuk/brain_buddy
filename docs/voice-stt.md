# Voice Brain Dump accurate STT

Voice Brain Dump records original browser audio and treats browser speech recognition only as a provisional preview. After Stop, the backend may send sealed audio to the configured accurate-STT provider only when the operation contains explicit external-processing consent.

## Configure OpenAI

Set these in the runtime environment (see `.env.example`):

- `BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER=openai`
- `BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL=gpt-4o-mini-transcribe` (or `gpt-4o-transcribe`)
- `BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV=OPENAI_API_KEY`
- set the named credential variable, e.g. `OPENAI_API_KEY`, outside source control

Timeout, retry backoff, per-operation estimated-cost ceiling, and retention settings are independently bounded. Missing credentials resolve to the explicit `disabled` provider. No-consent, disabled, authentication, cost-limit, oversized-audio, retry-exhaustion, and invalid-response failures use redacted error codes; provider response bodies, transcripts, vocabulary, audio, credentials, and paths are not copied into errors or logs.

`deterministic` accurate STT is selected automatically only in the test environment. Production refuses that provider unless `BRAINBUDDY_ALLOW_DETERMINISTIC_STT=1` is deliberately set.

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

For extraction scoring, `expected_tasks_file` may remain a JSON string list or
use labelled objects such as
`{"title":"Починить BrainBuddy","structural_change":"split"}`. The semantic
reconciler supplies per-operation confidence and split/merge labels so the
report can calculate labelled boundary precision/recall, semantic preservation,
split/merge accuracy, and confidence calibration rather than treating matching
task counts as matching boundaries.

Run the credentialed STT-only track from the repository root:

```sh
cd backend
uv run python ../scripts/evaluate_voice_stt.py /absolute/path/to/corpus --consent-external-processing
```

The command prints aggregate CER, WER, critical-term recall, omission/hallucination counts, mean/p95 latency, and p95 latency grouped by duration, disjoint language cohort, and provider/model. Ground truth is read by the scorer after the provider call and is never included in `AccurateSttRequest`. Without consent or configured credentials, the report is explicitly `disabled` and makes no provider call.

Task-extraction metrics are a separate optional scorer input in `evaluate_real_audio_corpus`; STT output is never presented as proof of downstream extraction quality. No speech-accuracy threshold is claimed until the founder corpus produces a measured baseline.
