"""Spec 026 PR-48 (T048): the server AI adapters over the shared Rust policy.

Existing consent, invalid-response, confirmation and cancel suites stay the
protection for behaviour they already pin (``test_review_navigator``,
``test_brain_dump_consent_precedence``, ``test_brain_dump_cancel_commit_race``,
``test_brain_dump_commit_ledger``). These tests cover only what moved: the
navigator defers route and output verdicts to the shared core, and a confirmed
AgentRun proposal is typed by the core before the ordinary Task write.
"""

from __future__ import annotations

from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.exceptions import ValidationFailure
from app.modules.tasks.navigator import (
    NavigatorInput,
    NavigatorProviderResult,
    check_task_create_proposal,
    confirm_command_proposal,
    shared_policy_core,
    validate_navigator_output,
)
from app.modules.tasks.rust_adapter import RustCore
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.confirmation import confirm_native_inbox_action
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

from .conftest import FrozenClock

NAVIGATOR = "/api/review/navigator"
TASK = "task_0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
SOURCE = {"kind": "remote", "provider": "openai"}
REFORMULATE: dict[str, object] = {
    "decision_id": "decision_0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
    "type": "reformulate",
    "formulation_id": "form_0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
    "title": "Measure the bathroom wall",
    "ai_use": "as_is",
}


class RecordingCore(RustCore):
    """The real core, recording every route request and optionally overriding it."""

    def __init__(self, route: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.route_requests: list[dict[str, Any]] = []
        self._forced = route

    def ai_route(self, request: Any) -> dict[str, Any]:
        self.route_requests.append(dict(request))
        return self._forced or super().ai_route(request)


class SpyProvider:
    category = "openai"

    def __init__(self) -> None:
        self.calls = 0

    def estimate_cost_usd(self, *, input_tokens: int, output_tokens: int) -> float:
        return 0.0001

    def suggest(self, navigator_input: NavigatorInput) -> NavigatorProviderResult:
        self.calls += 1
        return NavigatorProviderResult(
            proposals=("Find the tape measure",),
            clarifying_question=None,
            input_tokens=10,
            output_tokens=5,
        )


@pytest.fixture
def navigator(api_client: TestClient, frozen_clock: FrozenClock) -> Any:
    del frozen_clock
    container = api_client.app.state.container  # type: ignore[attr-defined]
    container.feature_flag_service.set_mode(
        "weekly_review", "on", operator_id="test-operator"
    )
    service = container.navigator_service
    service.provider = SpyProvider()
    granted = api_client.post(
        f"{NAVIGATOR}/consent",
        json={"provider": "openai", "consent_text_version": 1},
        headers={"Idempotency-Key": "rust-ai-policy-grant"},
    )
    assert granted.status_code == 200, granted.text
    return api_client, service


def _suggest(client: TestClient) -> Any:
    return client.post(
        f"{NAVIGATOR}/suggestions",
        json={
            "kind": "first_step",
            "consent": {"external_processing_allowed": True, "provider": "openai"},
            "task": {
                "title": "Measure the wall",
                "notes": None,
                "stall_reason": None,
            },
        },
    )


def test_026_FR_019_the_navigator_sends_the_core_the_current_consent_facts(
    navigator: Any,
) -> None:
    """The route request carries the owner's stored grant and the echoed consent."""

    client, service = navigator
    core = RecordingCore()
    service._rust_core = core
    with allure.step("a suggestion with a current grant"):
        response = _suggest(client)
    assert response.status_code == 200, response.text
    request = core.route_requests[0]
    remote = request["remote"]
    assert remote["provider"] == "openai"
    assert remote["credentials_configured"] is True
    assert remote["echoed_consent"] == {
        "external_processing_allowed": True,
        "provider": "openai",
    }
    assert remote["consents"][0]["consent"]["revoked_at"] is None
    assert request["cancelled"] is False
    assert service.provider.calls == 1


def test_026_SC_006_a_core_denial_stops_the_request_before_any_provider_call(
    navigator: Any,
) -> None:
    """The verdict is the core's: its denial wins over a current Python-side grant."""

    client, service = navigator
    service._rust_core = RecordingCore(
        {"route": "denied", "denial": "consent_required", "reason": "consent_required"}
    )
    with allure.step("the core denies consent"):
        response = _suggest(client)
    assert response.status_code == 400
    assert response.json()["detail"] == {"reason": "navigator_consent_required"}
    assert service.provider.calls == 0


def test_026_FR_019_the_real_core_denies_a_revoked_grant_without_a_provider_call(
    navigator: Any,
) -> None:
    client, service = navigator
    revoked = client.delete(
        f"{NAVIGATOR}/consent", headers={"Idempotency-Key": "rust-ai-policy-revoke"}
    )
    assert revoked.status_code == 204
    service._rust_core = core = RecordingCore()
    with allure.step("a suggestion after the revoke"):
        response = _suggest(client)
    assert response.status_code == 400
    assert core.route_requests[0]["remote"]["consents"][0]["consent"]["revoked_at"]
    assert service.provider.calls == 0


def test_026_FR_020_the_output_rules_are_the_cores_not_a_python_copy() -> None:
    """A smart-add token is dropped and an ungrounded date forces a refusal."""

    navigator_input = NavigatorInput(
        kind="first_step",
        task_title="Write the report",
        task_notes=None,
        stall_reason=None,
        project_name=None,
        open_task_titles=(),
    )
    kept = validate_navigator_output(
        navigator_input,
        proposals=("Open the report file", "Tag it #later"),
        clarifying_question=None,
    )
    assert kept is not None
    assert kept.proposals == ("Open the report file",)
    ungrounded = validate_navigator_output(
        navigator_input, proposals=("Call Alice on 5 May",), clarifying_question=None
    )
    assert ungrounded is None


def test_026_FR_020_a_review_decision_for_another_task_is_refused() -> None:
    """2722c2b1: the decision's target must be the task the model inspected."""

    inspected = confirm_command_proposal(
        command_type="review.decide",
        target=TASK,
        payload=REFORMULATE,
        basis_entity_id=TASK,
        basis_revision="3",
        current_revision="3",
        source=SOURCE,
    )
    assert inspected.preconditions[0]["edit_revision"] == "3"
    with pytest.raises(ValidationFailure) as refused:
        confirm_command_proposal(
            command_type="review.decide",
            target="task_other",
            payload=REFORMULATE,
            basis_entity_id=TASK,
            basis_revision="3",
            current_revision="3",
            source=SOURCE,
        )
    assert refused.value.detail == {"reason": "invalid_value", "field": "target"}


def test_026_FR_020_a_proposal_cannot_complete_a_task_or_use_a_stale_basis() -> None:
    with pytest.raises(ValidationFailure) as completion:
        confirm_command_proposal(
            command_type="task.transition",
            target=TASK,
            payload={"action": "complete"},
            basis_entity_id=TASK,
            basis_revision="3",
            current_revision="3",
            source=SOURCE,
        )
    assert completion.value.detail == {"reason": "invalid_value", "field": "type"}
    with pytest.raises(ValidationFailure) as stale:
        confirm_command_proposal(
            command_type="review.decide",
            target=TASK,
            payload=REFORMULATE,
            basis_entity_id=TASK,
            basis_revision="3",
            current_revision="4",
            source=SOURCE,
        )
    assert stale.value.detail["reason"] == "revision_conflict"
    with pytest.raises(ValidationFailure) as switched:
        confirm_command_proposal(
            command_type="review.decide",
            target=TASK,
            payload=REFORMULATE,
            basis_entity_id=TASK,
            basis_revision="3",
            current_revision="3",
            source=SOURCE,
            current_source={"kind": "remote", "provider": "anthropic"},
        )
    assert switched.value.detail["reason"] == "provider_unavailable"


class _Created:
    id = "task-created"


class _SpyCreate:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> _Created:
        self.calls.append(kwargs)
        return _Created()


def test_026_FR_021_a_confirmed_action_reaches_the_ordinary_task_write_once() -> None:
    """The AgentRun proposal is typed by the core, then written through the port."""

    create = _SpyCreate()
    confirmed = confirm_native_inbox_action(
        operation_id="op-1",
        owner_id="owner-1",
        proposal_id="proposal-1",
        title="Buy milk",
        source_segment_ids=["seg-1"],
        task_port=InProcessTaskPort(create, check_task_create_proposal),
        confirmed_at=utcnow(),
    )
    assert confirmed.task_id == "task-created"
    assert [call["title"] for call in create.calls] == ["Buy milk"]
    assert create.calls[0]["idempotency_key"] == "brain_dump_action:op-1:proposal-1"


@pytest.mark.parametrize("title", ["", "x" * 501])
def test_026_FR_021_an_untypable_proposal_never_creates_a_task(title: str) -> None:
    create = _SpyCreate()
    with pytest.raises(ValidationFailure) as refused:
        confirm_native_inbox_action(
            operation_id="op-1",
            owner_id="owner-1",
            proposal_id="proposal-1",
            title=title,
            source_segment_ids=[],
            task_port=InProcessTaskPort(create, check_task_create_proposal),
            confirmed_at=utcnow(),
        )
    assert create.calls == []
    assert refused.value.detail["reason"] == "invalid_payload"


def test_026_FR_021_a_poisoned_policy_runtime_is_replaced() -> None:
    first = shared_policy_core()
    first.close()
    second = shared_policy_core()
    assert second is not first and second.is_open
    assert check_task_create_proposal("Buy milk", task_ref="ref-1").command_type == (
        "task.create"
    )


def test_026_FR_021_the_production_container_port_refuses_an_invalid_proposal(
    api_client: TestClient,
) -> None:
    """The built container wires the shared check: no Task for an untypable title."""

    container = api_client.app.state.container  # type: ignore[attr-defined]
    owner_id = api_client.get("/api/auth/me").json()["id"]
    port = container.voice_brain_dump_service.task_port
    before = container.task_repo.list_for_owner(owner_id=owner_id)
    with pytest.raises(ValidationFailure) as refused:
        port.create_native_inbox_task(
            owner_id=owner_id,
            title="",
            source_capture_ids=["brain_dump:op-1:proposal-1"],
            idempotency_key="brain_dump_action:op-1:proposal-1",
        )
    assert refused.value.detail["reason"] == "invalid_payload"
    assert container.task_repo.list_for_owner(owner_id=owner_id) == before
