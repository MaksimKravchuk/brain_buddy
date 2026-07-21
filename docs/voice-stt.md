# Voice Brain Dump accurate STT

Voice Brain Dump records original browser audio and treats browser speech recognition only as a provisional preview. After Stop, the backend may send sealed audio to the configured accurate-STT provider only when the operation contains explicit external-processing consent.

## Configure the authorized MVP providers

Set these in the runtime environment (see `.env.example`):

- `BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER=deepgram`
- `BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL=nova-3`
- `BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV=DEEPGRAM_API_KEY`
- set `DEEPGRAM_API_KEY` outside source control
- `BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER=openai`
- `BRAIN_BUDDY_VOICE_RECONCILER_MODEL=gpt-5.6-luna`
- `BRAIN_BUDDY_VOICE_RECONCILER_TEMPLATE_VERSION=product-operation-v1`
- set the named reconciler credential variable outside source control

Nova-3 uses Deepgram's multilingual mode for Russian + English captures. The
reconciler is pinned to GPT-5.6 Luna with the `product-operation-v1` contract;
Terra, Sol, and Fable are not authorized defaults or automatic fallbacks.

Timeout, retry backoff, per-operation estimated-cost ceiling, and retention settings are independently bounded. Missing credentials resolve to the explicit `disabled` provider. No-consent, disabled, authentication, cost-limit, oversized-audio, retry-exhaustion, and invalid-response failures use redacted error codes; provider response bodies, transcripts, vocabulary, audio, credentials, and paths are not copied into errors or logs.

`deterministic` accurate STT is test-only. Production refuses that provider unconditionally.

## Language and keyterm hints

Before recording, choose Russian, Russian + English, or English. The first declared hint controls the provisional browser recognizer locale (`ru-RU` or `en-US`). All declared hints and comma-separated keyterms are persisted with consent and passed to accurate STT. For RU + EN, Deepgram receives `language=multi` plus the English/Russian keyterms.

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
