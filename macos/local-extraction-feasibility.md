# Local task extraction check — 2026-09-26

## Target and boundary

- Device: MacBook Air (Mac16,12), Apple M4, 16 GB RAM, macOS 26.5.2.
- Candidate: Apple's on-device Foundation Models framework available in the
  installed macOS SDK. No remote model or API was used.
- Input/output goal for a later trial: turn a Russian voice transcript or text
  into separate editable GTD task drafts without inventing commitments.

## Availability result

With local Swift module caches, the check
`xcrun swift -e 'import FoundationModels; print(SystemLanguageModel.default.availability)'`
returned:

```text
unavailable(FoundationModels.SystemLanguageModel.Availability.UnavailableReason.appleIntelligenceNotEnabled)
```

No `ollama`, `mlx_lm`, or `llama-cli` executable was found in `PATH`. No GGUF,
safetensors, or MLX language-model files were found in the local Hugging Face
model directory or user cache inspected. The installed Whisper model is for
speech recognition, not task extraction.

## Decision and next measurable trial

There is no available local language model to run an extraction sample now.
Quality, inference time, and peak memory therefore have **no measured result**;
hardware suitability remains unproven. The app keeps one editable transcript
draft and does not offer automatic multi-task extraction or a cloud fallback.

When a local model becomes available, use a fixed set of 6–10 Russian samples:
one action, several actions, a dated action, a waiting-for item, ambiguous
commitment, and text without an action. Record each input, raw model output,
elapsed time, peak memory, missed or invented actions, classification errors,
and required edits before deciding whether to ship the feature.
