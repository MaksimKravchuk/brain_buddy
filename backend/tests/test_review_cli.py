"""Spec 020 (research R21): the TEST-only review CLI seams for Playwright.

``python -m app.cli review-seed-aged-task`` creates a Next task whose
formulation started N days ago for an activated owner, and
``review-run-sweep`` runs one ``_run_review_maintenance_sweep``. Both refuse to
run unless ``BRAIN_BUDDY_ENV=test``: no test-only route or command reaches a
production stack.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import allure
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app import cli
from app.container import Container
from app.core.config import AppEnvironment

from .conftest import TEST_USER_EMAIL, FrozenClock


def _wire(
    monkeypatch: pytest.MonkeyPatch, container: Container, environment: AppEnvironment
) -> None:
    monkeypatch.setattr(
        cli, "get_config", lambda: SimpleNamespace(environment=environment)
    )
    monkeypatch.setattr(cli, "build_container", lambda _config: container)


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


def test_020_FR_016_seed_creates_an_aged_next_task_for_an_activated_owner(
    api_client: TestClient, frozen_clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _container(api_client)
    _wire(monkeypatch, container, AppEnvironment.TEST)
    container.feature_flag_service.set_mode("weekly_review", "on", operator_id="t")

    with allure.step("python -m app.cli review-seed-aged-task --days 15"):
        result = CliRunner().invoke(
            cli.app,
            ["review-seed-aged-task", "--email", TEST_USER_EMAIL, "--days", "15"],
        )
    assert result.exit_code == 0, result.output
    task_id = result.stdout.strip()
    owner_id = api_client.get("/api/auth/me").json()["id"]
    task = container.task_repo.get_for_owner(task_id, owner_id=owner_id)
    assert task.state == "next"
    assert task.formulation_started_at == frozen_clock() - timedelta(days=15)
    state = api_client.get("/api/review/state").json()
    assert state["explainer_seen"] is True
    assert state["counts"]["asks_for_decision"] == 1


def test_020_FR_012_run_sweep_parks_a_seeded_due_task(
    api_client: TestClient, frozen_clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _container(api_client)
    _wire(monkeypatch, container, AppEnvironment.TEST)
    container.feature_flag_service.set_mode("weekly_review", "on", operator_id="t")
    seeded = CliRunner().invoke(
        cli.app,
        [
            "review-seed-aged-task",
            "--email",
            TEST_USER_EMAIL,
            "--days",
            "22",
            "--title",
            "Renovate the bathroom",
        ],
    )
    assert seeded.exit_code == 0, seeded.output
    result = CliRunner().invoke(cli.app, ["review-run-sweep"])
    assert result.exit_code == 0, result.output
    assert "parked=1" in result.stdout
    owner_id = api_client.get("/api/auth/me").json()["id"]
    task = container.task_repo.get_for_owner(seeded.stdout.strip(), owner_id=owner_id)
    assert task.state == "someday" and task.parked is not None


@pytest.mark.parametrize(
    "args",
    [
        ["review-seed-aged-task", "--email", TEST_USER_EMAIL, "--days", "15"],
        ["review-run-sweep"],
    ],
    ids=["seed", "sweep"],
)
@pytest.mark.parametrize(
    "environment", [AppEnvironment.DEVELOPMENT, AppEnvironment.PRODUCTION]
)
def test_020_FR_018_review_cli_refuses_to_run_outside_test(
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    environment: AppEnvironment,
) -> None:
    """No seam reaches a real stack: exit 2 and nothing is written."""

    built: list[object] = []
    monkeypatch.setattr(
        cli, "get_config", lambda: SimpleNamespace(environment=environment)
    )
    monkeypatch.setattr(cli, "build_container", lambda config: built.append(config))
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 2
    assert "BRAIN_BUDDY_ENV=test" in result.output
    assert built == []


def test_020_FR_016_seed_for_an_activated_owner_keeps_its_activation(
    api_client: TestClient, frozen_clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _container(api_client)
    _wire(monkeypatch, container, AppEnvironment.TEST)
    args = ["review-seed-aged-task", "--email", TEST_USER_EMAIL, "--days", "3"]
    assert CliRunner().invoke(cli.app, args).exit_code == 0
    owner_id = api_client.get("/api/auth/me").json()["id"]
    activated = container.review_service.settings_for(owner_id).activated_at
    frozen_clock.advance(days=1)
    assert CliRunner().invoke(cli.app, args).exit_code == 0
    assert container.review_service.settings_for(owner_id).activated_at == activated


def test_020_FR_014_run_sweep_reports_a_failure_by_type_only(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, container, AppEnvironment.TEST)

    def boom() -> None:
        raise RuntimeError("SENTINEL-CLI-TEXT")

    monkeypatch.setattr(container.review_service, "run_maintenance_sweep", boom)
    result = CliRunner().invoke(cli.app, ["review-run-sweep"])
    assert result.exit_code == 1
    assert "RuntimeError" in result.output
    assert "SENTINEL-CLI-TEXT" not in result.output


def test_020_FR_016_seed_reports_an_unknown_account(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, container, AppEnvironment.TEST)
    result = CliRunner().invoke(
        cli.app,
        ["review-seed-aged-task", "--email", "nobody@example.com", "--days", "3"],
    )
    assert result.exit_code == 1
    assert "No account" in result.output
