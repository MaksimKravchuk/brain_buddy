"""Structured text-model adapter for semantic Voice Brain Dump reconciliation.

This module deliberately contains no fixture-specific or regex extraction logic. The
provider returns a constrained operation document; this adapter validates every target
and provenance reference before materializing domain patches with server-owned IDs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
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


class _ReconcileEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[_OperationDraft] = Field(max_length=100)


def _strict_response_schema() -> dict[str, object]:
    """Return an OpenAI-strict schema with every property explicitly required."""

    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
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
                            "enum": [
                                "add",
                                "update",
                                "split",
                                "merge",
                                "remove",
                                "supersede",
                            ],
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
                    },
                    "required": [
                        "operation",
                        "proposal_id",
                        "title",
                        "source_segment_ids",
                        "predecessor_ids",
                        "base_revision",
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

    api_key: str
    model: str = "gpt-4o"
    endpoint: str = _DEFAULT_ENDPOINT
    timeout_seconds: float = 30.0
    complete: Completion | None = None
    provider_id: str = "openai"
    requires_external_processing: bool = True

    def reconcile(self, request: ReconcileTextRequest) -> ReconcileResult:
        payload = self._payload(request)
        raw = self.complete(payload) if self.complete is not None else self._call(payload)
        try:
            envelope = _ReconcileEnvelope.model_validate(raw)
        except ValidationError as exc:
            raise ValidationFailure("Reconciler returned an invalid operation envelope.") from exc
        patches = self._materialize(request, envelope.operations)
        return ReconcileResult(
            input_hash=hashlib.sha256(
                json.dumps(payload["messages"], sort_keys=True).encode("utf-8")
            ).hexdigest(),
            patches=patches,
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
        }
        return {
            "model": self.model,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "voice_brain_dump_reconciliation",
                    "strict": True,
                    "schema": _strict_response_schema(),
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
                        "Do not split a single shopping intent solely on a conjunction. New "
                        "proposal IDs are server-owned: set proposal_id to null for add/split/"
                        "merge/supersede. Existing update/remove targets must use an exact "
                        "supplied ID. Return every schema field; use null or [] when a field "
                        "does not apply."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                },
            ],
        }

    def _call(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise ProviderRetryableError("RECONCILER_PROVIDER_RETRYABLE")
                response.raise_for_status()
        except ProviderRetryableError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderRetryableError("RECONCILER_PROVIDER_RETRYABLE") from exc
        except httpx.HTTPError as exc:
            raise ProviderTerminalError("RECONCILER_PROVIDER_REJECTED") from exc

        try:
            body: dict[str, Any] = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderTerminalError("RECONCILER_INVALID_RESPONSE") from exc
        if not isinstance(parsed, dict):
            raise ProviderTerminalError("RECONCILER_INVALID_RESPONSE")
        return parsed

    def _materialize(
        self, request: ReconcileTextRequest, operations: list[_OperationDraft]
    ) -> list[ProposalPatch]:
        existing = {
            item.id: item
            for item in request.active_proposals
            if isinstance(item, ReconciledProposal)
        }
        known_segments = {segment.id for segment in request.transcript_segments}
        patches: list[ProposalPatch] = []
        allocated_ids: set[str] = set(existing)

        for index, draft in enumerate(operations):
            self._validate_draft(draft, existing, known_segments)
            proposal_id = draft.proposal_id
            if draft.operation in {"add", "split", "merge", "supersede"}:
                proposal_id = self._server_id(request.operation_id, index, draft)
                while proposal_id in allocated_ids:
                    proposal_id = self._server_id(
                        request.operation_id, index + len(allocated_ids), draft
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
    ) -> None:
        structural = {"add", "split", "merge", "supersede"}
        if draft.operation in structural and draft.proposal_id is not None:
            raise ValidationFailure("New reconciler proposal IDs are server-owned.")
        if draft.operation in {"update", "remove"} and draft.proposal_id not in existing:
            raise ValidationFailure("Reconciler targeted an unknown proposal ID.")
        if draft.operation == "remove":
            if draft.title is not None or draft.source_segment_ids or draft.predecessor_ids:
                raise ValidationFailure("Remove accepts only an existing proposal target.")
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
        if draft.operation == "split" and len(draft.predecessor_ids) != 1:
            raise ValidationFailure("Split requires exactly one predecessor.")
        if draft.operation == "merge" and len(draft.predecessor_ids) < 2:
            raise ValidationFailure("Merge requires at least two predecessors.")
        if draft.operation == "supersede" and len(draft.predecessor_ids) != 1:
            raise ValidationFailure("Supersede requires exactly one predecessor.")
        if draft.predecessor_ids and not set(draft.predecessor_ids) <= set(existing):
            raise ValidationFailure("Reconciler used unknown predecessor IDs.")

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
