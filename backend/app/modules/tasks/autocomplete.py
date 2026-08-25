"""Privacy-bounded task-title completion service.

The service owns local eligibility, owner-scoped context projection, and strict
provider-result validation. It deliberately has no persistence or Task writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.ai.title_completion import (
    TitleCompletionProviderResult,
    TitleCompletionRequest,
    validate_candidates,
)
from app.modules.tasks.domain import ProjectDocument
from app.modules.tasks.repository import TaskRepository


class TitleCompletionProvider(Protocol):
    @property
    def category(self) -> str | None: ...

    def complete(
        self, *, draft: str, project_name: str | None, prior_titles: list[str]
    ) -> list[str] | TitleCompletionProviderResult: ...


@dataclass(frozen=True, slots=True)
class CompletionContext:
    draft: str
    project_id: str | None
    project_name: str | None
    prior_titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompletionResult:
    candidates: tuple[str, ...]
    provider: str
    context: CompletionContext
    input_tokens: int | None = None
    output_tokens: int | None = None


class CompletionUnavailable(RuntimeError):
    """The configured provider cannot safely produce a complete result."""


class InvalidCompletionRequest(ValueError):
    """A locally rejected semantic request that must not consume quota."""


class TaskTitleAutocompleteService:
    """Build a bounded context and ask one injected provider for three titles."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        provider: TitleCompletionProvider | None = None,
    ) -> None:
        self.repository = repository
        self.provider = provider

    def context(
        self, *, owner_id: str, request: TitleCompletionRequest
    ) -> CompletionContext:
        project: ProjectDocument | None = None
        if request.project_id:
            project = self.repository.get_project_for_owner(
                request.project_id, owner_id=owner_id
            )
            if project.state != "active":
                raise InvalidCompletionRequest("project is inactive")

        tasks = self.repository.list_for_owner(owner_id=owner_id)
        selected = request.project_id
        ordered = sorted(
            tasks,
            key=lambda task: (
                0 if selected and task.project_id == selected else 1,
                -_timestamp(task.updated_at),
            ),
        )
        seen: set[str] = set()
        titles: list[str] = []
        for task in ordered:
            title = " ".join(task.title.split())
            key = title.casefold()
            if key in seen:
                continue
            seen.add(key)
            titles.append(title)
            if len(titles) == 50:
                break
        return CompletionContext(
            draft=" ".join(request.draft.split()),
            project_id=request.project_id,
            project_name=project.name if project else None,
            prior_titles=tuple(titles),
        )

    def complete(
        self,
        *,
        owner_id: str,
        request: TitleCompletionRequest,
        provider: TitleCompletionProvider | None = None,
    ) -> CompletionResult:
        chosen = provider or self.provider
        if chosen is None or chosen.category is None:
            raise CompletionUnavailable("provider unavailable")
        context = self.context(owner_id=owner_id, request=request)
        try:
            provider_result = chosen.complete(
                draft=context.draft,
                project_name=context.project_name,
                prior_titles=list(context.prior_titles),
            )
            raw_candidates = (
                provider_result.candidates
                if isinstance(provider_result, TitleCompletionProviderResult)
                else provider_result
            )
            candidates = validate_candidates(
                context.draft,
                raw_candidates,
            )
        except (ValueError, TimeoutError, OSError) as exc:
            raise CompletionUnavailable("provider unavailable") from exc
        return CompletionResult(
            candidates=tuple(candidates),
            provider=chosen.category,
            context=context,
            input_tokens=(
                provider_result.input_tokens
                if isinstance(provider_result, TitleCompletionProviderResult)
                else None
            ),
            output_tokens=(
                provider_result.output_tokens
                if isinstance(provider_result, TitleCompletionProviderResult)
                else None
            ),
        )


def _timestamp(value: datetime) -> float:
    return value.timestamp()


__all__ = [
    "CompletionContext",
    "CompletionResult",
    "CompletionUnavailable",
    "InvalidCompletionRequest",
    "TaskTitleAutocompleteService",
    "TitleCompletionProvider",
]
