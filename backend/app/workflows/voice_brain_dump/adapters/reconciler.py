"""Structured text-model adapter for semantic Voice Brain Dump reconciliation.

This module deliberately contains no fixture-specific or regex extraction logic. The
provider returns a constrained operation document; this adapter validates every target
and provenance reference before materializing domain patches with server-owned IDs.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.exceptions import (
    ProviderRetryableError,
    ProviderTerminalError,
    ValidationFailure,
)
from app.workflows.voice_brain_dump.domain import ProposalPatch, ReconciledProposal
from app.workflows.voice_brain_dump.providers import (
    ReconcileResult,
    ReconcileTextRequest,
)

_DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_Operation = Literal["add", "update", "split", "merge", "remove", "supersede"]


class _OperationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: _Operation
    proposal_id: str | None = None
    title: str | None = Field(default=None, max_length=500)
    source_segment_ids: list[str] = Field(default_factory=list, max_length=100)
    predecessor_ids: list[str] = Field(default_factory=list, max_length=100)
    base_revision: int | None = Field(default=None, ge=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


class _ReconcileEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[_OperationDraft] = Field(max_length=100)


def _strict_response_schema(
    allowed_operations: list[_Operation] | None = None,
) -> dict[str, object]:
    """Return an OpenAI-strict schema with every property explicitly required."""

    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    operation_values = (
        allowed_operations
        if allowed_operations is not None
        else ["add", "update", "split", "merge", "remove", "supersede"]
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "operations": {
                "type": "array",
                "maxItems": 100,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": operation_values,
                        },
                        "proposal_id": nullable_string,
                        "title": nullable_string,
                        "source_segment_ids": {
                            "type": "array",
                            "maxItems": 100,
                            "items": {"type": "string"},
                        },
                        "predecessor_ids": {
                            "type": "array",
                            "maxItems": 100,
                            "items": {"type": "string"},
                        },
                        "base_revision": {
                            "anyOf": [
                                {"type": "integer", "minimum": 1},
                                {"type": "null"},
                            ]
                        },
                        "confidence": {
                            "anyOf": [
                                {"type": "number", "minimum": 0, "maximum": 1},
                                {"type": "null"},
                            ]
                        },
                    },
                    "required": [
                        "operation",
                        "proposal_id",
                        "title",
                        "source_segment_ids",
                        "predecessor_ids",
                        "base_revision",
                        "confidence",
                    ],
                },
            }
        },
        "required": ["operations"],
    }


Completion = Callable[[dict[str, object]], dict[str, object]]


@dataclass(slots=True)
class OpenAITextReconciler:
    """Call a current OpenAI text model using strict structured output."""

    api_key: str = field(repr=False)
    model: str = "gpt-4o"
    endpoint: str = _DEFAULT_ENDPOINT
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: Sequence[float] = (1.0, 2.0)
    max_cost_usd_per_operation: float = 0.50
    estimated_cost_usd_per_megabyte: float = 0.01
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    complete: Completion | None = None
    provider_id: str = "openai"
    requires_external_processing: bool = True

    def reconcile(self, request: ReconcileTextRequest) -> ReconcileResult:
        payload = self._payload(request)
        # Conservatively scaled by the bounded retry budget: a single logical
        # call may itself cost the provider once per internal transport
        # attempt, so the admission check and any recorded spend (success or
        # failure alike) must assume the worst case.
        estimated_cost = (
            len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) / 1_000_000
        ) * self.estimated_cost_usd_per_megabyte * (self.max_retries + 1)
        if estimated_cost > self.max_cost_usd_per_operation:
            raise ProviderTerminalError("RECONCILER_COST_LIMIT_EXCEEDED")
        try:
            raw = self.complete(payload) if self.complete is not None else self._call(payload)
            try:
                envelope = _ReconcileEnvelope.model_validate(raw)
            except ValidationError:
                raise ValidationFailure(
                    "Reconciler returned an invalid operation envelope."
                ) from None
            patches = self._materialize(request, envelope.operations)
        except (ProviderRetryableError, ProviderTerminalError, ValidationFailure) as exc:
            exc.estimated_cost_usd = estimated_cost
            raise
        return ReconcileResult(
            input_hash=hashlib.sha256(
                json.dumps(payload["messages"], sort_keys=True).encode("utf-8")
            ).hexdigest(),
            patches=patches,
            confidences={
                patch.proposal_id: draft.confidence
                for patch, draft in zip(patches, envelope.operations, strict=True)
                if draft.confidence is not None
            },
            estimated_cost_usd=estimated_cost,
        )

    def _payload(self, request: ReconcileTextRequest) -> dict[str, object]:
        transcript = [asdict(segment) for segment in request.transcript_segments]
        proposals = [
            asdict(item) if isinstance(item, ReconciledProposal) else item
            for item in request.active_proposals
        ]
        context = {
            "operation_id": request.operation_id,
            "transcript_segments": transcript,
            "proposals": proposals,
            "user_locks": request.user_locks,
            "language_hints": request.language_hints,
            "vocabulary": request.vocabulary,
        }
        allowed_operations: list[_Operation] | None = None
        no_active_proposals_instruction = ""
        if not proposals:
            allowed_operations = ["add"]
            no_active_proposals_instruction = (
                " No active proposals were supplied, so only add operations are valid."
            )
        return {
            "model": self.model,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "voice_brain_dump_reconciliation",
                    "strict": True,
                    "schema": _strict_response_schema(allowed_operations),
                },
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Convert the accurate transcript into reviewable task proposal "
                        "operations. Preserve intent, language, proper nouns, source segment "
                        "IDs, existing proposal identity, user locks, and deletions. Use only "
                        "add, update, split, merge, remove, or supersede. Never infer details, "
                        "tags, projects, priority, due dates, routes, or destructive actions. "
                        "Never invent, fabricate, or hallucinate a task whose meaning is not "
                        "actually present in the supplied transcript segments; every operation "
                        "must be grounded in and traceable to its cited source_segment_ids, and "
                        "an ambiguous or empty transcript span must not be turned into a task. "
                        "This applies to every operation shape, including update/split/merge/"
                        "supersede renames. A remove must also cite the source_segment_ids that "
                        "justify deleting the proposal; never remove an existing proposal without "
                        "transcript evidence for that removal. Do not split a single shopping "
                        "intent solely on a conjunction. New "
                        "proposal IDs are server-owned: set proposal_id to null for add/split/"
                        "merge/supersede. Existing update/remove targets must use an exact "
                        "supplied ID. Return every schema field; use null or [] when a field "
                        "does not apply."
                        + no_active_proposals_instruction
                        + " Report confidence from 0 to 1 for each proposed task operation."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                },
            ],
        }

    def _call(self, payload: dict[str, object]) -> dict[str, object]:
        response = self._post_with_retries(payload)
        try:
            body: dict[str, Any] = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderTerminalError("RECONCILER_INVALID_RESPONSE") from exc
        if not isinstance(parsed, dict):
            raise ProviderTerminalError("RECONCILER_INVALID_RESPONSE")
        return parsed

    def _post_with_retries(self, payload: dict[str, object]) -> httpx.Response:
        attempt = 0
        while True:
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds, transport=self.transport
                ) as client:
                    response = client.post(
                        self.endpoint,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise ProviderRetryableError("RECONCILER_PROVIDER_RETRYABLE") from exc
                self._backoff(attempt)
                attempt += 1
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self.max_retries:
                    raise ProviderRetryableError("RECONCILER_PROVIDER_RETRYABLE")
                self._backoff(attempt)
                attempt += 1
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderTerminalError("RECONCILER_PROVIDER_REJECTED") from exc
            return response

    def _backoff(self, attempt: int) -> None:
        if not self.retry_backoff_seconds:
            return
        index = min(attempt, len(self.retry_backoff_seconds) - 1)
        self.sleep(float(self.retry_backoff_seconds[index]))

    def _materialize(
        self, request: ReconcileTextRequest, operations: list[_OperationDraft]
    ) -> list[ProposalPatch]:
        existing = {
            item.id: item
            for item in request.active_proposals
            if isinstance(item, ReconciledProposal)
        }
        known_segments = {segment.id for segment in request.transcript_segments}
        source_text_by_id = {
            segment.id: segment.text for segment in request.transcript_segments
        }
        patches: list[ProposalPatch] = []
        allocated_ids: set[str] = set(existing)

        for index, draft in enumerate(operations):
            self._validate_draft(draft, existing, known_segments, source_text_by_id)
            proposal_id = draft.proposal_id
            if draft.operation in {"add", "split", "merge", "supersede"}:
                collision_offset = 0
                proposal_id = self._server_id(
                    request.operation_id, index + collision_offset, draft
                )
                while proposal_id in allocated_ids:
                    collision_offset += 1
                    proposal_id = self._server_id(
                        request.operation_id, index + collision_offset, draft
                    )
                allocated_ids.add(proposal_id)
            assert proposal_id is not None
            patches.append(
                ProposalPatch(
                    operation=draft.operation,
                    proposal_id=proposal_id,
                    producer="reconciler",
                    title=draft.title,
                    source_segment_ids=draft.source_segment_ids,
                    predecessor_ids=draft.predecessor_ids,
                    base_revision=draft.base_revision,
                )
            )
        return patches

    @staticmethod
    def _validate_draft(
        draft: _OperationDraft,
        existing: dict[str, ReconciledProposal],
        known_segments: set[str],
        source_text_by_id: dict[str, str],
    ) -> None:
        structural = {"add", "split", "merge", "supersede"}
        if draft.operation in structural and draft.proposal_id is not None:
            raise ValidationFailure("New reconciler proposal IDs are server-owned.")
        if draft.operation in {"update", "remove"} and draft.proposal_id not in existing:
            raise ValidationFailure("Reconciler targeted an unknown proposal ID.")
        if draft.operation == "remove":
            if draft.title is not None or draft.predecessor_ids:
                raise ValidationFailure("Remove accepts only an existing proposal target.")
            if (
                not draft.source_segment_ids
                or not set(draft.source_segment_ids) <= known_segments
            ):
                raise ValidationFailure(
                    "Reconciler used unknown transcript provenance for removal; "
                    "a destructive removal must be grounded in cited segments."
                )
            if draft.proposal_id is None:
                raise ValidationFailure("Removal requires a proposal ID.")
            target = existing[draft.proposal_id]
            source_text = " ".join(
                source_text_by_id[source_id]
                for source_id in draft.source_segment_ids
                if source_id is not None
            )
            OpenAITextReconciler._assert_semantic_support(
                target.title, source_text, destructive=True
            )
            return
        if not draft.title or not draft.title.strip():
            raise ValidationFailure("Reconciler operation requires a task title.")
        if not draft.source_segment_ids or not set(draft.source_segment_ids) <= known_segments:
            raise ValidationFailure("Reconciler used unknown transcript provenance.")
        if draft.operation == "add" and draft.predecessor_ids:
            raise ValidationFailure("Add cannot carry predecessors.")
        if draft.operation in structural and any(
            proposal.tombstoned
            and proposal.title.casefold() == draft.title.casefold()
            for proposal in existing.values()
        ):
            raise ValidationFailure(
                "Reconciler cannot restore a user-deleted proposal."
            )
        # Every operation that mints or rewrites a title (add/update/split/
        # merge/supersede) must be grounded in its cited source segments so a
        # transcript that only says "Buy milk" can never yield "Buy yacht"
        # regardless of which patch shape carries the invention.
        source_text = " ".join(
            source_text_by_id[source_id] for source_id in draft.source_segment_ids
        )
        OpenAITextReconciler._assert_semantic_support(
            draft.title,
            source_text,
            enforce_action=True,
        )
        if draft.operation == "split" and len(draft.predecessor_ids) != 1:
            raise ValidationFailure("Split requires exactly one predecessor.")
        if draft.operation == "merge" and len(draft.predecessor_ids) < 2:
            raise ValidationFailure("Merge requires at least two predecessors.")
        if draft.operation == "supersede" and len(draft.predecessor_ids) != 1:
            raise ValidationFailure("Supersede requires exactly one predecessor.")
        if draft.predecessor_ids and not set(draft.predecessor_ids) <= set(existing):
            raise ValidationFailure("Reconciler used unknown predecessor IDs.")

    _DESTRUCTIVE_SINGLE_TERMS = frozenset(
        {
            # English: explicit destructive/negating vocabulary.
            "remove",
            "removed",
            "delete",
            "deleted",
            "cancel",
            "cancelled",
            "canceled",
            "drop",
            "scrap",
            "discard",
            "unnecessary",
            "obsolete",
            "undo",
            "revert",
            "skip",
            # Russian equivalents.
            "удалить",
            "удали",
            "удалять",
            "убрать",
            "убери",
            "отменить",
            "отмени",
            "вычеркнуть",
            "стереть",
            "выкинуть",
            "отказаться",
            "ненужно",
        }
    )
    _DESTRUCTIVE_NEGATION_PAIRS = frozenset(
        {
            ("no", "longer"),
            ("not", "needed"),
            ("not", "necessary"),
            ("не", "нужно"),
            ("не", "надо"),
            ("не", "актуально"),
            ("не", "актуальна"),
            ("не", "актуален"),
            ("не", "требуется"),
        }
    )
    _TASK_REFERENCE_TERMS = frozenset(
        {"task", "tasks", "задача", "задачи", "задачу", "задачей"}
    )
    # A negation marker scopes over only the destructive term(s) it directly
    # precedes: "Do not delete Buy milk" must never authorize removing "Buy
    # milk" just because "delete" appears somewhere in the sentence. This is
    # distinct from ``_DESTRUCTIVE_NEGATION_PAIRS`` above, whose pairs (e.g.
    # "no longer", "не нужно") are themselves the destructive signal ("this
    # is obsolete"), not a negation of one.
    _NEGATION_MARKERS = frozenset(
        {
            "not",
            "never",
            "don",
            "doesn",
            "didn",
            "won",
            "isn",
            "wasn",
            "aren",
            "shouldn",
            "wouldn",
            "couldn",
            "не",
            "нет",
            "нельзя",
        }
    )

    # Grammatical/discourse prefixes only, not an action vocabulary. Unknown
    # lexical predicates remain action claims and need exact cited support.
    _ACTION_PREFIX_TERMS = frozenset(
        {
            "please",
            "kindly",
            "just",
            "do",
            "does",
            "did",
            "can",
            "could",
            "would",
            "will",
            "should",
            "must",
            "may",
            "might",
            "you",
            "i",
            "we",
            "need",
            "needs",
            "needed",
            "want",
            "wants",
            "wanted",
            "to",
            "let",
            "lets",
            "have",
            "has",
            "had",
            "t",
            "пожалуйста",
            "надо",
            "нужно",
            "нужен",
            "нужна",
            "хочу",
            "хотим",
            "можно",
            "можешь",
            "можете",
            "давай",
            "давайте",
            "я",
            "мы",
            "мне",
            "нам",
        }
    )

    # Action changes are material intent changes. The reconciler may normalize
    # only an explicitly listed equivalent, never infer that matching objects
    # make arbitrary verbs interchangeable. Action recognition itself must not
    # use a finite vocabulary: an unknown verb is still an action claim and may
    # be accepted only when the same cited clause contains that exact token.
    _ACTION_NORMALIZATION_PAIRS = frozenset({frozenset({"call", "phone"})})

    @staticmethod
    def _actions_are_equivalent(proposed: str, source: str) -> bool:
        return proposed == source or frozenset({proposed, source}) in (
            OpenAITextReconciler._ACTION_NORMALIZATION_PAIRS
        )

    @staticmethod
    def _action_predicate(tokens: list[str]) -> tuple[str | None, bool, int | None]:
        """Return the first lexical predicate, its polarity, and token index."""

        # Polarity can be preposed (``do not delete``) or postposed in natural
        # speech (``удалять не надо``, ``delete never``). Clauses are split
        # conservatively before this helper is called, so any local marker
        # governs this predicate group.
        negated = any(
            token in OpenAITextReconciler._NEGATION_MARKERS for token in tokens
        )
        for index, token in enumerate(tokens):
            if token in OpenAITextReconciler._NEGATION_MARKERS:
                continue
            if token in OpenAITextReconciler._ACTION_PREFIX_TERMS:
                continue
            return token, negated, index
        return None, negated, None

    @staticmethod
    def _has_destructive_support(source_text: str) -> bool:
        """Explicit, unnegated destructive/negating vocabulary is required.

        A removal must be justified by language that actually asks for
        something to go away (or says it is no longer needed) -- positive,
        constructive text about the same subject (e.g. "Buy milk") must
        never be read as authorization to delete an existing proposal.
        Scoped/negated destructive phrasing ("Do not delete Buy milk") must
        not launder a removal either: a nearby negation marker cancels the
        destructive term it precedes, so only an unambiguous affirmative
        destructive action counts as support.
        """

        tokens = [
            token.casefold()
            for token in re.findall(r"[^\W\d_]+", source_text, flags=re.UNICODE)
        ]
        saw_destructive_term = False
        clause_is_negated = any(
            token in OpenAITextReconciler._NEGATION_MARKERS for token in tokens
        )
        for token in tokens:
            if token not in OpenAITextReconciler._DESTRUCTIVE_SINGLE_TERMS:
                continue
            saw_destructive_term = True
            if not clause_is_negated:
                return True
        if saw_destructive_term:
            return False
        # Bare "not needed" / "не надо" may describe the item itself, but it
        # may also negate an instruction about the item ("не надо менять
        # задачу" = do not edit the task). A task-reference noun makes that
        # scope ambiguous, so it cannot authorize removal without an explicit
        # affirmative destructive term.
        if any(
            token in OpenAITextReconciler._TASK_REFERENCE_TERMS for token in tokens
        ):
            return False
        return any(
            pair in OpenAITextReconciler._DESTRUCTIVE_NEGATION_PAIRS
            for pair in zip(tokens, tokens[1:], strict=False)
        )

    @staticmethod
    def _source_clauses(text: str) -> list[str]:
        """Return conservative command clauses without recombining their targets.

        Punctuation always separates commands. A coordinating conjunction only
        separates when at least a verb/object-sized two-token phrase follows it;
        this keeps simple objects such as ``milk and bread`` together while
        separating ``schedule meeting and call dentist``. Oxford-comma spans
        are expanded only when their local shape unambiguously shares one
        predicate (``buy milk, bread, and eggs``) or one target (``split,
        merge, and remove tasks``). A multiword target is expanded only in the
        conservative shared-predicate shape documented below; ambiguous members
        remain separate command groups so predicates and targets cannot rebind.
        """

        sentences: list[str] = []
        start = 0
        for index, character in enumerate(text):
            if character in ".!?;":
                if text[start:index].strip():
                    sentences.append(text[start:index].strip())
                start = index + 1
        if text[start:].strip():
            sentences.append(text[start:].strip())

        def words(value: str) -> list[str]:
            return re.findall(r"[^\W\d_]+", value, flags=re.UNICODE)

        conjunction = re.compile(
            r"\b(?:and|then|but|и|затем|но)\b(?=\s+[^\W\d_]+\s+[^\W\d_]+)",
            flags=re.IGNORECASE | re.UNICODE,
        )

        def split_compound(value: str) -> list[str]:
            clauses: list[str] = []
            clause_start = 0
            for match in conjunction.finditer(value):
                if value[clause_start : match.start()].strip():
                    clauses.append(value[clause_start : match.start()].strip())
                clause_start = match.end()
            if value[clause_start:].strip():
                clauses.append(value[clause_start:].strip())
            return clauses

        comma_groups: list[str] = []
        for sentence in sentences:
            parts = [part.strip() for part in sentence.split(",") if part.strip()]
            if len(parts) < 3 or not re.match(
                r"^(?:and|и)\b", parts[-1], flags=re.IGNORECASE | re.UNICODE
            ):
                comma_groups.extend(parts)
                continue

            parts[-1] = re.sub(
                r"^(?:and|и)\b\s*",
                "",
                parts[-1],
                count=1,
                flags=re.IGNORECASE | re.UNICODE,
            )
            # Split an earlier independent command before expanding the local
            # Oxford list. The list in ``email team and fire Bob, Alice, and
            # Carol`` is anchored to ``fire Bob``, never to ``email team``.
            compound_prefix = split_compound(parts[0])
            if len(compound_prefix) > 1:
                parts = [compound_prefix[-1], *parts[1:]]
                comma_groups.extend(compound_prefix[:-1])
            token_groups = [words(part) for part in parts]

            # Multiword target members are accepted only when the list also
            # contains a one-word target and no multiword member carries a
            # proper-name predicate/object signal. This admits ``buy milk,
            # orange juice, and eggs`` without reopening ``fire Bob, email
            # Alice, and schedule Carol`` cross-predicate rebinding. The anchor
            # must also prove the local one-predicate shape structurally: after
            # optional prefix/negation terms, exactly one lexical target follows
            # its predicate. This proof does not depend on enumerating every
            # natural-language coordinator; an unsplit ``email team plus fire
            # Bob`` anchor therefore remains ambiguous and is preserved below.
            trailing_groups = token_groups[1:]
            anchor_tokens = [token.casefold() for token in token_groups[0]]
            anchor_action, anchor_negated, anchor_action_index = (
                OpenAITextReconciler._action_predicate(anchor_tokens)
            )
            single_predicate_anchor = (
                anchor_action_index is not None
                and len(anchor_tokens) - anchor_action_index == 2
            )
            target_list = (
                len(trailing_groups) >= 2
                and len(trailing_groups[-1]) == 1
                and all(
                    tokens
                    and (
                        len(tokens) == 1
                        or not OpenAITextReconciler._named_entities(part)
                    )
                    for part, tokens in zip(parts[1:], trailing_groups, strict=True)
                )
                and single_predicate_anchor
            )
            if target_list:
                anchor = parts[0]
                comma_groups.append(anchor)
                if anchor_action is not None:
                    synthetic_action = (
                        f"not {anchor_action}" if anchor_negated else anchor_action
                    )
                    comma_groups.extend(
                        f"{synthetic_action} {target}" for target in parts[1:]
                    )
                else:
                    comma_groups.extend(parts[1:])
                continue

            # Local action list: at least two one-token predicates followed by
            # one complete predicate-target command.
            action_start = len(parts) - 1
            while action_start > 0 and len(token_groups[action_start - 1]) == 1:
                action_start -= 1
            action_count = len(parts) - 1 - action_start
            final_tokens = [token.casefold() for token in token_groups[-1]]
            _, final_action_negated, final_action_index = (
                OpenAITextReconciler._action_predicate(final_tokens)
            )
            prefix_parts = parts[:action_start]
            action_parts = parts[action_start:-1]
            shared_negated = final_action_negated
            if prefix_parts:
                prefix_tokens = [token.casefold() for token in words(prefix_parts[-1])]
                prefix_action, prefix_negated, prefix_action_index = (
                    OpenAITextReconciler._action_predicate(prefix_tokens)
                )
                if (
                    prefix_action is not None
                    and prefix_negated
                    and prefix_action_index == len(prefix_tokens) - 1
                ):
                    action_parts = [prefix_parts[-1], *action_parts]
                    prefix_parts = prefix_parts[:-1]
                    action_count += 1
                    shared_negated = True
            if (
                action_count >= 2
                and final_action_index is not None
                and final_action_index < len(final_tokens) - 1
            ):
                shared_target = " ".join(final_tokens[final_action_index + 1 :])
                scoped_target: str | None = None
                if prefix_parts:
                    scoped = re.match(r"^(.*?):\s*([^:]+)$", prefix_parts[-1])
                    if scoped and len(words(scoped.group(2))) == 1:
                        scoped_target = scoped.group(1).strip()
                        action_parts = [scoped.group(2).strip(), *action_parts]
                        prefix_parts = prefix_parts[:-1]
                comma_groups.extend(prefix_parts)
                action_terms = [
                    action
                    for part in action_parts
                    for part_tokens in [[token.casefold() for token in words(part)]]
                    for action, _, _ in [
                        OpenAITextReconciler._action_predicate(part_tokens)
                    ]
                    if action is not None
                ]
                all_actions = [*action_terms, final_tokens[final_action_index]]
                polarity_prefix = "not " if shared_negated else ""
                comma_groups.extend(
                    f"{polarity_prefix}{action} {shared_target}"
                    for action in all_actions
                )
                if scoped_target:
                    comma_groups.extend(
                        f"{polarity_prefix}{action} {scoped_target}"
                        for action in all_actions
                    )
                continue

            # Ambiguous serial shape: fail closed by preserving each member as
            # its own command group rather than aggregating identities/actions.
            comma_groups.extend(parts)

        clauses: list[str] = []
        for sentence in comma_groups:
            clauses.extend(split_compound(sentence))
        return clauses

    @staticmethod
    def _named_entities(text: str) -> set[str]:
        """Capitalized, non-sentence-leading tokens as a proper-noun proxy.

        Works the same way across Latin and Cyrillic script without a
        language-specific name list: sentence-initial capitalization is a
        punctuation convention (every title and every transcript sentence
        starts with one), so it is excluded; a capital letter elsewhere in a
        sentence is the language-neutral signal for a concrete named target
        (a person, product, or place) rather than a generic action word.
        """

        entities: set[str] = set()
        stripped = text.strip()
        for match in re.finditer(r"[^\W\d_]+", stripped, flags=re.UNICODE):
            token = match.group()
            preceding = stripped[: match.start()].rstrip()
            is_sentence_start = not preceding or preceding[-1] in ".!?"
            if is_sentence_start:
                continue
            if token[:1].isupper() and len(token) >= 2:
                entities.add(token.casefold())
        return entities

    @staticmethod
    def _identity_anchor_terms(text: str) -> set[str]:
        """Case-insensitive, position-based concrete-object anchor.

        ``_named_entities`` only fires when the transcript happens to be
        capitalized, but real STT output -- especially Cyrillic -- is
        routinely all lowercase, which silently disables that guard. Both
        English imperative phrasing ("Schedule dentist") and Russian
        infinitive/imperative task phrasing ("позвонить Ивану", "надо
        написать Ивану") put the action word first and the concrete
        object/target after it, regardless of case. Treating every token
        after the first as an identity anchor -- with a lower length floor
        than the base grounding check so short names ("Bob") still count --
        catches an object swap even when nothing is capitalized and even
        when the swapped object is a common noun rather than a proper name.
        This augments, never replaces, the capitalization-based signal.
        """

        tokens = [
            token
            for token in re.findall(r"[^\W\d_]+", text.casefold(), flags=re.UNICODE)
            if len(token) >= 3
        ]
        _, _, action_index = OpenAITextReconciler._action_predicate(tokens)
        if action_index is None or action_index >= len(tokens) - 1:
            return set()
        return set(tokens[action_index + 1 :])

    @staticmethod
    def _assert_semantic_support(
        title: str,
        source_text: str,
        *,
        destructive: bool = False,
        enforce_action: bool = False,
    ) -> None:
        """Fail closed unless cited text carries a language-neutral identity anchor.

        The model may normalize wording (``Call`` -> ``Phone``; equivalent
        verbs in Russian/other languages) but cannot invent a different
        concrete target. We intentionally avoid a language-specific verb
        allowlist for the base grounding check: shared substantial Unicode
        terms are the inspectable evidence, and ambiguity becomes a
        conflict/user edit rather than a destructive guess.

        Sharing only a generic action word (e.g. "call"/"позвонить") is not
        enough on its own when each side also names its OWN distinct
        concrete target ("Call Bob" cited against transcript "Call Alice"):
        that is a concrete-identity mismatch, not a wording normalization,
        and must fail closed even though the generic verb overlaps. A
        destructive removal additionally requires the cited text to carry
        explicit destructive/negating language -- positive, constructive
        text about the same subject can never authorize a deletion.
        """

        def identity_terms(text: str) -> set[str]:
            return {
                token
                for token in re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
                if any(character.isalnum() for character in token)
                and (len(token) >= 4 or any(character.isdigit() for character in token))
            }

        operation = "destructive removal" if destructive else "task identity"
        title_terms = identity_terms(title)
        source_terms = identity_terms(source_text)
        if not title_terms or not source_terms or not title_terms & source_terms:
            raise ValidationFailure(
                f"unsupported {operation} is not grounded in cited transcript evidence."
            )

        title_entities = OpenAITextReconciler._named_entities(
            title
        ) | OpenAITextReconciler._identity_anchor_terms(title)
        source_entities = OpenAITextReconciler._named_entities(
            source_text
        ) | OpenAITextReconciler._identity_anchor_terms(source_text)
        if title_entities - source_entities:
            raise ValidationFailure(
                f"unsupported {operation} names a different concrete identity than "
                "the cited transcript evidence supports."
            )

        clauses = OpenAITextReconciler._source_clauses(source_text)
        title_tokens = re.findall(r"[^\W\d_]+", title.casefold(), flags=re.UNICODE)
        title_action, title_negated, _ = OpenAITextReconciler._action_predicate(
            title_tokens
        )
        clause_supports_title = []
        for clause in clauses:
            clause_entities = OpenAITextReconciler._named_entities(
                clause
            ) | OpenAITextReconciler._identity_anchor_terms(clause)
            if title_entities <= clause_entities:
                clause_supports_title.append(clause)

        action_supported = not enforce_action or destructive or any(
            title_action is not None
            and source_action is not None
            and title_negated == source_negated
            and (
                OpenAITextReconciler._actions_are_equivalent(
                    title_action, source_action
                )
                or any(
                    clause_tokens[index : index + len(title_tokens)] == title_tokens
                    for index in range(len(clause_tokens) - len(title_tokens) + 1)
                )
            )
            for clause in clause_supports_title
            for clause_tokens in [
                re.findall(r"[^\W\d_]+", clause.casefold(), flags=re.UNICODE)
            ]
            for source_action, source_negated, _ in [
                OpenAITextReconciler._action_predicate(clause_tokens)
            ]
        )
        if not clause_supports_title or not action_supported:
            raise ValidationFailure(
                f"unsupported {operation} is not grounded in one cited transcript clause."
            )

        if destructive and not any(
            OpenAITextReconciler._has_destructive_support(clause)
            for clause in clause_supports_title
        ):
            raise ValidationFailure(
                "unsupported destructive removal has no explicit destructive or "
                "negating language in the cited transcript evidence."
            )

    @staticmethod
    def _server_id(operation_id: str, index: int, draft: _OperationDraft) -> str:
        identity = json.dumps(
            {
                "operation_id": operation_id,
                "index": index,
                "operation": draft.operation,
                "title": draft.title,
                "sources": draft.source_segment_ids,
                "predecessors": draft.predecessor_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "proposal_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
