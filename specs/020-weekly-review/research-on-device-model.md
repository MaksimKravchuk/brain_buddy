# Research: on-device model for the AI navigator (FR-019…FR-026)

Checked 2026-10-05. Scope: which model serves first-step proposals on iOS/macOS
when Apple's on-device model can't, and how we judge SC-005 before launch.

**Evidence flags.** **[V]** means I read the primary source in this session
(developer.apple.com docs or video transcript, a GitHub repo, App Store
guidelines). **[S]** means it comes from search snippets or secondary sources
only, because the primary page was blocked (apple.com, support.apple.com,
huggingface.co, developers.google.com, mjtsai.com, callstack.com, infoq.com and
mera.a-ai.ru were all blocked by the egress proxy). **[U]** means it is
unverified: an estimate or an inference.

## TL;DR

1. **Apple's on-device model does not support Russian, on iOS 26.x or iOS 27.**
   For a Russian task the framework throws `unsupportedLanguageOrLocale`. So
   for the owner's main language, FR-023 is the **normal path**, not an edge
   case.
2. **iOS 27 changes the build plan.** The new `LanguageModel` protocol lets one
   `LanguageModelSession` + `@Generable` code path run Apple's model, a local
   Core AI or MLX model, or PCC. That is iOS 27+ only, and the app targets
   iOS 26.
3. **Recommendation:**
   - Runtime: **Core AI** (Apple's first-party successor to Core ML, iOS 27+).
   - Model: **Qwen3-1.7B, 4-bit/palettized** (Apache-2.0).
   - Delivery: an **Apple-hosted Background Assets** pack, downloaded on demand.
   - Contender: **Gemma 4 E2B** (Apache-2.0). Choose between the two with the
     offline eval below.
   - Deployment target stays iOS 26. Option (a) is gated on
     `#available(iOS 27, *)` plus a memory check.
   - Either runtime adds a SwiftPM dependency with third-party transitive deps,
     so it **needs an ADR** that amends `ios/AGENTS.md` "No third-party
     dependencies".
4. **Fallback:** if no candidate clears the eval gate, ship cloud-only (FR-024
   consent) for unsupported languages and hide option (a). This needs a small
   FR-023 wording change.

## 1. Apple Foundation Models

### Languages

- **The language list has 16 entries and no Russian.** The list is English,
  Danish, Dutch, French, German, Italian, Norwegian, Portuguese (BR/PT),
  Spanish, Swedish, Turkish, Vietnamese, Chinese (Simplified and Traditional),
  Japanese and Korean. **[S]**
  - Eight of these arrived in iOS 26.1, in Nov 2025. An Apple engineer confirms
    this in [forum 805378](https://developer.apple.com/forums/thread/805378).
    **[V]**
  - The WWDC26 newsroom footnote, quoted in search results, gives the same 16
    for iOS 27. **[S]**
  - The newsroom and support.apple.com/121115 pages themselves were blocked.
- **No source lists Russian for iOS 26.x or iOS 27.** **[S]**
- One report says Siri AI in iOS 27 will not support Russian or Ukrainian
  ([ukranews](https://ukranews.com/news/1156583-obnovlennaya-siri-ot-apple-ne-budet-podderzhivat-ukrainskij-i-russkij-yazyki)).
  **[S]**
- The language list is per OS version, and the docs say "language support
  improves over time in newer model and OS versions"
  ([languages article](https://developer.apple.com/documentation/foundationmodels/supporting-languages-and-locales-with-foundation-models)).
  **[V]** So the check must happen at runtime and never be hard-coded.

### Detection in code

All of the following is from the
[SystemLanguageModel docs](https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel)
and the
[UnavailableReason docs](https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/availability-swift.enum/unavailablereason).
**[V]**

- **`SystemLanguageModel.default.availability`** returns `.available` or
  `.unavailable(reason)`. The reasons map 1:1 onto FR-023's "say why" copy:
  - `.deviceNotEligible`
  - `.appleIntelligenceNotEnabled`
  - `.modelNotReady` (the model is downloading or the system is busy)
- **`supportedLanguages: Set<Locale.Language>`** and
  **`supportsLocale(_ locale: Locale = .current) -> Bool`**. These check the
  *user's/app's* locale with close-language fallback. They do **not** check the
  task text.
- **Runtime check of the text.** At `respond(...)` the framework "checks the
  language or languages of the input prompt text" and throws
  `unsupportedLanguageOrLocale`:
  - On iOS 26 it is `LanguageModelSession.GenerationError`, which is deprecated
    at 27.0.
  - On iOS 27 it is `LanguageModelError`.

  [Languages article](https://developer.apple.com/documentation/foundationmodels/supporting-languages-and-locales-with-foundation-models),
  [GenerationError](https://developer.apple.com/documentation/foundationmodels/languagemodelsession/generationerror).
  **[V]**
- **Guardrails apply only to supported languages.** Detection can miss a short
  phrase in an unsupported language mixed into supported text. **[V]** This
  matters for RU/EN code-switching.
- **Planning implication [U].** Before calling the model, classify the task
  text (title + notes) with `NLLanguageRecognizer` (NaturalLanguage, first
  party, no dependency).
  - If the dominant language, or any language above roughly 20% of tokens, is
    outside `supportedLanguages`, go straight to the FR-023 choice. Do not
    attempt the call and wait for it to throw.
  - Keep the thrown error as a backstop.
  - The language threshold is a planning choice.
- **Pinning the output language.** Instructions should begin with the exact
  phrase "The person's locale is <id>." and add "You MUST respond in <lang>".
  **[V]** In 2025 the forums reported that this was unreliable
  ([thread 793714](https://developer.apple.com/forums/thread/793714)). **[V]**

### Guided generation fit

- `@Generable` applies to structs and enums. `@Guide` supports `.count(n)` and
  `maximumCount(_:)` on arrays
  ([Generable](https://developer.apple.com/documentation/foundationmodels/generable)).
  **[V]**
- Suggested shape. Enums with associated values are avoided until tested
  **[U]**:

  ```swift
  @Generable struct NavigatorReply {
      var kind: Kind                       // .steps | .question
      @Guide(.maximumCount(3)) var steps: [String]
      var question: String?
  }
  ```

- The code then validates the reply itself: 1–3 non-empty steps XOR exactly
  one question. It also rejects duplicates of sibling titles (FR-019) and
  re-asks or fails per FR-025.
- The `Generable` schema counts against the context window, so keep the
  `@Guide` text short ([TN3193](https://developer.apple.com/documentation/technotes/tn3193-managing-the-on-device-foundation-model-s-context-window)).
  **[V]**

### Context window vs. our input

- The window is **4,096 tokens per session** on iOS 26.x (TN3193, still stated
  after its 2026-03-31 update for 26.4). **[V]**
- It is **8,192** on the iOS 27 model: `contextSize` prints 8192
  ([WWDC26-241](https://developer.apple.com/videos/play/wwdc2026/241/)). **[V]**
- `contextSize` and `tokenCount(for:)` arrived in iOS 26.4. **[V]**
- **Estimated input [U]:**

  | Part | Size |
  |---|---|
  | Instructions | ~250 tokens |
  | Schema | ~120 tokens |
  | Title + reason + project name | <100 tokens |
  | 20 sibling titles | ~400–700 tokens (Cyrillic tokenises less efficiently than Latin; TN3193 gives 3–4 chars/token for Latin) |
  | Output | ~200 tokens |

  That leaves roughly **2,500 tokens for notes on iOS 26**, or ~6,500 on iOS 27.
- **Spec question (FR-019):** the input is "exactly" the notes. When the notes
  exceed the budget, do we truncate them (and say so) or refuse? The proposal
  is to budget with `tokenCount(for:)` and truncate oldest-first with a visible
  notice.

### Device floor

- Apple Intelligence runs on iPhone 15 Pro/Pro Max, all iPhone 16/17, iPads
  with A17 Pro or M1+, and Macs with M1+. **[S]** (apple.com was blocked.)
- The docs say availability also depends on **region**
  ([SystemLanguageModel](https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel)).
  **[V]**
- Which devices iOS 27 itself supports: **[U]**.

### iOS 27 additions

All from [WWDC26-241](https://developer.apple.com/videos/play/wwdc2026/241/)
and the docs. **[V]**

- **Rebuilt on-device model.** It is better at reasoning and tool calling, adds
  vision, and has the 8K window above. There are three model versions: 26.0–26.3,
  26.4 and 27.0. Expect prompt drift, so re-run the eval per OS.
- **`LanguageModel` protocol** (iOS/macOS 27+,
  [docs](https://developer.apple.com/documentation/foundationmodels/languagemodel)).
  It lets `LanguageModelSession` be backed by:
  - `SystemLanguageModel`
  - `PrivateCloudComputeLanguageModel`
  - `CoreAILanguageModel` ([apple/coreai-models](https://github.com/apple/coreai-models))
  - `MLXLanguageModel` ([ml-explore/mlx-swift-lm](https://github.com/ml-explore/mlx-swift-lm))
  - Anthropic/Google packages

  Guided generation is a capability that a provider declares
  ([WWDC26-339](https://developer.apple.com/videos/play/wwdc2026/339/)).
  **One navigator code path for all backends — but only on iOS 27+.**
- **`PrivateCloudComputeLanguageModel`** (iOS 27+,
  [docs](https://developer.apple.com/documentation/foundationmodels/privatecloudcomputelanguagemodel)):
  - A larger model with a 32K window and reasoning.
  - "No prompts are ever stored", and the claims are independently verifiable.
  - Free within per-user daily quotas, which are higher with iCloud+.
  - It needs a managed entitlement. The developer must be enrolled in the
    **Small Business Program**, have **fewer than 2M first-time downloads**,
    and migrate away within 6 months if they cross that threshold
    ([PCC access](https://developer.apple.com/private-cloud-compute/)).
  - It has its own `supportedLanguages`, and is available "where Apple
    Intelligence is available". **Whether it accepts Russian is unverified
    [U]; probably not.**
- **Product question (PCC).** PCC is server-side, so task content *leaves the
  device*. That fails FR-022's "no task content leaves the device" and "works
  offline". It could at most be a variant of option (b), with FR-024 consent
  naming "Apple Private Cloud Compute". Two things to decide:
  1. Does the owner treat PCC as "on-device-grade" privacy, or as a cloud
     provider? The spec's wording says it is a cloud provider.
  2. If PCC does not support Russian, it does not help the main case at all.
     Verify on a device with `supportsLocale(ru_RU)` before spending effort on
     it.

## 2. Downloadable on-device model

### Runtimes

| Runtime | First-party? | OS floor | Dependency footprint | Notes |
|---|---|---|---|---|
| **Core AI** + `CoreAILanguageModel` | Core AI is an Apple system framework (successor to Core ML). The `coreai-models` Swift package is Apple-authored, BSD-3. **[V]** | iOS/macOS **27.0** **[V]** | `coreai-models` depends on swift-transformers, xgrammar, hummingbird and swift-argument-parser. Products: `CoreAILM`… **[V]** Whether only part of that is linked: **[U]** | ANE/GPU/CPU orchestration. AOT compile via `xcrun coreai-build compile`. Recipes include `qwen3`, `gemma3`, `gemma4`, `phi`, `smollm2`, `mistral`; **no `qwen3_5`**. Apple's session ships Qwen 0.6B on iPhone and 8B on Mac via Background Assets ([WWDC26-326](https://developer.apple.com/videos/play/wwdc2026/326/)). **[V]** |
| **MLX Swift** (`mlx-swift-lm`) | No (ml-explore, MIT) **[V]** | iOS 17 / macOS 14 **[V]** | mlx-swift, swift-syntax. Hugging Face download via swift-huggingface / swift-transformers. **[V]** | Works on iOS 26 too. Has an `MLXFoundationModels` bridge (iOS 27 SDK) and `MLXGuidedGeneration` (grammar-constrained). **[V]** GPU only, no ANE **[U]**. |
| **llama.cpp** (SPM / xcframework, MIT) | No | iOS 16+ **[U]** | C++ core, Metal | GGUF format. Shipped in App Store apps such as PocketPal AI **[S]**. No Foundation Models bridge; we would write our own JSON-grammar + `LanguageModel` adapter. |
| **LiteRT-LM** (Google) | No | **[U]** | Google SDK | Gemma 4 numbers below. A heavier vendor SDK. |

All rows break the `ios/AGENTS.md` "no third-party dependencies" rule, either
directly or transitively. **An ADR is required** in `docs/decisions/`.

Core AI's raw system framework without the package would avoid the dependency.
We would then have to write our own tokenizer and decode loop. That is a real
cost, and its feasibility is **[U]**.

### Candidate models

| Model | License (commercial App Store) | Download, quantized [U] | RAM working set [U] | Russian signal | Notes |
|---|---|---|---|---|---|
| **Qwen3-1.7B** | Apache-2.0 **[S]** | ~1.0–1.2 GB (4-bit) | ~1.5–2 GB | Qwen3 claims 119 languages **[S]**. No Russian-specific benchmark seen. | Has a Core AI recipe (0.6/1.7/4/8B), including iOS palettized configs. Recipe warns "may exceed memory limit when running from an iOS app" → `increased-memory-limit` entitlement. **[V]** Use non-thinking mode. |
| Qwen3-0.6B | Apache-2.0 **[S]** | ~0.4–0.5 GB | <1 GB | Weakest. Perplexity 26 vs 12 for 8B on WikiText-2. **[V]** | Apple's own iPhone example size. Risky for SC-005 in Russian. |
| Qwen3-4B | Apache-2.0 **[S]** | ~2.3 GB | ~3+ GB | Better | macOS only, or 8 GB+ iPhones. |
| **Gemma 4 E2B** | **Apache-2.0** (since Gemma 4, released 2026-04-02) **[S]** | ~2.6 GB (LiteRT file) **[S]** | ~1.5 GB peak on GPU **[S]** | 140+ languages. A secondary source calls Russian "tier 1" **[S/U]**. | Has a Core AI recipe (`gemma4`). **[V]** Multimodal weights inflate the download. On iPhone 17 Pro (LiteRT): ~56 tok/s decode on GPU, 25 tok/s on CPU **[S]**. |
| Gemma 3 1B/4B | **Gemma Terms of Use**: use restrictions must be passed on to end users in our terms, plus the Prohibited Use Policy **[S]** | 0.7 / 2.5 GB | — | 140 languages **[S]** | Superseded by Gemma 4's clean license. Avoid. |
| Llama 3.2 1B/3B | Llama 3.2 Community License: "Built with Llama" attribution, license copy, 700M MAU cap; the EU restriction is on the vision models **[S]** | 0.7 / 1.8 GB | — | Russian is not among the 8 official languages **[U]** | Worse license friction and weaker Russian. Avoid. |
| Qwen3.5-0.8B/2B | Apache-2.0, released 2026-03-02, 201 languages **[S]** | ~0.6 / 1.3 GB (with vision tower) | — | Probably better than Qwen3 **[U]** | **No Core AI recipe** **[V]**, so it would need MLX. Keep as an MLX-path alternative. |
| Vikhr-Qwen-2.5-1.5B-Instruct | Apache-2.0 **[S]** | ~0.9 GB (MLX 4-bit exists) **[S]** | — | Fine-tuned on Russian (GrandMaster-PRO-MAX) **[S]** | A Russian-tuned control for the eval. Older base. |

- **Speed is not the constraint [U].** The output is about 150 tokens (three
  short steps) and the prefill about 1–2K tokens. At the reported 25–56 tok/s
  decode for 1–2B models on recent iPhones **[S]**, that is roughly 3–8 s
  end-to-end.
- **The constraints are download size, RAM, and Russian quality.**
- **[U]** iPhone 15/16-class decode rates are secondary only. One article
  reports ~28–35 tok/s for a 1B Q4 model on iPhone 15 (A16) under llama.cpp
  **[S]**. Measure on-device before committing.

### Device floor proposal for option (a) [U]

- iOS/macOS 27 (Core AI).
- At run time, `os_proc_available_memory()` must be at least model working set
  + 500 MB.
- `com.apple.developer.kernel.increased-memory-limit` entitlement. "Only
  available on some device models"
  ([docs](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.increased-memory-limit)).
  **[V]**
- Practically this means 8 GB iPhones (15 Pro+ / 16 / 17) and Apple-silicon
  Macs. When the device fails the check, FR-023 hides (a) and states why.
  Those are the same devices as Apple Intelligence; the case that matters is
  **Russian on an Apple-Intelligence device**, which is exactly the owner.

### App Store and delivery

- **Guideline 2.5.2** forbids downloading "code which introduces or changes
  features". Model weights are data. Apps that download GGUF/MLX weights are
  on the App Store (PocketPal AI, Private LLM) **[S]**. Keep the prompt,
  schema and logic in the binary; the pack holds only weights and tokenizer.
  ([Guidelines](https://developer.apple.com/app-store/review/guidelines/))
  **[V]**
- **Guideline 4.2.3(ii):** "disclose the size of the download and prompt users
  before doing so" **[V]**. This matches FR-023(a), which already requires
  showing the size first.
- **Apple-hosted Background Assets** (iOS 26+):
  - Up to 200 GB / 200 packs per app, included in the membership.
  - The system manages download, update and compression.
  - Packs ship to TestFlight/App Store separately from builds. Apple names "update on-device ML models" as a use case.
  - Localized packs need iOS 27.

  ([overview](https://developer.apple.com/help/app-store-connect/manage-asset-packs/overview-of-apple-hosted-asset-packs/),
  [limits](https://developer.apple.com/help/app-store-connect/reference/app-uploads/apple-hosted-asset-pack-size-limits))
  **[V]**
  - Apple's Core AI session recommends this over bundling, "only when users
    opt-in" ([WWDC26-326](https://developer.apple.com/videos/play/wwdc2026/326/)).
    **[V]**
  - Prefer it to a runtime Hugging Face download. Apple hosting means no
    third-party host sees the user's IP, the version is pinned, and the pack
    goes through review.
  - Per-pack size cap: **[U]**. Only total and count limits were found.
- **Storage UX (FR-023a):**
  - Show the size before download, and check free space first. Free-space
    reads are a required-reason API, so add a `PrivacyInfo.xcprivacy` entry per
    `ios/AGENTS.md`.
  - Show progress, with a retry plus the cloud alternative on failure.
  - Settings shows the installed size and a "Delete model" action, which
    removes the pack.
  - Nothing else in the feature depends on the pack.
  - Store downloads Wi-Fi-only by default: **[U]**, a planning choice.

## 3. Recommendation

1. **Routing (iOS/macOS).**
   1. Detect the task language.
   2. If `SystemLanguageModel` is available *and* supports the language, use
      it. That covers English tasks on Apple Intelligence devices: FR-022 path,
      offline, free.
   3. Otherwise show the FR-023 choice, with the reason taken from
      `UnavailableReason`, or "language not supported".
2. **Option (a).**
   - Runtime: Core AI via `CoreAILanguageModel` behind the iOS 27
     `LanguageModel` protocol, so the navigator session, the `@Generable` reply
     and the validators are shared with the Apple-model path.
   - Model: **Qwen3-1.7B palettized 4-bit** on iPhone. The same 1.7B on Mac
     keeps evaluation simple; 4B on Mac is optional.
   - Delivery: an Apple-hosted on-demand asset pack.
   - Gate: `#available(iOS 27, macOS 27, *)` + memory check. Deployment target
     stays iOS 26.
   - Swap in **Gemma 4 E2B** if it beats Qwen3-1.7B on the Russian eval by a
     clear margin and the extra ~1.5 GB download is acceptable.
3. **Why not MLX first?**
   - It works on iOS 26 and has Qwen3.5. But it is a third-party GPU runtime
     with a Hugging Face download path, and a larger dependency tree to vet
     (swift-syntax, mlx-swift).
   - Core AI is Apple-maintained, supports AOT compile, ANE and Background
     Assets, and is the path Apple demonstrates.
   - MLX stays the plan B if Core AI's Qwen3 quality or memory fails. It is
     also the only route to Qwen3.5.
4. **ADR (needed whichever runtime is chosen).** Amend the
   "no third-party dependencies" rule for one vetted package, app target only,
   never `BrainBuddyCore`. Record license review (Apache-2.0 model, BSD/MIT
   runtime), the pinned versions, and the asset-pack provenance.
   `BrainBuddyCore` keeps the navigator *rules* (input assembly per FR-019,
   output validation, duplicate check), and these stay testable on Linux.
5. **Fallback.** If no candidate clears the gate below, ship **cloud-only** for
   unsupported languages:
   - FR-024 consent, the existing provider and cost caps.
   - Hide option (a) behind a flag.
   - Amend FR-023(a) to "when a qualifying model is available".
   - Revisit when Apple adds Russian, or when a better small model lands.
6. **Open questions for the owner:**
   - (i) Is PCC a cloud provider or "on-device-grade"? Moot if PCC lacks
     Russian.
   - (ii) Notes truncation when the input exceeds the context budget.
   - (iii) Is a ~1 GB (Qwen3-1.7B) vs ~2.6 GB (Gemma 4 E2B) download
     acceptable?
   - (iv) Is it OK that iOS 26.x users get only the cloud for Russian?

## 4. Offline evaluation for SC-005 (no real user data — constitution I)

- **Fixtures.** Synthetic only, at
  `backend/tests/fixtures/navigator/eval_v1.json`, or under `specs/020-…/eval/`.
  That follows the `voice_brain_dump/reference_corpus` precedent. About 48
  cases:
  - 24 Russian, 12 English, 12 RU/EN code-switched.
  - The cases cover each stall reason and none.
  - Vague tasks where the correct output is *one question* (~25%).
  - Tasks whose notes name people, places or amounts, which may be reused.
  - Tasks with none of these, where any such fact is invented.
  - Projects with 0, 5 and 20 sibling titles, including near-duplicates of the
    ideal step.
  - Each case carries `expected_kind`, `allowed_entities` (extracted from the
    input) and `sibling_titles`.
- **Who writes them.** The owner or an agent writes them from invented
  personas. Real tasks are paraphrased beyond recognition or not used. No real
  names.
- **Automatic checks** run per model and are deterministic over recorded
  outputs:
  1. Schema: 1–3 steps XOR exactly 1 question.
  2. Language match, via NLLanguageRecognizer or a stdlib heuristic. No new
     Python dependency.
  3. No duplicate of a sibling title: normalised, with token-overlap ≥ 0.8.
  4. **Invented-fact screen.** Flag any digit, date, currency or time
     expression, or any capitalised Cyrillic/Latin token not at sentence start,
     that does not appear in `allowed_entities` or the input.
  5. Latency and peak memory, measured on-device only.
- **Human review.** Every proposal flagged by the invented-fact screen is
  reviewed by a human. SC-005's "0 invented facts" is judged on the reviewed
  set: any confirmed invention fails the model.
- **Acceptance proxy.** The owner blind-grades each case's output as
  accept as-is / accept with edit / reject. Model identity is hidden and order
  is shuffled.
  - **Gate:** at least 50% accepted overall *and* in the Russian subset, plus
    0 confirmed invented facts.
  - Use the same harness for the Apple model (English cases) and the cloud
    provider to get baselines.
- **Running it.**
  - Generate on a Mac with the *same* quantized artifact as iPhone: the
    Core AI `llm-runner` CLI, or `mlx_lm` for MLX candidates.
  - Spot-check about 10 cases on a physical iPhone, because the quantization
    and runtime path differ.
  - Commit only fixtures, recorded outputs of synthetic cases, and aggregate
    scores.
  - If the owner runs the eval on real tasks, it is local only and reports
    counts only (FR-044).
- **Ongoing measurement.** In production, SC-005's 50% comes from FR-026
  records (used as-is / edited / not used), split by backend, and needs no
  proposal text.
- **Re-runs.** Re-run the eval on each Apple model version (26.4, 27.0, …) and
  on any pack update.
