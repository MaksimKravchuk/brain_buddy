# Contract: AI navigator prompt, output and model protocol (020, increment 2)

**Requirements**: FR-019 – FR-026, FR-044, FR-045, SC-005 · **Design**: M-05, M-06,
M-07, M-08, M-19, D-02 · **Model choice research**: `research.md` R13 and
`research-on-device-model.md` (written separately; this contract does not depend on its
outcome).

## 1. One input type everywhere (FR-019)

```text
NavigatorInput
  kind:             first_step | reformulate | project_next_action
  task_title:       string?   (absent for project_next_action)
  task_notes:       string?   (≤ 20 000; truncated to the last 4 000 chars for the prompt, see §3)
  stall_reason:     unclear | too_big | missing_info | waiting_on_someone | no_energy | no_longer_matters | null
  project_name:     string?   (null for a task without a project)
  open_task_titles: [string]  (≤ 20, other open tasks in the same project, excluding this task, most recently updated first)
  language_hint:    BCP-47 language of task_title (else project_name), detected on device
```

Nothing else: no ids, dates, tags, due dates, other projects, account data or history.
The same value is built by `NavigatorInputBuilder` in
`ios/BrainBuddyKit/Sources/BrainBuddyCore/Navigator.swift` (iOS/macOS) and by
`frontend/src/features/review/navigatorInput.ts` (web), and is what the M-07
consent screen lists. The backend accepts exactly this set
(`NavigatorSuggestionRequest`, `extra="forbid"`) and does not enrich it.

## 2. Output

```text
NavigatorOutput = proposals: [string] (1..3)  |  clarifying_question: string
```

Post-validation, identical on device and server (`NavigatorOutputValidator` in
Core; `validate_navigator_output` in `backend/app/modules/tasks/navigator.py`):

1. Trim; drop empty, multi-line, > 200 chars, or containing Smart Add tokens (`#`,
   `@`-prefixed tag syntax, `!` priority markers) the task parser would interpret.
2. Drop any proposal whose `formulation_key` equals the current title's or any
   `open_task_titles` entry's (FR-019 no duplicates), and duplicates among themselves.
3. Grounding check (FR-021): drop a proposal containing a **capitalised token
   (other than the first word), number, currency amount or date expression** that does not occur
   (case-insensitively, after `formulation_key`) in the input fields. This is a cheap
   deterministic backstop; the prompt is the primary control and SC-005 is measured on
   the evaluation set (§5).
4. If ≥ 1 proposal survives → return them (M-05 "partial failure": fewer than 3 shown,
   no message). If none survive and the model returned a clarifying question that
   passes rule 3 → return the question. Otherwise → `malformed` (M-05 error,
   M-07 malformed).

## 3. Prompt (versioned `navigator-prompt/v1`)

Instructions (system role; English for model reliability, output language forced by
the hint):

```text
You help a person get unstuck on a task they keep postponing.
Propose 1 to 3 concrete next physical actions that would take under 30 minutes
each and could be started today. Each proposal is one short imperative line.
Rules:
- Write in the language with code {language_hint}.
- Use only facts present in the input. Never invent people, places, amounts,
  dates, brands or organisations.
- Do not repeat the current wording or any listed open task.
- If the input is too vague to propose a grounded step, ask exactly one short
  clarifying question instead of proposing.
- Stall reason guidance: unclear → a step that clarifies the outcome; too_big →
  the smallest first slice; missing_info → a step that obtains the information;
  waiting_on_someone → a step that contacts or follows up; no_energy → a
  2-minute starter step; no_longer_matters → a step that decides to drop or
  delegate it.
```

User content (data role, delimited, never interpolated into instructions):

```text
<task_title>…</task_title>
<task_notes>…last 4 000 chars…</task_notes>
<stall_reason>too_big</stall_reason>
<project_name>…</project_name>
<open_tasks>
- …
</open_tasks>
<kind>first_step</kind>
```

For `project_next_action` the instruction's first line is "Propose 1 to 3 first next
actions for this project."

**Structured output**:

- Apple Foundation Models: guided generation with a `@Generable` type
  `NavigatorGeneration { @Guide(.count(0...3)) proposals: [String];
  clarifyingQuestion: String? }` in the app target (`#if canImport(FoundationModels)`).
- Cloud (OpenAI chat completions, the same adapter style as
  `backend/app/ai/title_completion.py`): JSON schema response format
  `{"proposals": string[≤3], "clarifying_question": string | null}`; `max_tokens` from
  `BRAIN_BUDDY_REVIEW_NAVIGATOR_MAX_OUTPUT_TOKENS` (default 300); temperature 0.4.
- Downloaded on-device model: the same JSON shape, parsed and validated by §2; the
  runtime adapter is decided in `research-on-device-model.md`.

## 4. `NavigatorModel` protocol (Swift, `BrainBuddyCore`, Linux-testable)

```swift
public enum NavigatorAvailability: Sendable, Equatable {
    case available
    case unavailable(NavigatorUnavailableReason)
}
public enum NavigatorUnavailableReason: Sendable, Equatable {
    case deviceNotEligible, appleIntelligenceOff, modelNotReady,
         unsupportedLanguage(String), noAccount, offline, notDownloaded,
         consentRequired, disabled
}
public enum NavigatorSource: Sendable, Equatable { case appleOnDevice, downloadedOnDevice, cloud(provider: String) }

public protocol NavigatorModel: Sendable {
    var source: NavigatorSource { get }
    func availability(for language: String) async -> NavigatorAvailability
    func suggest(_ input: NavigatorInput) async throws(NavigatorError) -> NavigatorOutput
}
public enum NavigatorError: Error, Sendable, Equatable {
    case cancelled, timeout, malformed, providerError(referenceID: String?),
         costCap(referenceID: String?), rateLimited(referenceID: String?),
         consentRequired, unavailable(NavigatorUnavailableReason)
}
```

Implementations:

| type | location | notes |
|---|---|---|
| `AppleNavigatorModel` | `ios/BrainBuddy/Navigator/AppleNavigatorModel.swift` | `SystemLanguageModel.default.availability` → reasons; `supportsLocale(_:)` / `supportedLanguages` for the language check; app target only |
| `CloudNavigatorModel` | `ios/BrainBuddyKit/Sources/BrainBuddyAPI/NavigatorAPI.swift` | calls §7 of `contracts/http.md`; maps reasons to `NavigatorError` |
| `DownloadedNavigatorModel` | app target, later slice (PR-09) | behind the same protocol; may not ship in the first iOS navigator release |
| `StubNavigatorModel` | `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/` | deterministic for package tests |

`NavigatorRouter` (Core) chooses: Apple model if `available` for the language →
else the person's remembered fallback (`downloaded` if installed, `cloud` if
consented and signed in) → else return `unavailable(reason)` so M-06 shows the choice.
It never falls back silently from on-device to cloud (constitution I).

## 5. Evaluation set (SC-005)

`backend/tests/fixtures/navigator_eval_set.json`: ≥ 40 **synthetic** stalled tasks
(RU and EN, each stall reason, thin and rich inputs, projects with open tasks). No real
user data. A deterministic test checks the validator against recorded outputs; a manual,
approval-gated run (`/verify-live` class: spends provider money) records accept/edit
judgements and personal-fact violations in `specs/020-weekly-review/evidence/`.
The owner's real-task acceptance rate is measured from `review_decisions.ai_use`
counts (ids and codes only), never from text.

## 6. Privacy and logging

- On device: no network call; M-05 note "Suggested on this iPhone. Nothing left the device."
- Cloud: server log line `navigator outcome=%s request_id=%s owner_id=%s provider=%s
  kind=%s duration_ms=%d input_tokens=%s output_tokens=%s proposals=%d` (codes and
  counts only, mirroring the title-completion line in `backend/app/api/tasks.py`).
- Neither input nor output text is persisted server-side. `review_decisions` stores
  only `ai_use` and `navigator_request_id`.
