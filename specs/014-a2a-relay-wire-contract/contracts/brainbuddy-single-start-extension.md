# BrainBuddy Single-Start Extension for A2A — v1 (public specification draft)

**Identifier (URI)**: `https://github.com/MaksimKravchuk/brain_buddy/blob/main/docs/a2a-extensions/single-start/v1.md`
**Status**: Draft for feature 014; the published copy lives at the identifier path in this
repository (`docs/a2a-extensions/single-start/v1.md`) and must never move. A breaking change
gets a new URI (`…/v2.md`), per A2A `docs/topics/extensions.md`.
**Kind**: profile extension (A2A v1.0 §4.6) — it narrows `SendMessage` semantics; it adds no
methods, states, fields or parameters.

## 1. Purpose

A2A leaves `SendMessage` idempotency optional ("Agents may utilize the messageId to detect
duplicate messages", §3.3.1). A client that must never start the same work twice therefore
cannot rely on the protocol alone. This extension lets an agent **promise** that a replayed
message never creates a second task, so a client may retry an ambiguous send safely.

## 2. Declaration

An agent declares support in its Agent Card:

```json
"capabilities": {
  "extensions": [
    {
      "uri": "https://github.com/MaksimKravchuk/brain_buddy/blob/main/docs/a2a-extensions/single-start/v1.md",
      "description": "Deduplicates messages by messageId within a contextId and returns the original task on replay.",
      "required": false
    }
  ]
}
```

`required` MUST be `false` (a client unaware of the extension must be unaffected). `params`
MUST be absent or empty; this version defines none.

## 3. Activation

A client activates the extension per request with the standard header
`A2A-Extensions: <URI>` (§4.6.1, §9.2) and SHOULD also list the URI in
`Message.extensions`. An agent SHOULD echo `A2A-Extensions` in the response. An agent that
declares the extension MUST honour §4 for every request that activates it and MAY honour it
for all requests.

## 4. Required behavior (the entire contract)

1. **Dedup key**: the pair `(Message.contextId, Message.messageId)` of a `SendMessage` (or
   `SendStreamingMessage`) request. When `contextId` is absent, the key is
   `(<server-assigned contextId>, messageId)` and dedup applies only within that `contextId`.
2. **First receipt**: processed normally.
3. **Replay** — a later request whose dedup key equals one the agent has already accepted:
   the agent MUST NOT create a new task, MUST NOT deliver the message to the agent logic a
   second time, and MUST return the **original** result: the original `Task` in its
   **current** state (same `Task.id`), or, if the original answer was a direct `Message`,
   an equivalent `Message`. The reply MUST be a normal success result, not an error.
4. **Follow-up messages**: rule 3 applies equally to messages that reference an existing
   `taskId` (multi-turn replies), so a replayed reply is delivered once.
5. **Retention**: the agent MUST remember accepted dedup keys at least as long as it keeps
   the task itself retrievable through `GetTask`; once the task is gone, a replay MAY create
   a new task (the client cannot distinguish this from a first receipt and accepts the risk).
6. **Payload equality**: the agent MAY compare the replayed message body with the original
   and MAY reject a mismatching replay with `InvalidParamsError (-32602)`; it MUST NOT
   silently accept a different body under the same key as a new task.
7. **Nothing else**: no ordering, delivery, push, cancellation or state guarantees are
   implied. Clients still observe task state through `GetTask`/`ListTasks`.

## 5. Client behavior (informative, what BrainBuddy does)

BrainBuddy sets `contextId` to its own run id and `messageId` to `<run id>:start`, keeps the
byte-identical message for the run's lifetime, and, before any resend, first calls
`ListTasks(contextId)`; only when the agent reports no task does it resend. With a declaring
agent BrainBuddy activates the extension — the `A2A-Extensions` header and
`Message.extensions` — on the first `SendMessage`, on every replay of it and on every
follow-up message, so the dedup key is recorded from first receipt. BrainBuddy adopts a task
only when the task's `contextId` equals the run id it sent; when an agent's first answer
shows that it assigned its own `contextId` instead, BrainBuddy records that on the connection,
never resends automatically for it (an ambiguous send stays "Delivery unconfirmed" until the
user checks again), and says so in the connection's duplicate-risk disclosure. A declaring
agent SHOULD therefore accept the client-supplied `contextId` (A2A §3.4.1); the dedup key of
§4 is scoped to it. With a declaring agent the tier shown to the user is **Guaranteed single
start**; without it, **Best-effort single start** with a duplicate-risk disclosure.

## 6. Conformance test (normative for the "guaranteed" claim)

Given a declaring agent reachable at `<interface>`:

1. Fetch the card; assert the URI appears in `capabilities.extensions[].uri` with
   `required: false`.
2. Send `SendMessage` with `contextId = C`, `messageId = M`, one text part, header
   `A2A-Extensions: <URI>`. Record `Task.id = T` (or the Message).
3. Send the byte-identical request twice more (three sends total).
4. Assert every response is a success carrying `Task.id == T` (or an equivalent Message).
5. Assert `ListTasks {contextId: C}` returns exactly one task with id `T`.
6. If the task reached `input-required`, send a follow-up (`taskId = T`, `messageId = M2`)
   twice; assert the second answer does not create a new task and the agent's history shows
   `M2` once.

Reference harness: `backend/tests/a2a_fakes.py` (a fake declaring agent) and the SC-002
tests in `backend/tests/test_agent_relay_service.py`; the same steps are runnable by hand
with `curl` (see `quickstart.md`).

## 7. Security considerations

Dedup keys are client-chosen strings; an agent MUST scope them to the authenticated caller
so one client cannot replay into another client's `contextId` (A2A §13.1). The extension never
transports credentials or additional data.

## 8. Versioning and change control

`v1` is frozen once feature 014 lands; edits are limited to clarifications. Any behavioral
change is published as `…/single-start/v2.md` with a new URI. The identifier is a GitHub
`blob/main` URL accepted for v1 by the product owner (2026-09-03): the path
`docs/a2a-extensions/single-start/v1.md` is frozen by repository policy (never moved,
renamed or deleted; `scripts/check_spec_kit_specs.py` or a sibling gate should assert its
presence). A redirect-based permanent identifier (for example `w3id.org`) may be introduced
in a later version without changing the v1 URI; agents declaring the v1 URI stay conformant.
