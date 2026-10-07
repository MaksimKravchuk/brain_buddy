"""Spec 021 PR-02: a project's desired outcome over the API."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _create(client: TestClient, key: str, **fields: Any) -> Any:
    return client.post(
        "/api/projects",
        headers={"Idempotency-Key": key},
        json={"name": f"Project {key}", **fields},
    )


def _patch(client: TestClient, project: dict[str, Any], key: str, **fields: Any) -> Any:
    return client.patch(
        f"/api/projects/{project['id']}",
        headers={"Idempotency-Key": key},
        json={"expected_revision": project["revision"], **fields},
    )


def test_021_FR_028_create_stores_the_outcome(api_client: TestClient) -> None:
    """A create with an outcome answers 201 and reads it back."""

    response = _create(api_client, "do-create", desired_outcome="Ship the garden")

    assert response.status_code == 201, response.text
    assert response.json()["desired_outcome"] == "Ship the garden"
    stored = api_client.get(f"/api/projects/{response.json()['id']}").json()
    assert stored["desired_outcome"] == "Ship the garden"
    assert _create(api_client, "do-plain").json()["desired_outcome"] is None


def test_021_FR_028_patch_omitted_keeps_null_clears_blank_clears(
    api_client: TestClient,
) -> None:
    """Omit keeps the stored value, null and blank clear it."""

    project = _create(api_client, "do-patch", desired_outcome="Keep me").json()

    renamed = _patch(api_client, project, "do-rename", name="Renamed")
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["desired_outcome"] == "Keep me"

    cleared = _patch(api_client, renamed.json(), "do-null", desired_outcome=None)
    assert cleared.json()["desired_outcome"] is None

    again = _patch(api_client, cleared.json(), "do-set", desired_outcome="  Back  ")
    assert again.json()["desired_outcome"] == "Back"

    blank = _patch(api_client, again.json(), "do-blank", desired_outcome="  \n ")
    assert blank.json()["desired_outcome"] is None


def test_021_FR_028_outcome_length_limit(api_client: TestClient) -> None:
    """1,000 characters are kept; 1,001 are rejected on create and PATCH."""

    kept = _create(api_client, "do-1000", desired_outcome="x" * 1000)
    assert kept.status_code == 201
    assert kept.json()["desired_outcome"] == "x" * 1000

    assert _create(api_client, "do-1001", desired_outcome="x" * 1001).status_code == 422
    assert (
        _patch(api_client, kept.json(), "do-1001-p", desired_outcome="x" * 1001)
    ).status_code == 422


def test_021_FR_028_patch_changing_only_the_outcome_bumps_the_revision(
    api_client: TestClient,
) -> None:
    """An outcome edit is a project edit like any other."""

    project = _create(api_client, "do-rev").json()

    response = _patch(api_client, project, "do-rev-patch", desired_outcome="New")

    assert response.status_code == 200
    assert response.json()["revision"] == project["revision"] + 1


def test_021_FR_030_no_log_record_carries_a_project_name_or_outcome(
    api_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Create, PATCH, archive, unarchive and export log neither sentinel."""

    name, outcome = "SENTINEL-NAME-7f3a", "SENTINEL-OUTCOME-91bc"
    with caplog.at_level(logging.DEBUG):
        created = api_client.post(
            "/api/projects",
            headers={"Idempotency-Key": "log-create"},
            json={"name": name, "desired_outcome": outcome},
        ).json()
        patched = _patch(
            api_client, created, "log-patch", desired_outcome=f"{outcome}-2"
        ).json()
        archived = api_client.post(
            f"/api/projects/{created['id']}/archive",
            headers={"Idempotency-Key": "log-archive"},
            json={"expected_revision": patched["revision"]},
        ).json()
        unarchived = api_client.post(
            f"/api/projects/{created['id']}/unarchive",
            headers={"Idempotency-Key": "log-unarchive"},
            json={"expected_revision": archived["revision"]},
        )
        exported = api_client.get("/api/account/export")

    assert unarchived.status_code == 200 and exported.status_code == 200
    assert caplog.records
    for record in caplog.records:
        rendered = logging.Formatter("%(message)s").format(record)
        assert "SENTINEL" not in rendered
        assert "SENTINEL" not in str(record.__dict__)
