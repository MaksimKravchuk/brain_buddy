"""Spec 020: every review table is exported and purged (FR-043, data-model).

The account ZIP holds ``review/*.json`` for E2 – E8 (an ``extend`` decision's
``reason_text`` included); ``navigator_usage`` (E9) is operational and listed
under ``excluded``; account purge empties every review table for the owner and
a second purge is a no-op.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta

import allure
import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import TaskDocument

NOW = datetime(2026, 10, 9, 14, 2, tzinfo=UTC)
REASON = "Waiting for the plumber's quote"
EXPORTED = {
    "review/settings.json",
    "review/sessions.json",
    "review/decisions.json",
    "review/receipts.json",
    "review/park_acknowledgements.json",
    "review/bulk_releases.json",
    "review/navigator_consents.json",
}


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


def _seed_review_records(container: Container, owner_id: str) -> None:
    repo = container.task_repo
    task = TaskDocument(
        id="task_0000000000aa",
        owner_id=owner_id,
        title="Renovate the bathroom",
        state="next",
        order_key=0,
        created_at=NOW,
        updated_at=NOW,
        formulation_id="form_0000000000aa",
        formulation_started_at=NOW,
    )
    repo.save(task)
    repo.save_review_settings(
        rd.ReviewSettingsDocument(owner_id=owner_id, time_zone="Europe/Berlin")
    )
    repo.save_review_session(
        rd.ReviewSessionDocument(
            id="review_0000000000aa",
            owner_id=owner_id,
            mode="quick",
            entry="list",
            origin="ios",
            started_at=NOW,
            last_activity_at=NOW,
        )
    )
    repo.save_review_decision(
        rd.ReviewDecisionDocument(
            id="decision_0000000000aa",
            owner_id=owner_id,
            task_id=task.id,
            decided_at=NOW,
            type="extend",
            stall_reason="missing_info",
            reason_text=REASON,
            formulation_id=task.formulation_id,
            task_revision_before=1,
            task_revision_after=2,
            review_counts_as="extended",
        )
    )
    repo.save_review_receipt(
        rd.ReviewReceiptDocument(
            owner_id=owner_id,
            task_id=task.id,
            kind="someday",
            task_revision=2,
            reviewed_at=NOW,
            hidden_until=NOW + timedelta(days=30),
            source="keep",
            decision_id="decision_0000000000aa",
        )
    )
    repo.save_park_ack(
        rd.ReviewParkAckDocument(
            owner_id=owner_id,
            task_id=task.id,
            formulation_id="form_0000000000ab",
            parked_at=NOW,
            from_revision=3,
            source="sweep",
        )
    )
    repo.save_bulk_release(
        rd.ReviewBulkReleaseDocument(
            id="bulk_0000000000aa",
            owner_id=owner_id,
            kind="restart",
            created_at=NOW,
        )
    )
    repo.save_navigator_consent(
        rd.NavigatorConsentDocument(
            owner_id=owner_id,
            provider="openai",
            granted_at=NOW,
            consent_text_version=1,
        )
    )
    repo.save_navigator_usage(
        rd.NavigatorUsageDocument(owner_id=owner_id, day=date(2026, 10, 9), calls=2)
    )


def _review_row_counts(container: Container, owner_id: str) -> dict[str, int]:
    repo = container.task_repo
    return {
        "settings": int(repo.get_review_settings(owner_id) is not None),
        "sessions": len(repo.list_review_sessions(owner_id)),
        "decisions": len(repo.list_review_decisions(owner_id)),
        "receipts": len(repo.list_review_receipts(owner_id)),
        "park_acks": len(repo.list_park_acks(owner_id)),
        "bulk_releases": len(repo.list_bulk_releases(owner_id)),
        "navigator_consents": len(repo.list_navigator_consents(owner_id)),
        "navigator_usage": len(repo.list_navigator_usage(owner_id)),
    }


def test_020_FR_043_export_holds_every_review_table_and_excludes_usage(
    api_client: TestClient,
) -> None:
    """The ZIP carries review/*.json; navigator_usage is listed as excluded."""

    owner_id = api_client.get("/api/auth/me").json()["id"]
    _seed_review_records(_container(api_client), owner_id)

    with allure.step("Download the account export"):
        response = api_client.get("/api/account/export")
        assert response.status_code == 200, response.text
        archive = zipfile.ZipFile(io.BytesIO(response.content))

    assert set(archive.namelist()) >= EXPORTED
    decisions = json.loads(archive.read("review/decisions.json"))
    assert [d["reason_text"] for d in decisions] == [REASON]
    assert decisions[0]["stall_reason"] == "missing_info"
    settings = json.loads(archive.read("review/settings.json"))
    assert settings[0]["time_zone"] == "Europe/Berlin"
    for name in EXPORTED - {"review/settings.json", "review/decisions.json"}:
        assert len(json.loads(archive.read(name))) == 1, name
    manifest = json.loads(archive.read("export_manifest.json"))
    assert any("navigator_usage" in entry for entry in manifest["excluded"])
    assert not any("navigator_usage" in name for name in archive.namelist())


def test_020_FR_043_export_of_an_owner_without_review_rows_is_empty_lists(
    second_api_client: tuple[TestClient, TestClient],
) -> None:
    """Another owner's review rows never reach this owner's export."""

    first, second = second_api_client
    first_id = first.get("/api/auth/me").json()["id"]
    _seed_review_records(_container(first), first_id)

    archive = zipfile.ZipFile(io.BytesIO(second.get("/api/account/export").content))
    for name in EXPORTED:
        assert json.loads(archive.read(name)) == [], name


def test_020_FR_043_purge_empties_every_review_table_and_is_idempotent(
    second_api_client: tuple[TestClient, TestClient],
) -> None:
    """Purge removes the owner's review rows, keeps others, runs twice."""

    first, second = second_api_client
    container = _container(first)
    first_id = first.get("/api/auth/me").json()["id"]
    second_id = second.get("/api/auth/me").json()["id"]
    _seed_review_records(container, first_id)
    _seed_review_records(container, second_id)

    with allure.step("Purge the first account twice"):
        container.account_service.purge_account(first_id)
        container.account_service.purge_account(first_id)

    assert set(_review_row_counts(container, first_id).values()) == {0}
    assert set(_review_row_counts(container, second_id).values()) == {1}


@pytest.mark.parametrize("purge_during_exposure", [False, True])
def test_023_FR_018_review_sweep_cannot_recreate_purged_owner_metadata(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    purge_during_exposure: bool,
) -> None:
    """A stale exposure answer cannot recreate the deleted owner's review rows."""

    container = _container(api_client)
    owner_id = api_client.get("/api/auth/me").json()["id"]
    _seed_review_records(container, owner_id)
    settings = container.task_repo.get_review_settings(owner_id)
    assert settings is not None
    container.task_repo.save_review_settings(
        settings.model_copy(update={"activated_at": NOW})
    )
    container.feature_flag_service.set_mode("weekly_review", "on", operator_id=owner_id)
    exposed_for_owner = container.review_service.is_exposed

    def exposure_then_purge(candidate_owner: str) -> bool:
        exposed = exposed_for_owner(candidate_owner)
        if exposed and purge_during_exposure:
            # Reproduce the exact interleaving: exposure read, complete purge,
            # then the sweep takes the owner lock with its stale answer.
            container.account_service.purge_account(candidate_owner)
        return exposed

    monkeypatch.setattr(container.review_service, "is_exposed", exposure_then_purge)
    with allure.step("Evaluate review exposure across a completed account purge"):
        container.review_service.run_maintenance_sweep()
        if not purge_during_exposure:
            container.account_service.purge_account(owner_id)

    with allure.step("Verify neither identity nor any owned review row reappears"):
        assert container.user_repo.get_by_id(owner_id) is None
        assert set(_review_row_counts(container, owner_id).values()) == {0}
        assert owner_id not in container.task_repo.review_owner_ids()
