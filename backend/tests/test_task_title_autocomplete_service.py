from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from app.ai.title_completion import TitleCompletionRequest
from app.modules.tasks.autocomplete import (
    CompletionUnavailable,
    InvalidCompletionRequest,
    TaskTitleAutocompleteService,
)
from app.modules.tasks.repository import TaskRepository


class Provider:
    category = "deterministic"

    def __init__(self) -> None:
        self.context: dict[str, object] = {}

    def complete(self, **kwargs: object) -> list[str]:
        self.context = kwargs
        return ["buy milk for breakfast", "buy milk today", "buy milk tomorrow"]


def _task(
    title: str, *, project_id: str | None = None, minute: int = 0
) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        project_id=project_id,
        updated_at=datetime(2026, 1, 1, 0, minute, tzinfo=UTC),
    )


def test_service_sends_only_bounded_owner_context_in_project_order() -> None:
    project = SimpleNamespace(id="p1", name="Launch", state="active")
    repo = SimpleNamespace(
        get_project_for_owner=lambda project_id, owner_id: project,
        list_for_owner=lambda owner_id: [
            _task("recent other", minute=5),
            _task("matching old", project_id="p1", minute=1),
            _task("matching new", project_id="p1", minute=3),
            _task("recent other"),
        ],
    )
    provider = Provider()

    result = TaskTitleAutocompleteService(repository=repo, provider=provider).complete(
        owner_id="owner-1",
        request=TitleCompletionRequest(draft="buy milk", project_id="p1"),
    )

    assert result.candidates == (
        "buy milk for breakfast",
        "buy milk today",
        "buy milk tomorrow",
    )
    assert provider.context == {
        "draft": "buy milk",
        "project_name": "Launch",
        "prior_titles": ["matching new", "matching old", "recent other"],
    }


def test_unscoped_context_is_recency_ordered_deduplicated_and_capped() -> None:
    tasks = [_task(f"title {index}", minute=index) for index in range(59)]
    tasks.append(_task(" TITLE 58 ", minute=0))
    repo = SimpleNamespace(list_for_owner=lambda owner_id: tasks)

    context = TaskTitleAutocompleteService(
        repository=cast(TaskRepository, repo)
    ).context(
        owner_id="owner-1",
        request=TitleCompletionRequest(draft="prepare launch notes"),
    )

    assert len(context.prior_titles) == 50
    assert context.prior_titles[:3] == ("title 58", "title 57", "title 56")
    assert len({title.casefold() for title in context.prior_titles}) == 50


def test_inactive_project_is_rejected_before_provider_use() -> None:
    project = SimpleNamespace(id="p1", name="Private project", state="archived")
    repo = SimpleNamespace(
        get_project_for_owner=lambda project_id, owner_id: project,
        list_for_owner=lambda owner_id: [],
    )
    provider = Provider()

    with pytest.raises(InvalidCompletionRequest, match="inactive"):
        TaskTitleAutocompleteService(
            repository=cast(TaskRepository, repo), provider=provider
        ).complete(
            owner_id="owner-1",
            request=TitleCompletionRequest(draft="prepare", project_id="p1"),
        )

    assert provider.context == {}


def test_invalid_provider_candidates_are_reported_as_unavailable() -> None:
    class InvalidProvider:
        category = "invalid"

        def complete(
            self, *, draft: str, project_name: str | None, prior_titles: list[str]
        ) -> list[str]:
            return [draft]

    repo = SimpleNamespace(list_for_owner=lambda owner_id: [])

    with pytest.raises(CompletionUnavailable, match="unavailable"):
        TaskTitleAutocompleteService(
            repository=cast(TaskRepository, repo), provider=InvalidProvider()
        ).complete(
            owner_id="owner-1",
            request=TitleCompletionRequest(draft="prepare launch notes"),
        )


def test_missing_provider_is_reported_as_unavailable() -> None:
    repo = SimpleNamespace(list_for_owner=lambda owner_id: [])

    with pytest.raises(CompletionUnavailable, match="unavailable"):
        TaskTitleAutocompleteService(
            repository=cast(TaskRepository, repo), provider=None
        ).complete(
            owner_id="owner-1",
            request=TitleCompletionRequest(draft="prepare launch notes"),
        )
