from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.ai.title_completion import (
    DisabledTitleCompletionProvider,
    TitleCompletionProviderResult,
)
from app.container import Container
from app.core.rate_limit import title_completion_rate_limiter
from app.modules.tasks.autocomplete import (
    InvalidCompletionRequest,
    TitleCompletionProvider,
)
from app.repositories.feature_flag import FlagMode


class FailingProvider:
    category = "test-provider"

    def complete(
        self, *, draft: str, project_name: str | None, prior_titles: list[str]
    ) -> list[str]:
        del draft, project_name, prior_titles
        raise OSError("ZZPRIVATEPROVIDERBODYSENTINELZZ")


class UsageProvider:
    category = "test-provider"

    def complete(
        self, *, draft: str, project_name: str | None, prior_titles: list[str]
    ) -> TitleCompletionProviderResult:
        del project_name, prior_titles
        return TitleCompletionProviderResult(
            candidates=[f"{draft} today", f"{draft} this week", f"{draft} tomorrow"],
            input_tokens=41,
            output_tokens=17,
        )


def _enable(client: TestClient) -> Container:
    container: Container = client.app.state.container
    container.feature_flag_service.set_mode(
        "task_title_autocomplete", FlagMode.ON, operator_id="test-operator"
    )
    return container


def test_discovery_preserves_auth_then_flag_then_provider_precedence(
    anonymous_api_client: TestClient, api_client: TestClient
) -> None:
    """012-FR-001 012-FR-007: discovery is authenticated and flag-gated."""
    assert (
        anonymous_api_client.get("/api/tasks/title-completion-provider").status_code
        == 401
    )
    assert api_client.get("/api/tasks/title-completion-provider").status_code == 404

    _enable(api_client)
    response = api_client.get("/api/tasks/title-completion-provider")

    assert response.status_code == 200
    assert response.json() == {"provider": "deterministic"}
    assert response.headers["X-Correlation-ID"]


def test_generation_returns_random_request_id_and_exact_candidates(
    api_client: TestClient,
) -> None:
    """012-FR-006 012-FR-008 012-FR-011 012-SC-001 012-SC-002 012-SC-004."""
    _enable(api_client)

    response = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": "prepare launch notes",
            "project_id": None,
            "consent": {
                "external_processing_allowed": True,
                "provider": "deterministic",
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    UUID(payload["request_id"])
    assert payload["candidates"] == [
        "prepare launch notes today",
        "prepare launch notes this week",
        "prepare launch notes tomorrow",
    ]
    assert set(payload) == {"request_id", "candidates"}


def test_invalid_local_request_does_not_consume_owner_quota(
    api_client: TestClient,
) -> None:
    """012-FR-002 012-FR-010: local rejection precedes the owner quota."""
    _enable(api_client)
    title_completion_rate_limiter.reset()

    invalid = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": "two words",
            "project_id": None,
            "consent": {
                "external_processing_allowed": True,
                "provider": "deterministic",
            },
        },
    )
    assert invalid.status_code == 400

    payload = {
        "draft": "three valid words",
        "project_id": None,
        "consent": {
            "external_processing_allowed": True,
            "provider": "deterministic",
        },
    }
    for _ in range(20):
        assert (
            api_client.post("/api/tasks/title-completions", json=payload).status_code
            == 200
        )
    limited = api_client.post("/api/tasks/title-completions", json=payload)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"


def test_generation_accepts_trimmed_500_character_draft_at_schema_boundary(
    api_client: TestClient,
) -> None:
    _enable(api_client)
    draft = f" {'one two ' + ('x' * 492)} "

    response = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": draft,
            "project_id": None,
            "consent": {
                "external_processing_allowed": True,
                "provider": "deterministic",
            },
        },
    )

    assert len(draft.strip()) == 500
    assert response.status_code == 503
    assert response.json()["message"] == "Title completion unavailable"


def test_acceptance_is_flag_gated_uuid_only_and_has_no_task_write(
    api_client: TestClient,
) -> None:
    """012-FR-012 012-SC-005: acceptance is content-free and performs no write."""
    container = _enable(api_client)
    before = container.task_repo.list_for_owner(owner_id="user_test_owner")

    response = api_client.post(
        "/api/tasks/title-completions/accepted",
        json={"request_id": "8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e", "rank": 2},
    )

    assert response.status_code == 204
    remaining = container.task_repo.list_for_owner(owner_id="user_test_owner")
    assert remaining == before


def test_disabled_provider_is_discovered_as_null_and_generation_returns_503(
    api_client: TestClient,
) -> None:
    container = _enable(api_client)
    container.task_title_autocomplete_service.provider = cast(
        TitleCompletionProvider, DisabledTitleCompletionProvider()
    )

    discovery = api_client.get("/api/tasks/title-completion-provider")
    generated = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": "prepare launch notes",
            "project_id": None,
            "consent": {
                "external_processing_allowed": True,
                "provider": "openai",
            },
        },
    )

    assert discovery.status_code == 200
    assert discovery.json() == {"provider": None}
    assert generated.status_code == 503
    assert generated.json()["message"] == "Title completion unavailable"


def test_provider_failure_response_and_observation_are_content_free(
    api_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    container = _enable(api_client)
    container.task_title_autocomplete_service.provider = FailingProvider()
    caplog.clear()

    response = api_client.post(
        "/api/tasks/title-completions",
        headers={"X-Correlation-ID": "safe-correlation"},
        json={
            "draft": "ZZPRIVATEDRAFTSENTINELZZ launch notes",
            "project_id": None,
            "consent": {
                "external_processing_allowed": True,
                "provider": "test-provider",
            },
        },
    )

    assert response.status_code == 503
    assert response.headers["X-Correlation-ID"] == "safe-correlation"
    combined = response.text + caplog.text
    assert "ZZPRIVATEDRAFTSENTINELZZ" not in combined
    assert "ZZPRIVATEPROVIDERBODYSENTINELZZ" not in combined
    assert "outcome=unavailable" in caplog.text


def test_success_observation_emits_available_token_counts_without_content(
    api_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    container = _enable(api_client)
    container.task_title_autocomplete_service.provider = UsageProvider()
    caplog.clear()

    response = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": "ZZPRIVATEDRAFTSENTINELZZ launch notes",
            "project_id": None,
            "consent": {
                "external_processing_allowed": True,
                "provider": "test-provider",
            },
        },
    )

    assert response.status_code == 200
    assert "input_tokens=41" in caplog.text
    assert "output_tokens=17" in caplog.text
    assert "ZZPRIVATEDRAFTSENTINELZZ" not in caplog.text
    assert "today" not in caplog.text


def test_flag_off_hides_all_title_completion_routes(api_client: TestClient) -> None:
    discovery = api_client.get("/api/tasks/title-completion-provider")
    generation = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": "prepare launch notes",
            "project_id": None,
            "consent": {
                "external_processing_allowed": True,
                "provider": "deterministic",
            },
        },
    )
    acceptance = api_client.post(
        "/api/tasks/title-completions/accepted",
        json={"request_id": "8f3d2f73-0e55-4f47-9f9b-1a0b6c7a9c6e", "rank": 1},
    )

    assert discovery.status_code == 404
    assert generation.status_code == 404
    assert acceptance.status_code == 404


def test_acceptance_rejects_malformed_request_id(api_client: TestClient) -> None:
    _enable(api_client)

    response = api_client.post(
        "/api/tasks/title-completions/accepted",
        json={"request_id": "x" * 36, "rank": 1},
    )

    assert response.status_code == 422


def test_generation_requires_current_provider_consent(api_client: TestClient) -> None:
    _enable(api_client)

    response = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": "prepare launch notes",
            "project_id": None,
            "consent": {
                "external_processing_allowed": False,
                "provider": "deterministic",
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Valid provider consent is required"


def test_generation_rejects_an_archived_project_before_egress(
    api_client: TestClient,
) -> None:
    _enable(api_client)
    created = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "autocomplete-project-create"},
        json={"name": "Private project", "color": "#0ea5e9"},
    )
    assert created.status_code == 201
    project = created.json()
    archived = api_client.post(
        f"/api/projects/{project['id']}/archive",
        headers={"Idempotency-Key": "autocomplete-project-archive"},
        json={"expected_revision": project["revision"]},
    )
    assert archived.status_code == 200

    response = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": "prepare",
            "project_id": project["id"],
            "consent": {
                "external_processing_allowed": True,
                "provider": "deterministic",
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["message"] == "project is inactive"


def test_generation_maps_a_service_race_to_safe_bad_request(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _enable(api_client)

    def reject_after_context(**_kwargs: object) -> None:
        raise InvalidCompletionRequest("project changed")

    monkeypatch.setattr(
        container.task_title_autocomplete_service, "complete", reject_after_context
    )

    response = api_client.post(
        "/api/tasks/title-completions",
        json={
            "draft": "prepare launch notes",
            "project_id": None,
            "consent": {
                "external_processing_allowed": True,
                "provider": "deterministic",
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["message"] == "project changed"
