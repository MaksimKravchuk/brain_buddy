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
  task_notes:       string?   (after `reduce_notes`, below; `notes_truncated = true` when anything was dropped — owner decision NC-3, FR-019)
  stall_reason:     unclear | too_big | missing_info | waiting_on_someone | no_energy | no_longer_matters | null
  project_name:     string?   (null for a task without a project)
  open_task_titles: [string]  (≤ 20, other open tasks in the same project, excluding this task, most recently updated first)
```

`kind` is request metadata (which suggestion is asked for), listed in FR-019.
**Device-only routing input** (never part of the request body, never sent to a cloud
provider): `language` — the BCP-47 dominant language of title + notes (else
project name), detected on device with `NLLanguageRecognizer`; Apple's model and the
downloaded model receive it as the locale pin of §3. The web does not detect a
language; the cloud prompt says to answer in the language of the task text.

**One shared reduction** (owner decision NC-3, FR-019 "exactly the same reduced input"):
`reduce_notes(notes) -> (notes', truncated)` is one deterministic function implemented
in Core (`NavigatorInputBuilder`), in `navigatorInput.ts` and in `navigator.py`
(backstop), covered by the shared vector file
`backend/tests/fixtures/navigator/reduce_notes_vectors.json`, run by pytest and by
byte-identical copies in `NavigatorValidatorTests` and Vitest.
With `NOTES_BUDGET_CHARS = 6 000` (a constant, not per model): if the notes have at
most that many characters (Unicode scalars) they are unchanged; otherwise the first
lines up to 2 000 characters and the most recent (last) lines up to 4 000 characters
are kept, whole lines only, joined by one line `…`, and `truncated = true`. Lines
are split on U+000A, and a preceding U+000D is dropped, so the joining separator is
exactly U+000A U+2026 U+000A (3 scalars) and comes on top of the budget, so a reduced note
is at most 6 003 scalars, and that is the request limit for `task.notes` (http §7,
`NAVIGATOR_NOTES_MAX_CHARS`). If the kept first and last lines are all the lines,
nothing is dropped: the lines are rejoined with U+000A (so the U+000D are gone) and
`truncated = false`. Notes that already contain a `…` line get no special case, so
client-reduced notes of 6 001–6 003 scalars come back from the server's backstop as
the same text, usually with `truncated = true`. The server reports only what its
backstop dropped, so a client ORs the response's `notes_truncated` with its own
reduction's `truncated` before showing the hint. Title,
stall reason, project name and sibling titles are never dropped. The budget is chosen so
the reduced input, with instructions and siblings, fits the smallest supported window
(Apple's 4,096 tokens on iOS 26.x, `research-on-device-model.md` §1) at the
conservative 3 characters per token; every model, on-device or cloud, receives exactly
this reduced input. Token measurement (`tokenCount(for:)` on iOS 26.4+, 3 characters per
token on the server against `BRAIN_BUDDY_REVIEW_NAVIGATOR_MAX_INPUT_TOKENS`) is a
**guard only**: if the reduced input still does not fit (for example very long
sibling titles in a dense script), the model is not called and the person sees the
"input too large" copy (http §7). When `notes_truncated` is set, the UI shows "Part
of the notes was not considered." (design M-05 / M-07 / D-02 "notes shortened").

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

Post-validation, rules 1–4 identical on device and server (`NavigatorOutputValidator`
in Core; `validate_navigator_output` in `backend/app/modules/tasks/navigator.py`);
rule 5 runs on every client after them:

1. Trim; drop empty, multi-line, > 200 chars, or containing Smart Add tokens (`#`,
   `@`-prefixed tag syntax, `!` priority markers) the task parser would interpret.
2. Drop any proposal whose `formulation_key` equals the current title's or any
   `open_task_titles` entry's (FR-019 no duplicates), and duplicates among themselves.
3. Grounding check (FR-021): drop a proposal containing a **capitalised token
   (other than the first word), number, currency amount or date expression** that does
   not occur in the input fields. Matching is the same on every platform:
   - **Tokens**: the text is split on whitespace, meaning the characters for which
     Python's `str.isspace()` is true (Unicode White_Space plus U+001C–U+001F).
     Implementations code this set explicitly, because platform defaults differ (JS
     `\s` and Swift's `isWhitespace` omit U+001C–U+001F).
   - **Triggers**: a token is a trigger when its first alphabetic character is
     upper-case and it is not the first token, when it contains a decimal digit
     (Unicode Nd) or a currency symbol (Sc), or when its `formulation_key` is a date
     word. `formulation_key` uses full Unicode case folding (`str.casefold()`, so "ß"
     becomes "ss"), not simple lowercasing (formulation-clock §1).
   - **Finding a term**: the term is the trigger's `formulation_key`. It must occur as
     whole words in the `formulation_key` of one single input field (the title, the
     notes, the project name or one sibling title): ` term ` within ` field `. A part
     of a word does not count ("Ann" is not in "Anna").
   - **Date words**: the normative table is `date_words` in `validator_vectors.json`.
     A key is a date word when it equals an English word or a Russian form there, or
     when the whole key starts with a Russian stem. A hyphenated "в-марте" has the key
     "в марте", which does not start with a stem, so it is not a date word. That covers month and weekday names in every
     inflection, plus `tonight`, `tomorrow`, `завтра` and `послезавтра`. English `may`
     is not in the table because it is the common verb; a capitalised "May" after the
     first token is already a trigger. The forms of `среда` stay date words although
     they also mean "environment": dropping such a proposal is the safe side of a
     backstop, and a task about an environment usually names it in its input, which
     grounds it.
   - **Phrases**: `next week`, `next month`, `this weekend` and `на следующей неделе`
     are terms when they occur as whole words in the `formulation_key` of the whole
     text. Each must occur whole in one input field.
   - **Durations are exempt**: a duration of at most 30 minutes is not a trigger,
     because the prompt asks for actions that "would take under 30 minutes" and for "a
     2-minute starter step" (§3). The bound is inclusive on purpose. The minute words
     are `min`, `mins`, `minute`, `minutes`, `мин` and any word starting `минут`. A
     duration is either:
     - a token whose key is exactly an ASCII-digit number of at most 30 and one minute
       word ("2-minute", "10-минутный"); or
     - a token whose key is exactly such a number, immediately followed by a token
       whose key's first word is a minute word ("10 minutes", "5 мин", "2 минуты").
       The two tokens are exempt together.

     Digits are tested after the NFKC step of `formulation_key`, so a fullwidth "２"
     counts and an Arabic-Indic "٢" does not. "2minute" and "5мин" are one word, so
     they are not exempt.
   - **"today"**: `today` and `сегодня` are not date words. They are also exempt from
     the capital-letter trigger, because the prompt asks for actions that "could be
     started today" (§3), so the exemption only changes the result for a capitalised
     "Today" or "Сегодня" after the first token.

   This is a cheap deterministic backstop; the prompt is the primary control and
   SC-005 is measured on the evaluation set (§5). Rules 1–4 share the vector file
   `backend/tests/fixtures/navigator/validator_vectors.json`.
4. If ≥ 1 proposal survives → return them (M-05 "partial failure": fewer than 3 shown,
   no message). If none survive and the model returned a clarifying question that
   passes rule 3 → return the question. Otherwise → `malformed` (M-05 error,
   M-07 malformed). For `kind: project_next_action` a clarifying question is allowed
   too; its answer field is the next action itself (FR-021, design M-08 "model
   question"): confirming creates that task, nothing is appended anywhere and the
   navigator does not run again.
5. **Client-side completion of "no duplicates"** (FR-019): the request carries at most
   20 sibling titles, so after rules 1–4 every client drops any proposal whose
   `formulation_key` equals that of **any** open task of the project it holds — iOS
   from the local store (`NavigatorProposalFilter`, Core), the web from the project's
   open tasks it already loads with `GET /tasks?project_id=…` to build the input
   (all pages, not only the 20 sent). If that leaves none, the client shows the
   M-05 / M-07 "No useful suggestion this time" state. Shared vector: a project with 25
   open tasks where the only proposal duplicates the 21st (not sent) title → filtered.

## 3. Prompt (versioned `navigator-prompt/v1`)

Instructions (system role; English for model reliability; on-device paths add the
locale pin below, the cloud path relies on the "same language" rule):

```text
You help a person get unstuck on a task they keep postponing.
Propose 1 to 3 concrete next physical actions that would take under 30 minutes
each and could be started today. Each proposal is one short imperative line.
Rules:
- Write in the same language as the task text.
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
<task_notes>…notes after reduce_notes (§1)…</task_notes>
<stall_reason>too_big</stall_reason>
<project_name>…</project_name>
<open_tasks>
- …
</open_tasks>
<kind>first_step</kind>
```

Inside a value (title, notes, project name, sibling titles), every `<` is sent as
`&lt;`, so content cannot end its own field or start another. Escaping runs after
`reduce_notes`. It does not count toward the 6 003-scalar notes limit, though it does
count in the token estimate. Shared vectors:
`backend/tests/fixtures/navigator/prompt_vectors.json`.

For `project_next_action` the instruction's first line is "Propose 1 to 3 first next
actions for this project."

**Structured output**:

- Apple Foundation Models: guided generation with a `@Generable` type in the app target
  (`#if canImport(FoundationModels)`), shape per `research-on-device-model.md` §1
  "Guided generation fit": `NavigatorReply { kind: .steps | .question;
  @Guide(.maximumCount(3)) steps: [String]; question: String? }`. Instructions begin
  "The person's locale is <id>." and "You MUST respond in <language>." (Apple's
  documented pinning phrase); §2 validation still runs because pinning is not reliable.
- Cloud (OpenAI chat completions, adapter `backend/app/ai/review_navigator.py` beside
  `backend/app/ai/title_completion.py`, injected through the `NavigatorProvider` port of
  `backend/app/modules/tasks/navigator.py`, contracts/http.md §7): JSON schema response format
  `{"proposals": string[≤3], "clarifying_question": string | null}`; `max_tokens` from
  `BRAIN_BUDDY_REVIEW_NAVIGATOR_MAX_OUTPUT_TOKENS` (default 300); temperature 0.4.
- Downloaded on-device model (PR-09, iOS/macOS 27+): the same `@Generable` reply through
  `LanguageModelSession` backed by `CoreAILanguageModel` (recommended runtime,
  `research-on-device-model.md` §3), so prompt, schema and §2 validation are shared
  with the Apple-model path.

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
| `AppleNavigatorModel` | `ios/BrainBuddy/Navigator/AppleNavigatorModel.swift` | `SystemLanguageModel.default.availability` → reasons; the detected task language must be in `supportedLanguages` (`supportsLocale` checks only the user's locale); `unsupportedLanguageOrLocale` thrown at `respond` maps to `unavailable(.unsupportedLanguage)`; app target only |
| `CloudNavigatorModel` | `ios/BrainBuddyKit/Sources/BrainBuddyAPI/NavigatorAPI.swift` | calls §7 of `contracts/http.md`; maps reasons to `NavigatorError` |
| `DownloadedNavigatorModel` | app target, later slice (PR-09) | Core AI + Qwen3-1.7B 4-bit from an Apple-hosted Background Assets pack, `#available(iOS 27, macOS 27, *)` + memory check; reports `.notDownloaded` / `.deviceNotEligible` otherwise; late slice approved by the owner (NC-2) |
| `StubNavigatorModel` | `ios/BrainBuddyKit/Sources/BrainBuddyFakeServer/` | deterministic for package tests |

`NavigatorRouter` (Core) chooses: Apple model if `available` for the language →
else the person's remembered fallback (`downloaded` if installed, `cloud` if
consent is current, the account is signed in and the server reports
`available: true`) → else return `unavailable(reason)` so M-06 shows the choice. It
never falls back silently from on-device to cloud (constitution I).

- **Route shown before the tap** (privacy advisory, campaign 1): the router resolves
  the route for the open task when the form appears, and the Suggest control carries it
  as a caption — "Suggest · on this iPhone" or "Suggest · OpenAI" (M-04, M-08, M-19) —
  so cloud egress for a given task is visible before anything is sent.
- **Interruption** (constitution async rules): backgrounding the app or dismissing the
  sheet while a suggestion runs cancels the Swift `Task` (`NavigatorError.cancelled`),
  which is shown quietly ("Suggestion stopped. Suggest again"), never as an error.
  Proposals that had already arrived are kept with the form's draft (FR-052) and shown
  again on return. A lost connection mid-request on the cloud path is a
  `providerError` with the M-07 timeout copy and Ref.

## 5. Evaluation set (SC-005)

Method and gate: `research-on-device-model.md` §4. The fixture, the deterministic
screen runner and the recorded-output format land in **PR-07** (before any cloud
exposure), not in the late PR-09. Evaluation matrix, by source and language: cloud
(RU, EN), Apple on-device (EN; RU only if Apple ever lists it), downloaded on-device
(RU, EN; PR-09). Each cell is generated manually by the owner (cloud runs spend money
and are approval-gated, never unattended or from a subagent), graded blind, and
recorded as aggregate scores only. PR-14 opens each flag stage only for the sources
whose cell has passed the gate. Fixtures:
`backend/tests/fixtures/navigator/eval_v1.json`, ~48 **synthetic** cases (24 RU, 12 EN,
12 RU/EN code-switched; every stall reason and none; ~25% where the right output is one
question; notes that name people/places/amounts vs none; 0/5/20 sibling titles), each with
`expected_kind`, `allowed_entities` and `sibling_titles`. No real user data. A
deterministic pytest runs the §2 validator and the automatic screens over recorded
outputs. A recording is scored only when it is complete for its cell. Its `eval_set`
and `prompt_version` must be the current ones (`eval_v1`, `navigator-prompt/v1`), and it
must hold exactly one output for every case of the languages it declares (`languages`;
all 48 cases when absent). A missing, duplicate or unknown case id is refused and named,
never scored. Generating outputs is manual: cloud runs spend provider money and are
approval-gated (never unattended or from a subagent); on-device runs use the same
quantized artifact on a Mac plus ~10 spot checks on an iPhone. Owner blind grading
(accept / edit / reject); gate ≥ 50 % accepted overall **and** in the Russian subset, 0
confirmed invented facts. Only fixtures, recorded synthetic outputs and aggregate scores
are committed (`specs/020-weekly-review/evidence/`).
**Real-use acceptance rate** (SC-005 first half), ids and codes only, never text:
numerator = decisions whose `navigator_request_id` names a server request and whose
`ai_use` is `as_is` or `edited`; denominator = server requests that showed at least one
proposal (`navigator_usage.shown`). Requests that ended with Stop, "None of these",
Close or another decision therefore stay in the denominator. On-device suggestions
(Apple or downloaded model) never reach the server, so they are **not** in this rate;
for them SC-005 rests on the evaluation-set gate above, and the read-out reports the
`ai_use` share of decisions without a server request id separately, labelled as an
upper bound (it has no denominator of shown proposals). The read-out test covers a
shown-then-abandoned request.

## 6. Privacy and logging

- On device: no network call; M-05 note "Suggested on this iPhone. Nothing left the device."
- Cloud: server log line `navigator outcome=%s request_id=%s owner_id=%s provider=%s
  kind=%s duration_ms=%d input_tokens=%s output_tokens=%s proposals=%d
  notes_truncated=%s` (codes and counts only, mirroring the title-completion line in
  `backend/app/api/tasks.py`).
- Provider configuration: see contracts/http.md §7 "Provider configuration" (startup
  raises when `openai` is configured without its key).
- Neither input nor output text is persisted server-side. `review_decisions` stores
  only `ai_use` and `navigator_request_id`. The suggestions endpoint takes no
  Idempotency-Key and writes no idempotency record or `task-commands/` mirror entry
  (contracts/http.md §7); its only writes are the content-free `navigator_usage`
  counters.
- The cloud provider keeps what it received under its own retention (30 days for
  OpenAI API data); account purge cannot reach that copy (data-model "Export and
  purge").
- **Other people's details** (owner decision 2026-10-06, privacy checklist CHK011):
  notes and sibling titles are sent as written; nothing is redacted, so any names or
  details of other people in them reach the cloud provider under the person's own
  consent. The consent screen (M-07, D-02) says so in one line, "Notes are sent as
  written, including any names in them.", and the privacy policy states it (PR-07).
  The line does not change the list of data sent, so it needs no new
  `consent_text_version` beyond the first.
