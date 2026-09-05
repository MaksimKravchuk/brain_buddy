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
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.exceptions import (
    ProviderRetryableError,
    ProviderTerminalError,
    ValidationFailure,
)
from app.workflows.voice_brain_dump.domain import (
    PatchOperation,
    ProposalPatch,
    ReconciledProposal,
    normalized_title,
)
from app.workflows.voice_brain_dump.language_fidelity import title_is_language_faithful
from app.workflows.voice_brain_dump.providers import (
    ReconcileResult,
    ReconcileTextRequest,
)

_DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_Operation = Literal["add", "update", "split", "merge", "remove", "supersede"]
_STRUCTURAL_OPERATIONS: frozenset[str] = frozenset(
    {"add", "split", "merge", "supersede"}
)


class _SemanticGroundingFailure(ValidationFailure):
    """A single operation could not be grounded in the cited transcript.

    Distinguished from a plain ``ValidationFailure`` so ``_materialize`` can
    drop just the offending operation and keep its well-formed siblings: a
    grounding miss reflects one hallucinated task, whereas a protocol
    violation (server-owned IDs, unknown references, bad arity) means the
    model is malfunctioning and the whole call must fail closed.
    """


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


@dataclass(frozen=True, slots=True)
class _DuplicateOf:
    """A structural draft that restates a title this envelope already minted.

    Carries the index of the surviving patch so the duplicate's cited segments
    can be folded into it: the second utterance keeps its provenance even though
    it does not become a second card.
    """

    patch_index: int


@dataclass(slots=True)
class _MaterializedOperations:
    """Surviving patches, their originating drafts, and skipped-op reasons.

    ``patches`` and ``drafts`` stay index-aligned so confidence can be mapped
    back to each surviving operation even after ungrounded siblings are
    dropped.
    """

    patches: list[ProposalPatch]
    drafts: list[_OperationDraft]
    skipped: list[str]


@dataclass(slots=True)
class OpenAITextReconciler:
    """Call a current OpenAI text model using strict structured output."""

    api_key: str = field(repr=False)
    model: str = "gpt-4o"
    template_version: str = "brain-dump-reconciler-v3"
    """Safe, configured identifier for the system prompt in ``_payload``.

    v3 phrases every title as a GTD next action (verb first, discourse fillers
    dropped, one proposal per distinct action) and pairs that with the
    server-side filler/duplicate guards in ``_materialize``.

    Bump this whenever the system/response-schema prompt text materially
    changes, so persisted provider runs and receipts (ADR-0002 audit
    provenance) can distinguish output produced under different prompt
    versions without persisting the prompt text itself.
    """
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
            (len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) / 1_000_000)
            * self.estimated_cost_usd_per_megabyte
            * (self.max_retries + 1)
        )
        if estimated_cost > self.max_cost_usd_per_operation:
            raise ProviderTerminalError("RECONCILER_COST_LIMIT_EXCEEDED")
        try:
            raw = (
                self.complete(payload)
                if self.complete is not None
                else self._call(payload)
            )
            try:
                envelope = _ReconcileEnvelope.model_validate(raw)
            except ValidationError:
                raise ValidationFailure(
                    "Reconciler returned an invalid operation envelope."
                ) from None
            materialized = self._materialize(request, envelope.operations)
        except (
            ProviderRetryableError,
            ProviderTerminalError,
            ValidationFailure,
        ) as exc:
            exc.estimated_cost_usd = estimated_cost
            raise
        return ReconcileResult(
            input_hash=hashlib.sha256(
                json.dumps(payload["messages"], sort_keys=True).encode("utf-8")
            ).hexdigest(),
            patches=materialized.patches,
            confidences={
                patch.proposal_id: draft.confidence
                for patch, draft in zip(
                    materialized.patches, materialized.drafts, strict=True
                )
                if draft.confidence is not None
            },
            estimated_cost_usd=estimated_cost,
            skipped_operations=materialized.skipped,
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
                        "intent solely on a conjunction. Write every task title in the same "
                        "language as the transcript segment(s) it cites; never translate a title "
                        "into another language. Each transcript segment is one separately spoken "
                        "utterance: do not merge content from different segments into a single "
                        "proposal unless they explicitly describe the same single action, and do "
                        "not split one segment into multiple proposals unless it clearly "
                        "enumerates independent commands. Emit one proposal for every actionable "
                        "segment; a segment may be skipped only if it is a query/display request, "
                        "a filler or self-correction, or modifies an existing proposal. "
                        "Reminder and note phrasings (for example «напомни…», "
                        '"remind me…", «запиши…») are actionable task '
                        "creates. Phrase every title as a GTD next action: it starts with the "
                        "concrete action verb (Russian infinitive, English base form) followed "
                        "by its object, for example «Купить молоко», «Сходить в магазин», "
                        '"Call the dentist". Drop discourse fillers, hesitations and modal '
                        "scaffolding that carry no action («так», «ну», «значит», «надо», "
                        '«нужно», "so", "um", "I need to"); a fragment with no action, such as '
                        "«Так» or «Надо», is never a task. Emit each distinct action once: when "
                        "the transcript repeats or rephrases the same action and object, produce "
                        "one proposal citing every segment that states it, never a duplicate. "
                        "Keep each title concise: the core action and its "
                        "object, using the words spoken in the source. Do not append deadlines, "
                        "dates, times, contexts, tags, labels, project names, or note "
                        "text to the title unless the title would be meaningless "
                        "without them. New "
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
                    "content": json.dumps(
                        context, ensure_ascii=False, separators=(",", ":")
                    ),
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
                    raise ProviderRetryableError(
                        "RECONCILER_PROVIDER_RETRYABLE"
                    ) from exc
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
    ) -> _MaterializedOperations:
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
        drafts: list[_OperationDraft] = []
        skipped: list[str] = []
        allocated_ids: set[str] = set(existing)
        # One proposal per distinct action. ``active_titles`` follows what each
        # active proposal is titled *as this envelope unfolds* (an earlier
        # update renames it, an earlier remove or structural predecessor
        # retires it); ``minted`` pairs each title this envelope produced with
        # its patch index so a later duplicate can hand over its provenance.
        active_titles: dict[str, str] = {
            proposal_id: proposal.title
            for proposal_id, proposal in existing.items()
            if not proposal.tombstoned
        }
        minted: list[tuple[str, int]] = []

        for index, draft in enumerate(operations):
            try:
                self._validate_draft(draft, existing, known_segments, source_text_by_id)
                outcome = self._dedupe_draft(draft, active_titles, minted)
            except _SemanticGroundingFailure as exc:
                # One hallucinated/ungrounded task: drop it and keep its
                # well-formed siblings. Protocol violations are not caught here
                # and still fail the whole call below.
                skipped.append(str(exc))
                continue
            if isinstance(outcome, _DuplicateOf):
                patches[outcome.patch_index] = self._fold_duplicate(
                    patches[outcome.patch_index], draft
                )
                skipped.append(
                    "duplicate task title within one reconciliation; its cited "
                    + (
                        "segments and predecessors"
                        if draft.predecessor_ids
                        else "segments"
                    )
                    + " were folded into the surviving proposal."
                )
                continue
            draft = outcome
            proposal_id = draft.proposal_id
            if draft.operation in _STRUCTURAL_OPERATIONS:
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
            drafts.append(draft)
            if draft.operation == "remove":
                # A removal retires a title; it never claims one.
                continue
            minted_title = (
                draft.title
                if draft.title is not None
                else (existing[proposal_id].title if proposal_id in existing else None)
            )
            if minted_title is not None:
                minted.append((minted_title, len(patches) - 1))
        if not patches and skipped:
            raise ValidationFailure(
                "All reconciler operations were dropped as ungrounded: "
                + " | ".join(skipped)
            )
        return _MaterializedOperations(patches=patches, drafts=drafts, skipped=skipped)

    @staticmethod
    def _fold_duplicate(
        survivor: ProposalPatch, draft: _OperationDraft
    ) -> ProposalPatch:
        """Fold a duplicate's provenance -- and its lineage -- into the survivor.

        A duplicate ``add`` only contributes the segments it cited. A duplicate
        structural operation also names the predecessors the model meant to
        retire; dropping them with the operation would leave those proposals
        active beside the survivor, so the survivor inherits them: an ``add``
        survivor becomes the structural operation itself, and two structural
        operations converging on one title become a ``merge`` of every
        predecessor either of them named. The projection tombstones every
        predecessor a patch lists, whatever its operation.
        """

        source_segment_ids = [
            *survivor.source_segment_ids,
            *(
                segment_id
                for segment_id in draft.source_segment_ids
                if segment_id not in survivor.source_segment_ids
            ),
        ]
        predecessor_ids = [
            *survivor.predecessor_ids,
            *(
                predecessor_id
                for predecessor_id in draft.predecessor_ids
                if predecessor_id not in survivor.predecessor_ids
            ),
        ]
        operation: PatchOperation = survivor.operation
        if (
            draft.operation in _STRUCTURAL_OPERATIONS
            and predecessor_ids != survivor.predecessor_ids
        ):
            if survivor.operation == "add":
                operation = draft.operation
            elif len(predecessor_ids) >= 2:
                operation = "merge"
        return replace(
            survivor,
            operation=operation,
            source_segment_ids=source_segment_ids,
            predecessor_ids=predecessor_ids,
        )

    @staticmethod
    def _dedupe_draft(
        draft: _OperationDraft,
        active_titles: dict[str, str],
        minted: list[tuple[str, int]],
    ) -> _OperationDraft | _DuplicateOf:
        """Enforce one proposal per distinct action across the whole envelope.

        ``active_titles`` is kept current as operations are accepted, so an
        earlier rename or removal is honoured by later operations. A structural
        operation restating a title this envelope already minted is a
        ``_DuplicateOf`` the survivor (its provenance is folded in). An ``add``
        whose title an untouched active proposal already carries is not a new
        task but the model re-deriving that proposal from the accurate
        transcript: it is rewritten into an ``update`` that affirms the existing
        proposal (reconciler-touched, citing the accurate segments) instead of
        minting a twin -- or failing the whole call when it was the only
        operation. Any other collision with an active title is dropped.
        """

        if draft.operation == "remove":
            active_titles.pop(draft.proposal_id or "", None)
            return draft
        if draft.title is None:
            return draft
        equivalent = OpenAITextReconciler._titles_equivalent
        duplicate_reason = (
            "duplicate task title within one reconciliation; the same action "
            "and object is proposed only once."
        )
        if draft.operation == "update":
            if any(
                proposal_id != draft.proposal_id and equivalent(title, draft.title)
                for proposal_id, title in active_titles.items()
            ):
                raise _SemanticGroundingFailure(duplicate_reason)
            if draft.proposal_id is not None:
                active_titles[draft.proposal_id] = draft.title
            return draft
        for predecessor_id in draft.predecessor_ids:
            active_titles.pop(predecessor_id, None)
        for title, patch_index in minted:
            if equivalent(title, draft.title):
                return _DuplicateOf(patch_index)
        twin = next(
            (
                proposal_id
                for proposal_id, title in active_titles.items()
                if equivalent(title, draft.title)
            ),
            None,
        )
        if twin is None:
            return draft
        if draft.operation == "add":
            return draft.model_copy(
                update={
                    "operation": "update",
                    "proposal_id": twin,
                    "title": None,
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            )
        raise _SemanticGroundingFailure(duplicate_reason)

    @staticmethod
    def _title_content_tokens(title: str) -> list[str]:
        """The tokens of a title that carry its action and object.

        Negation markers are kept (they change meaning); modal/prefix
        scaffolding, discourse fillers and bare articles are not content.
        """

        skip = (
            OpenAITextReconciler._ACTION_PREFIX_TERMS
            | OpenAITextReconciler._DISCOURSE_FILLER_TERMS
            | {"a", "an", "the"}
        )
        return [
            token
            for token in re.findall(r"[^\W\d_]+", title.casefold(), flags=re.UNICODE)
            if token not in skip
        ]

    @staticmethod
    def _titles_equivalent(first: str, second: str) -> bool:
        """Whether two titles name the same action and object.

        Exact content tokens after dropping scaffolding, fillers, articles,
        quotes, punctuation and case -- «Купить молоко.», «купить  молоко» and
        "Call the dentist"/"Call dentist" are one task. Deliberately not
        morphology-tolerant: a wrongly merged task is lost, a wrongly kept one
        is merely a second card.
        """

        left = OpenAITextReconciler._title_content_tokens(first)
        right = OpenAITextReconciler._title_content_tokens(second)
        if left and right:
            return left == right
        return normalized_title(first) == normalized_title(second)

    @staticmethod
    def _validate_draft(
        draft: _OperationDraft,
        existing: dict[str, ReconciledProposal],
        known_segments: set[str],
        source_text_by_id: dict[str, str],
    ) -> None:
        structural = _STRUCTURAL_OPERATIONS
        if draft.operation in structural and draft.proposal_id is not None:
            raise ValidationFailure("New reconciler proposal IDs are server-owned.")
        if (
            draft.operation in {"update", "remove"}
            and draft.proposal_id not in existing
        ):
            raise ValidationFailure("Reconciler targeted an unknown proposal ID.")
        if draft.operation == "remove":
            if draft.title is not None or draft.predecessor_ids:
                raise ValidationFailure(
                    "Remove accepts only an existing proposal target."
                )
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
        if (
            not draft.source_segment_ids
            or not set(draft.source_segment_ids) <= known_segments
        ):
            raise ValidationFailure("Reconciler used unknown transcript provenance.")
        if draft.operation == "add" and draft.predecessor_ids:
            raise ValidationFailure("Add cannot carry predecessors.")
        # Protocol checks above fail the whole call; from here on a defect is
        # one hallucinated task and only that operation is dropped.
        if not OpenAITextReconciler._title_names_an_action(draft.title):
            # A discourse fragment («Так», «Надо», "so um") names no action or
            # object. It can pass token grounding because the same filler is
            # spoken in the cited utterance, so it is rejected here as its own
            # skip reason; well-formed siblings in the same envelope survive.
            raise _SemanticGroundingFailure(
                "unsupported task title carries no action or object; a discourse "
                "filler is never a task."
            )
        if draft.operation in structural and any(
            proposal.tombstoned
            and OpenAITextReconciler._titles_equivalent(proposal.title, draft.title)
            for proposal in existing.values()
        ):
            raise _SemanticGroundingFailure(
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
        # FR-006 language-faithful title invariant, a *generation* rule distinct
        # from the FR-008 grounding tolerance enforced above. Grounding proves a
        # title's meaning is supported (and tolerates morphological variation);
        # this separate check rejects a title whose ordinary spoken words were
        # translated out of the cited segment's language. It is independent of
        # grounding on purpose: a translated title can share a proper noun or a
        # normalized/loanword verb and so satisfy a grounding path, yet FR-006
        # still prohibits it. Lands in the same skip taxonomy -- one offending
        # operation dropped, its well-formed siblings kept.
        if not title_is_language_faithful(draft.title, source_text):
            raise _SemanticGroundingFailure(
                "unsupported task title was translated out of the cited "
                "transcript's language; FR-006 requires a language-faithful title."
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

    # Discourse fillers, hesitations and sequencing words that open a spoken
    # clause («Так, надо купить молоко», "so um call the dentist", «потом
    # позвонить маме»). Consulted only by ``_title_names_an_action``: a title
    # made of nothing but these (plus negation/prefix scaffolding) names no
    # action or object and is never a task. Deliberately NOT folded into
    # ``_ACTION_PREFIX_TERMS`` -- that set also decides which clause token is
    # the predicate for grounding's identity anchors, and widening it there
    # changes what grounds.
    _DISCOURSE_FILLER_TERMS = frozenset(
        {
            "so",
            "okay",
            "ok",
            "well",
            "um",
            "uh",
            "hmm",
            "yeah",
            "also",
            "then",
            "and",
            "так",
            "ну",
            "вот",
            "значит",
            "итак",
            "ладно",
            "короче",
            "ещё",
            "еще",
            "потом",
            "затем",
            "и",
            "а",
        }
    )

    # Action changes are material intent changes. The reconciler may normalize
    # only an explicitly listed equivalent, never infer that matching objects
    # make arbitrary verbs interchangeable. Action recognition itself must not
    # use a finite vocabulary: an unknown verb is still an action claim and may
    # be accepted only when the same cited clause contains that exact token.
    _ACTION_NORMALIZATION_PAIRS = frozenset({frozenset({"call", "phone"})})

    # Explicit, bilingual self-correction vocabulary. A speaker who utters one
    # of these markers is discarding what they just said and restating the
    # command ("напомни в восемь, ой, лучше в восемь тридцать"). The restated
    # tail is a legitimate source for the title, so ``_correction_clauses``
    # offers it as an additional grounding clause -- but only for constructive
    # grounding, never for the destructive-removal guard.
    _CORRECTION_SINGLE_MARKERS = frozenset(
        {
            "actually",
            "ой",
            "лучше",
            "вернее",
        }
    )
    _CORRECTION_PHRASE_MARKERS = (
        ("no", "wait"),
        ("i", "mean"),
        ("scratch", "that"),
        ("хотя", "нет"),
        ("так", "нет"),
        ("то", "есть"),
    )

    @staticmethod
    def _title_names_an_action(title: str) -> bool:
        """Whether a title carries any lexical predicate or object at all.

        Negation markers, the modal/prefix scaffolding and discourse fillers are
        not content; a title made only of those («Так», «Ну надо», "so um") has
        nothing left to bind to a spoken action and is not a task.
        """

        action, _, _ = OpenAITextReconciler._action_predicate(
            OpenAITextReconciler._title_content_tokens(title)
        )
        return action is not None

    @staticmethod
    def _tokens_equivalent(first: str, second: str) -> bool:
        """Morphology-tolerant token equality for inflected multilingual text.

        Exact match, or a shared leading stem that is both substantial (at
        least 4 characters) and dominant (at least 60% of the longer token).
        This unifies Russian imperative/infinitive and case-ending variants
        ("создай"/"создать", "перенеси"/"перенести", "задачу"/"задачи",
        "молоко"/"молока") without conflating genuinely different words that
        merely share a short prefix ("call"/"cancel", "milk"/"milkshake",
        "просмотр"/"проспект"). Short tokens (< 4 shared characters) match
        only when identical, which preserves the exact-match guarantee for
        brief proper names such as "Bob".
        """

        if first == second:
            return True
        shorter, longer = sorted((first, second), key=len)
        common = 0
        for left, right in zip(shorter, longer, strict=False):
            if left != right:
                break
            common += 1
        return common >= 4 and common * 5 >= len(longer) * 3

    @staticmethod
    def _entities_subset(subset: set[str], superset: set[str]) -> bool:
        """Every ``subset`` term has a morphology-tolerant match in ``superset``."""

        return all(
            any(
                OpenAITextReconciler._entities_equivalent(item, candidate)
                for candidate in superset
            )
            for item in subset
        )

    @staticmethod
    def _damerau_levenshtein(first: str, second: str) -> int:
        """Optimal string-alignment distance (insert/delete/substitute plus
        adjacent transposition).

        Used only by ``_entities_equivalent`` for conservative STT-garble
        tolerance on long identity tokens; never for action verbs or the base
        grounding-token comparison.
        """

        len_first, len_second = len(first), len(second)
        if not len_first:
            return len_second
        if not len_second:
            return len_first
        previous_two: list[int] = [0] * (len_second + 1)
        previous = list(range(len_second + 1))
        for i in range(1, len_first + 1):
            current = [i] + [0] * len_second
            for j in range(1, len_second + 1):
                cost = 0 if first[i - 1] == second[j - 1] else 1
                current[j] = min(
                    current[j - 1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + cost,
                )
                if (
                    i > 1
                    and j > 1
                    and first[i - 1] == second[j - 2]
                    and first[i - 2] == second[j - 1]
                ):
                    current[j] = min(current[j], previous_two[j - 2] + 1)
            previous_two, previous = previous, current
        return previous[len_second]

    @staticmethod
    def _entities_equivalent(first: str, second: str) -> bool:
        """Entity/identity-anchor equality with conservative STT-garble tolerance.

        Starts from the same morphology-tolerant equality used everywhere else,
        then additionally tolerates a small transcription garble in a *long*
        identity token ("Brianbuddy"/"grainbuddy" -> "BrainBuddy"): both sides
        at least 5 characters, edit distance at most 2 *and* at most a quarter
        of the longer token. Short names ("Bob"/"Alice", "Анне"/"Максиму") never
        qualify -- their length floor excludes them -- so one concrete target can
        never be laundered into a different one. This tolerance applies only to
        entity/anchor comparison, never to action verbs or the base token check.
        """

        if OpenAITextReconciler._tokens_equivalent(first, second):
            return True
        if len(first) < 5 or len(second) < 5:
            return False
        distance = OpenAITextReconciler._damerau_levenshtein(first, second)
        return distance <= 2 and distance * 4 <= max(len(first), len(second))

    @staticmethod
    def _fuzzy_sublist(needle: list[str], haystack: list[str]) -> bool:
        """Whether ``needle`` occurs contiguously in ``haystack`` up to inflection.

        A contiguous full-phrase match keeps the action bound to the exact
        target span it governs in the source clause, so it cannot launder a
        cross-clause rebinding even though individual tokens match loosely.
        """

        if not needle or len(needle) > len(haystack):
            return False
        for start in range(len(haystack) - len(needle) + 1):
            if all(
                OpenAITextReconciler._tokens_equivalent(want, haystack[start + offset])
                for offset, want in enumerate(needle)
            ):
                return True
        return False

    @staticmethod
    def _actions_are_equivalent(proposed: str, source: str) -> bool:
        pair = frozenset({proposed, source})
        if pair in OpenAITextReconciler._ACTION_NORMALIZATION_PAIRS:
            return True
        return OpenAITextReconciler._tokens_equivalent(proposed, source)

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
        if any(token in OpenAITextReconciler._TASK_REFERENCE_TERMS for token in tokens):
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
    def _grounding_clauses(
        fragment: str, clauses: list[str], *, require_action: bool
    ) -> list[str]:
        """Source clauses that support one title fragment, keeping bindings intact.

        A clause grounds the fragment when the fragment's concrete identity
        anchors are all present in that single clause (so a target cannot be
        pulled from a different command), and -- when the action matters --
        the clause's own predicate matches the fragment's with the same
        polarity, either as an equivalent verb or because the whole fragment
        phrase appears contiguously in the clause. Splitting a multi-clause
        title into fragments and grounding each one independently lets a
        single command that punctuation/conjunctions fragmented (``молоко и
        хлеб``, ``на пятницу, на три часа``) still ground, while a rebinding
        that borrows one clause's verb for another clause's target never
        finds a single clause carrying both.
        """

        fragment_entities = OpenAITextReconciler._named_entities(
            fragment
        ) | OpenAITextReconciler._identity_anchor_terms(fragment)
        fragment_tokens = re.findall(
            r"[^\W\d_]+", fragment.casefold(), flags=re.UNICODE
        )
        (
            fragment_action,
            fragment_negated,
            fragment_action_index,
        ) = OpenAITextReconciler._action_predicate(fragment_tokens)
        grounded: list[str] = []
        for clause in clauses:
            clause_entities = OpenAITextReconciler._named_entities(
                clause
            ) | OpenAITextReconciler._identity_anchor_terms(clause)
            if not OpenAITextReconciler._entities_subset(
                fragment_entities, clause_entities
            ):
                continue
            if not require_action:
                grounded.append(clause)
                continue
            clause_tokens = re.findall(
                r"[^\W\d_]+", clause.casefold(), flags=re.UNICODE
            )
            clause_action, clause_negated, _ = OpenAITextReconciler._action_predicate(
                clause_tokens
            )
            if (
                fragment_action is not None
                and clause_action is not None
                and fragment_negated == clause_negated
                and (
                    OpenAITextReconciler._actions_are_equivalent(
                        fragment_action, clause_action
                    )
                    or OpenAITextReconciler._fuzzy_sublist(
                        fragment_tokens, clause_tokens
                    )
                )
            ):
                grounded.append(clause)
        if grounded or not require_action:
            return grounded
        # No single clause holds every entity: this may be one command whose
        # title legitimately aggregates entities from sibling clauses of the
        # SAME cited segment ("Отложить задачу про landing page в проекте
        # BrainBuddy", "Проверить backup на завтра"). Admit it only if the
        # action stays bound to its own primary target inside one clause; the
        # sibling clauses may then contribute adjuncts, but never a competing
        # direct object, so a cross-clause rebinding still fails.
        return OpenAITextReconciler._action_bound_clauses(
            fragment_tokens,
            fragment_action,
            fragment_negated,
            fragment_action_index,
            clauses,
        )

    @staticmethod
    def _action_bound_clauses(
        fragment_tokens: list[str],
        fragment_action: str | None,
        fragment_negated: bool,
        action_index: int | None,
        clauses: list[str],
    ) -> list[str]:
        """A clause that binds the fragment's action to its own primary target.

        Returns the single clause (if any) in which the fragment's
        ``[action ... primary-target]`` head appears contiguously (up to
        inflection) with the same polarity. Requiring the action and its
        nearest concrete object to be co-located in one clause keeps a rebinding
        that recombines one clause's verb with another clause's target ("email
        team and fire Bob" -> "Fire team") from ever finding a home, while a
        genuine single command spread across comma/conjunction fragments still
        grounds. Adjunct entities beyond the primary target are bounded by the
        segment-level identity-subset check already performed by the caller.
        """

        if fragment_action is None or action_index is None:
            return []
        primary_index: int | None = None
        for offset in range(action_index + 1, len(fragment_tokens)):
            if len(fragment_tokens[offset]) >= 3:
                primary_index = offset
                break
        if primary_index is None:
            return []
        needle = fragment_tokens[action_index : primary_index + 1]
        for clause in clauses:
            clause_tokens = re.findall(
                r"[^\W\d_]+", clause.casefold(), flags=re.UNICODE
            )
            _, clause_negated, _ = OpenAITextReconciler._action_predicate(clause_tokens)
            if fragment_negated != clause_negated:
                continue
            if OpenAITextReconciler._fuzzy_sublist(needle, clause_tokens):
                return [clause]
        return []

    @staticmethod
    def _fragment_action_recognized(fragment: str, clauses: list[str]) -> bool:
        """Whether the fragment's leading verb is actually spoken in the segment.

        True when the fragment's action equals some clause's own predicate (up
        to inflection) or the whole fragment appears verbatim in a clause. A
        fragment whose head is not a spoken action is a descriptive attribute
        (a bare due-date such as "срок на вечер пятницы"), not an action claim,
        so it may ground as an adjunct; a fragment that DOES claim a spoken verb
        must keep binding that verb to its target and is never relaxed this way.
        """

        tokens = re.findall(r"[^\W\d_]+", fragment.casefold(), flags=re.UNICODE)
        action, _, _ = OpenAITextReconciler._action_predicate(tokens)
        if action is None:
            return False
        for clause in clauses:
            clause_tokens = re.findall(
                r"[^\W\d_]+", clause.casefold(), flags=re.UNICODE
            )
            clause_action, _, _ = OpenAITextReconciler._action_predicate(clause_tokens)
            if (
                clause_action is not None
                and OpenAITextReconciler._actions_are_equivalent(action, clause_action)
            ):
                return True
            if OpenAITextReconciler._fuzzy_sublist(tokens, clause_tokens):
                return True
        return False

    @staticmethod
    def _correction_clauses(source_text: str) -> list[str]:
        """Extra grounding clauses for self-corrected / false-start utterances.

        A bilingual correction marker (see ``_CORRECTION_SINGLE_MARKERS`` /
        ``_CORRECTION_PHRASE_MARKERS``) or an em/en dash marks a spoken
        self-correction: the speaker discards what they just said and restates
        the command ("Так, нет, не на сегодня -- перенеси оплату подписки на
        завтра"). The restated tail is offered as an additional clause so the
        corrected reading can ground. These variants are consulted only for
        constructive grounding; the destructive-removal guard never sees them,
        so stripping a "не на сегодня" false start can never turn a negation
        into deletion authority.
        """

        variants: list[str] = []
        for sentence in re.findall(r"[^.!?;]+", source_text):
            if not sentence.strip():
                continue
            tail = OpenAITextReconciler._corrected_tail(sentence)
            if tail is not None and tail.strip():
                variants.extend(OpenAITextReconciler._source_clauses(tail))
        return variants

    @staticmethod
    def _corrected_tail(sentence: str) -> str | None:
        """The restatement that follows the last correction cue in one sentence.

        Returns the substring after the last correction marker or em/en dash,
        or ``None`` when the sentence carries no correction cue. Only the em
        dash (--) and en dash separate a false start from its restatement; the
        ASCII hyphen is left alone so hyphenated tokens ("code-switching",
        "pull-request") are never split.
        """

        cut = -1
        for match in re.finditer(r"[—–]", sentence):
            cut = max(cut, match.end())
        words = [
            (match.group().casefold(), match.start(), match.end())
            for match in re.finditer(r"[^\W\d_]+", sentence, flags=re.UNICODE)
        ]
        for position, (word, _start, end) in enumerate(words):
            if word in OpenAITextReconciler._CORRECTION_SINGLE_MARKERS:
                cut = max(cut, end)
            for phrase in OpenAITextReconciler._CORRECTION_PHRASE_MARKERS:
                window = tuple(
                    entry[0] for entry in words[position : position + len(phrase)]
                )
                if window == phrase:
                    cut = max(cut, words[position + len(phrase) - 1][2])
        if cut < 0:
            return None
        return sentence[cut:]

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
        if (
            not title_terms
            or not source_terms
            or not any(
                OpenAITextReconciler._tokens_equivalent(title_term, source_term)
                for title_term in title_terms
                for source_term in source_terms
            )
        ):
            raise _SemanticGroundingFailure(
                f"unsupported {operation} is not grounded in cited transcript evidence."
            )

        title_entities = OpenAITextReconciler._named_entities(
            title
        ) | OpenAITextReconciler._identity_anchor_terms(title)
        source_entities = OpenAITextReconciler._named_entities(
            source_text
        ) | OpenAITextReconciler._identity_anchor_terms(source_text)
        if not OpenAITextReconciler._entities_subset(title_entities, source_entities):
            raise _SemanticGroundingFailure(
                f"unsupported {operation} names a different concrete identity than "
                "the cited transcript evidence supports."
            )

        # Ground each title fragment against a single source clause, so a
        # command that punctuation or a conjunction split still grounds while a
        # cross-clause action/target rebinding cannot. Action entailment is not
        # enforced for a destructive removal; the destructive-language check
        # below is the guard that path relies on instead.
        clauses = OpenAITextReconciler._source_clauses(source_text)
        title_fragments = OpenAITextReconciler._source_clauses(title) or [title]
        require_action = enforce_action and not destructive
        # Constructive grounding may also draw on a self-corrected restatement
        # of the utterance. These variants are withheld from the destructive
        # path (its pool stays the raw clauses), so a stripped false start can
        # never hand a removal the negation it would otherwise need.
        grounding_pool = clauses
        if not destructive:
            correction = OpenAITextReconciler._correction_clauses(source_text)
            if correction:
                grounding_pool = [*clauses, *correction]
        supporting_clauses: list[str] = []
        for index, fragment in enumerate(title_fragments):
            grounded = OpenAITextReconciler._grounding_clauses(
                fragment, grounding_pool, require_action=require_action
            )
            if (
                not grounded
                and require_action
                and index > 0
                and not OpenAITextReconciler._fragment_action_recognized(
                    fragment, grounding_pool
                )
            ):
                # A trailing, action-less adjunct of the SAME task (a bare
                # due-date/attribute like "срок на вечер пятницы"): it claims no
                # spoken verb, and every token already cleared the segment-level
                # identity check, so entity presence in one clause is enough.
                # The head fragment carries the task's action and is never
                # relaxed this way, so no invented verb can slip in here.
                grounded = OpenAITextReconciler._grounding_clauses(
                    fragment, grounding_pool, require_action=False
                )
            if not grounded:
                raise _SemanticGroundingFailure(
                    f"unsupported {operation} is not grounded in "
                    "one cited transcript clause."
                )
            supporting_clauses.extend(grounded)

        if destructive and not any(
            OpenAITextReconciler._has_destructive_support(clause)
            for clause in supporting_clauses
        ):
            raise _SemanticGroundingFailure(
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
