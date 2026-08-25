# Task title completion API contract

**Status**: Normative for `012-task-title-autocomplete`
**Base**: authenticated same-origin `/api`

## 1. Provider discovery

```http
GET /api/tasks/title-completion-provider
```

Response when the feature flag is effective:

```json
{"provider":"openai"}
```

`provider` is `null` when the configured adapter is disabled, unsupported, or lacks credentials. Discovery never receives or returns Task text. If `task_title_autocomplete` is ineffective, return `404`; unauthenticated remains `401`. The client must not render consent until a non-null provider is known, and consent copy must name that value.

V0 supports only `openai` at the fixed official OpenAI API origin. No request or deployment configuration may supply an arbitrary provider endpoint.

The backend MUST register this static route before its existing dynamic `GET /tasks/{task_id}` route; `title-completion-provider` is never interpreted as a Task ID.

## 2. Generate exactly three completions

```http
POST /api/tasks/title-completions
Content-Type: application/json
```

```json
{
  "draft": "Prepare launch",
  "project_id": "project_123",
  "consent": {
    "external_processing_allowed": true,
    "provider": "openai"
  }
}
```

Request rules:

- `draft`: trimmed length 1–500; line breaks are rejected.
- `project_id`: nullable. A supplied ID must identify the current owner's active Project; absent/other-owner is `404`, inactive is `400`.
- `consent.external_processing_allowed` must be exactly `true` for this request.
- `consent.provider` must exactly match current provider discovery. Consent is request-scoped and is not persisted.
- Without Project context, the trimmed draft must contain at least three non-blank Unicode-whitespace-delimited words. With a valid Project, at least one such word is required.
- The effective flag, authentication, consent, provider capability, threshold, and owner rate limit are checked before any remote call.

Success:

```http
200 OK
```

```json
{
  "request_id": "8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e",
  "candidates": [
    "Prepare launch readiness checklist",
    "Prepare launch stakeholder update",
    "Prepare launch rollback notes"
  ]
}
```

Candidate invariants (all server-enforced):

1. `candidates` contains exactly three strings.
2. Each candidate is trimmed, one line, 1–500 characters, and distinct after NFKC + whitespace collapse + casefold.
3. Each candidate is a complete title whose normalized text starts with the normalized draft and adds at least one non-blank character; the provider may complete but not rewrite the user's prefix.
4. No candidate contains a completed Smart Add `#tag` or `@project` token under `contracts/smart-add.md`; generated text cannot silently introduce classification on later submit.
5. The response contains no Project, history, prompt, score, provider raw body, or persisted identifier other than the random completion `request_id`.
6. Fewer than three valid candidates is an invalid provider response, not a partially rendered list.

Context assembly (server only):

- current draft;
- selected owner's active Project `id` and display name when supplied;
- at most 50 distinct prior Task titles belonging to the current owner, ordered with titles assigned to the selected Project first and then by `updated_at` descending;
- all lifecycle states may contribute; no details, tags, comments, subtasks, due dates, priorities, account attributes, tree content, or other owners' records may contribute.

The assembled prompt and result are ephemeral. They are not cached, persisted, exported, or logged.

## 3. Best-effort acceptance observation

```http
POST /api/tasks/title-completions/accepted
Content-Type: application/json
```

```json
{"request_id":"8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e","rank":2}
```

The authenticated, flag-effective endpoint validates UUID `request_id` and `rank` in `1..3`, emits one content-free experiment event, and returns `204`. It receives no candidate or draft. Failure is ignored by the composer and can never block acceptance, submit a form, or write a Task. This is operational experiment evidence, not a domain record or authorization input.

## 4. Errors and availability

- `400`: consent false/provider mismatch, below threshold, inactive Project, or semantically invalid draft.
- `401`: unauthenticated.
- `404`: ineffective flag or absent/other-owner Project.
- `429`: owner exceeded 20 generation requests in a rolling 60 seconds; include `Retry-After`.
- `422`: malformed request.
- `503`: provider disabled/missing credentials, timeout, transport failure, malformed provider payload, or fewer than three valid candidates.

Every response keeps the existing error envelope and `X-Correlation-ID`. Errors must be actionable but must not echo draft, Project name, prior title, prompt, candidate, or content-derived hash. Provider calls time out after 3 seconds and are not retried. The browser preserves the draft and ordinary submit for every error.

## 5. Client concurrency contract

- Wait 350 ms after the latest eligible draft or Project change.
- Keep at most one current generation request. Abort it when draft, Project, consent, flag, provider, Smart Add ownership, or component lifetime changes.
- Associate each request with an incrementing client sequence plus the exact draft/Project snapshot. Render only the response matching the latest sequence and unchanged snapshot; all stale or late responses are discarded.
- Clear old candidates immediately when a new eligible edit begins; never show candidates for a previous draft while loading.
- HTTP abort is best effort once an upstream provider request has begun; the 3-second no-retry server bound limits residual work.
