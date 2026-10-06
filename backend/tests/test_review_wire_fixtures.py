"""Spec 020: the golden wire fixtures validate against the review wire schemas.

``tests/fixtures/review_wire_fixtures.json`` holds one entry per request and
response shape of contracts/http.md §2 – §7 plus the error envelope. The Swift
DTO tests and Vitest decode the byte-identical copies, so a wire change that is
not made here as well fails mechanically.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.schemas import review as review_schemas
from app.schemas.api import ErrorResponse
from app.schemas.tasks import TaskFormulationResponse, TaskParkResponse, TaskResponse

from .test_review_formulation_vectors import load_fixture

FIXTURES = load_fixture("review_wire_fixtures.json")
ENTRIES: list[dict[str, Any]] = FIXTURES["entries"]

MODELS: dict[str, type[BaseModel]] = {
    name: getattr(review_schemas, name) for name in review_schemas.__all__
}
MODELS.update(
    {
        "ErrorResponse": ErrorResponse,
        "TaskResponse": TaskResponse,
        "TaskFormulationResponse": TaskFormulationResponse,
        "TaskParkResponse": TaskParkResponse,
    }
)


def _entries(*, valid: bool) -> Any:
    selected = [entry for entry in ENTRIES if entry["valid"] is valid]
    return pytest.mark.parametrize(
        "entry", selected, ids=[entry["id"] for entry in selected]
    )


def _dump(model: BaseModel, kind: str) -> Any:
    if kind == "request":
        return model.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return model.model_dump(mode="json", by_alias=True)


@_entries(valid=True)
def test_020_FR_045_golden_wire_entry_round_trips_through_its_schema(
    entry: dict[str, Any],
) -> None:
    """Each valid entry validates and serialises back to exactly the fixture
    (020-FR-045, 020-FR-019)."""

    model = MODELS[entry["model"]].model_validate(entry["body"])
    assert _dump(model, entry["kind"]) == entry["body"]


@_entries(valid=False)
def test_020_FR_019_golden_wire_entry_is_rejected(entry: dict[str, Any]) -> None:
    """Invalid entries are refused with 422 (020-FR-019, 020-FR-045)."""

    assert entry["status"] == 422
    with pytest.raises(ValidationError):
        MODELS[entry["model"]].model_validate(entry["body"])


def test_020_FR_045_every_wire_shape_has_a_golden_entry() -> None:
    """One valid entry per request and response model, ids unique."""

    assert FIXTURES["schema"] == "brainbuddy-review-wire-fixtures/v1"
    ids = [entry["id"] for entry in ENTRIES]
    assert len(ids) == len(set(ids))
    covered = {entry["model"] for entry in ENTRIES if entry["valid"]}
    nested_only = {"TaskFormulationResponse", "TaskParkResponse"}
    assert set(MODELS) - nested_only <= covered
    assert covered <= set(MODELS)


def test_020_FR_045_error_envelope_carries_the_reference_id() -> None:
    """Every failure envelope names its correlation id as reference_id."""

    errors = [entry for entry in ENTRIES if entry["model"] == "ErrorResponse"]
    assert errors
    for entry in errors:
        assert entry["body"]["reference_id"]
        assert set(entry["body"]) == {"message", "detail", "reference_id"}


def _invalid(entry_id: str) -> dict[str, Any]:
    return next(entry for entry in ENTRIES if entry["id"] == entry_id)


@pytest.mark.parametrize(
    ("entry_id", "field"),
    [
        ("W-R01", "decision_id"),
        ("W-R02", "progress_id"),
        ("W-R03", "progress_id"),
        ("W-R04", "language"),
        ("W-R05", "navigator_request_id"),
    ],
)
def test_020_FR_019_contract_rejections_name_the_offending_field(
    entry_id: str, field: str
) -> None:
    """Free text in a client id, a progress body without progress_id and a
    language field in a navigator request are refused (020-FR-019, 020-FR-045)."""

    entry = _invalid(entry_id)
    with pytest.raises(ValidationError) as rejected:
        MODELS[entry["model"]].model_validate(entry["body"])
    locations = {
        str(part) for error in rejected.value.errors() for part in error["loc"]
    }
    assert field in locations


def test_020_FR_045_task_response_review_fields_default_to_null() -> None:
    """Until the behaviour slice, formulation and parked are always null."""

    body = next(
        entry["body"]
        for entry in ENTRIES
        if entry["model"] == "TaskResponse" and entry["body"]["formulation"] is None
    )
    trimmed = {k: v for k, v in body.items() if k not in {"formulation", "parked"}}
    task = TaskResponse.model_validate(trimmed)
    assert task.formulation is None
    assert task.parked is None


@pytest.mark.parametrize(
    "decision_type",
    ["reformulate", "first_step", "waiting", "someday", "extend"],
)
def test_020_FR_045_next_only_decisions_need_the_decided_formulation(
    decision_type: str,
) -> None:
    """A Next-only decision without formulation_id is refused (http §3)."""

    body = {
        "type": decision_type,
        "expected_revision": 3,
        "title": "Measure the wall",
        "waiting_for": "Ann",
        "reason": "Waiting for the quote",
    }
    with pytest.raises(ValidationError):
        review_schemas.DecisionRequest.model_validate(body)
    accepted = review_schemas.DecisionRequest.model_validate(
        {**body, "formulation_id": "form_0a1b2c3d4e5f"}
    )
    assert accepted.type == decision_type


@pytest.mark.parametrize(
    ("decision_type", "missing"),
    [
        ("reformulate", "title"),
        ("first_step", "title"),
        ("follow_up", "title"),
        ("return_to_next", "title"),
        ("waiting", "waiting_for"),
        ("extend", "reason"),
    ],
)
def test_020_FR_045_decision_types_require_their_fields(
    decision_type: str, missing: str
) -> None:
    """The http §3 "required fields" column is enforced as 422."""

    body: dict[str, Any] = {
        "type": decision_type,
        "expected_revision": 3,
        "formulation_id": "form_0a1b2c3d4e5f",
        "title": "Measure the wall",
        "waiting_for": "Ann",
        "reason": "Waiting for the quote",
    }
    review_schemas.DecisionRequest.model_validate(body)
    del body[missing]
    with pytest.raises(ValidationError):
        review_schemas.DecisionRequest.model_validate(body)


def test_020_FR_019_suggestion_request_shape_depends_on_kind() -> None:
    """A project next action has no task; the other kinds need one."""

    consent = {"external_processing_allowed": True, "provider": "openai"}
    project = {"name": "Flat", "open_task_titles": []}
    with pytest.raises(ValidationError):
        review_schemas.NavigatorSuggestionRequest.model_validate(
            {"kind": "first_step", "consent": consent, "project": project}
        )
    with pytest.raises(ValidationError):
        review_schemas.NavigatorSuggestionRequest.model_validate(
            {
                "kind": "project_next_action",
                "consent": consent,
                "task": {"title": "Paint", "notes": None, "stall_reason": None},
                "project": project,
            }
        )
    with pytest.raises(ValidationError):
        review_schemas.NavigatorSuggestionRequest.model_validate(
            {"kind": "project_next_action", "consent": consent}
        )


# ------------------------------------------------ review follow-ups (I-2, A-1, A-5, A-7)
def _suggestion_with_notes(notes: str) -> dict[str, Any]:
    return {
        "kind": "first_step",
        "consent": {"external_processing_allowed": True, "provider": "openai"},
        "task": {
            "title": "Renovate the bathroom",
            "notes": notes,
            "stall_reason": None,
        },
    }


def test_020_FR_019_a_fully_reduced_note_fits_the_request_limit() -> None:
    """reduce_notes keeps 2 000 + "\\n…\\n" + 4 000 scalars: 6 003 is accepted,
    one more is refused (020-FR-019)."""

    separator = review_schemas.NAVIGATOR_NOTES_SEPARATOR
    assert separator == "\n…\n"
    reduced = "h" * 2_000 + separator + "t" * 4_000
    assert len(reduced) == review_schemas.NAVIGATOR_NOTES_MAX_CHARS == 6_003
    accepted = review_schemas.NavigatorSuggestionRequest.model_validate(
        _suggestion_with_notes(reduced)
    )
    assert accepted.task is not None
    assert accepted.task.notes == reduced
    with pytest.raises(ValidationError):
        review_schemas.NavigatorSuggestionRequest.model_validate(
            _suggestion_with_notes(reduced + "t")
        )


_DECISION = {"type": "complete", "expected_revision": 4}


@pytest.mark.parametrize(
    "value", ["2026-10-09T14:05:12Z", "2026-10-09T16:05:12+02:00"], ids=["z", "offset"]
)
def test_020_FR_045_inbound_instants_accept_explicit_offsets(value: str) -> None:
    """`Z` and an explicit offset are the same instant (020-FR-045)."""

    decision = review_schemas.DecisionRequest.model_validate(
        {**_DECISION, "client_decided_at": value}
    )
    assert decision.client_decided_at is not None
    assert decision.client_decided_at.utcoffset() is not None
    assert decision.client_decided_at.timestamp() == 1_791_554_712


@pytest.mark.parametrize(
    ("model", "body"),
    [
        ("DecisionRequest", {**_DECISION, "client_decided_at": "2026-10-09T14:05:12"}),
        (
            "SessionResponse",
            {
                **next(e for e in ENTRIES if e["id"] == "W-045")["body"],
                "started_at": "2026-10-09T14:00:00",
            },
        ),
        (
            "TaskFormulationResponse",
            {
                **next(e for e in ENTRIES if e["id"] == "W-002")["body"]["formulation"],
                "ask_at": "2026-10-23T14:05:13",
            },
        ),
    ],
    ids=["decision-request", "session-response", "task-formulation"],
)
def test_020_FR_045_a_naive_instant_is_refused(
    model: str, body: dict[str, Any]
) -> None:
    """An instant without an offset is ambiguous and gets 422 (020-FR-045)."""

    with pytest.raises(ValidationError):
        MODELS[model].model_validate(body)


@pytest.mark.parametrize(
    "reason", ["", "   ", "\t\n "], ids=["empty", "spaces", "mixed"]
)
def test_020_FR_009_a_blank_extension_reason_is_refused(reason: str) -> None:
    """Keep 7 more days needs a real reason: whitespace alone is 422 (020-FR-009)."""

    body = {
        "type": "extend",
        "expected_revision": 5,
        "formulation_id": "form_0a1b2c3d4e5f",
        "reason": reason,
    }
    with pytest.raises(ValidationError):
        review_schemas.DecisionRequest.model_validate(body)


def test_020_FR_009_the_extension_reason_is_stripped_before_its_length_check() -> None:
    """Surrounding whitespace is dropped; 500 visible characters still fit."""

    body = {
        "type": "extend",
        "expected_revision": 5,
        "formulation_id": "form_0a1b2c3d4e5f",
        "reason": "  " + "q" * 500 + " \n",
    }
    decision = review_schemas.DecisionRequest.model_validate(body)
    assert decision.reason == "q" * 500
    with pytest.raises(ValidationError):
        review_schemas.DecisionRequest.model_validate({**body, "reason": "q" * 501})


def test_020_FR_051_task_api_returns_null_formulation_and_parked(
    api_client: TestClient,
) -> None:
    """A task without a clock (here in the Inbox) carries `formulation: null`
    and `parked: null` on create, GET of one task and of the list (020-FR-051,
    020-FR-045). The clock itself is covered by `test_review_clock_api.py`."""

    created = api_client.post(
        "/api/tasks",
        json={"title": "Call Bob", "state": "inbox"},
        headers={"Idempotency-Key": "review-null-fields"},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    single = api_client.get(f"/api/tasks/{task_id}")
    listed = api_client.get("/api/tasks", params={"state": "inbox"})
    assert single.status_code == 200, single.text
    assert listed.status_code == 200, listed.text
    assert single.headers["X-Correlation-ID"]
    bodies = [created.json(), single.json(), *listed.json()["items"]]
    assert task_id in {body["id"] for body in bodies[2:]}
    for body in bodies:
        assert "formulation" in body and body["formulation"] is None
        assert "parked" in body and body["parked"] is None
