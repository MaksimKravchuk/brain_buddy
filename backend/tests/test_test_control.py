"""Test control API on the frozen Python server (spec 027 PR-06)."""

from __future__ import annotations

from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import get_config
from app.main import create_app

from .conftest import BrainBuddyTestClient

TOKEN = "tc-" + "x" * 29
HEADERS = {"X-Test-Control-Token": TOKEN}
BASE = "/api/__test__"
OWNER = "owner-one@example.com"
OTHER = "owner-two@example.com"
PASSWORD = "correct horse battery staple 1"

AppFactory = Callable[[str | None, str | None], TestClient]


@pytest.fixture
def make_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[AppFactory]:
    clients: list[TestClient] = []

    def build(env: str | None, token: str | None) -> TestClient:
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "https://bb.example.com")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / f"d{len(clients)}"))
        for name, value in (
            ("BRAIN_BUDDY_ENV", env),
            ("BRAIN_BUDDY_TEST_CONTROL_TOKEN", token),
        ):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        get_config.cache_clear()
        client = BrainBuddyTestClient(create_app())
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.close()
    get_config.cache_clear()


@pytest.fixture
def control(make_client: AppFactory) -> TestClient:
    return make_client("test", TOKEN)


def _signup(client: TestClient, email: str) -> str:
    code = client.post(f"{BASE}/invites", json={}, headers=HEADERS).json()["codes"][0]
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "invite_code": code},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


@pytest.mark.parametrize("env", ["development", None])
def test_027_fr_022_prefix_is_404_outside_the_test_environment(
    make_client: AppFactory, env: str | None
) -> None:
    """Even with a token configured, a non-test server does not route the prefix."""

    client = make_client(env, TOKEN)
    for method, path in (
        ("post", "/invites"),
        ("post", "/admin"),
        ("put", "/flags/weekly_review"),
        ("post", "/sweeps/review"),
        ("get", f"/owners/{OWNER}/tasks"),
        ("post", "/reconcile"),
    ):
        resp = getattr(client, method)(f"{BASE}{path}", headers=HEADERS)
        assert resp.status_code == 404, (method, path, resp.status_code)


def test_027_fr_022_production_configuration_never_routes_the_prefix() -> None:
    from fastapi import FastAPI
    from pydantic import SecretStr

    from app.api.test_control import install_test_control
    from app.core.config import AppConfig, AppEnvironment

    config = AppConfig(
        environment=AppEnvironment.PRODUCTION, test_control_token=SecretStr(TOKEN)
    )
    app = FastAPI()
    assert install_test_control(app, config) is False
    assert not [r for r in app.routes if "__test__" in getattr(r, "path", "")]


def test_027_fr_022_test_environment_without_token_does_not_route_the_prefix(
    make_client: AppFactory,
) -> None:
    client = make_client("test", None)
    assert client.post(f"{BASE}/invites", json={}).status_code == 404


@pytest.mark.parametrize("token", [None, "", "wrong", TOKEN + "x"])
def test_027_fr_022_every_operation_needs_the_exact_token(
    control: TestClient, token: str | None
) -> None:
    headers = {} if token is None else {"X-Test-Control-Token": token}
    for method, path in (
        ("post", "/invites"),
        ("post", "/admin"),
        ("put", "/flags/weekly_review"),
        ("post", "/sweeps/review"),
        ("post", "/review/aged-task"),
        ("get", f"/owners/{OWNER}/tasks"),
        ("post", "/reconcile"),
    ):
        resp = getattr(control, method)(f"{BASE}{path}", headers=headers)
        assert resp.status_code == 401, (method, path, resp.status_code)
        assert resp.headers["X-Correlation-ID"]
        assert TOKEN not in resp.text


def test_027_fr_001_invites_are_fresh_and_usable_for_signup(
    control: TestClient,
) -> None:
    first = control.post(f"{BASE}/invites", json={"count": 2}, headers=HEADERS)
    second = control.post(f"{BASE}/invites", json={"count": 2}, headers=HEADERS)
    assert first.status_code == 200
    codes = first.json()["codes"] + second.json()["codes"]
    assert len(set(codes)) == 4
    assert first.headers["X-Correlation-ID"]
    resp = control.post(
        "/api/auth/signup",
        json={"email": OWNER, "password": PASSWORD, "invite_code": codes[0]},
    )
    assert resp.status_code == 201


def test_027_fr_001_admin_account_can_sign_in(control: TestClient) -> None:
    body = {"email": "ops@example.com", "password": PASSWORD}
    assert control.post(f"{BASE}/admin", json=body, headers=HEADERS).status_code == 201
    assert control.post(f"{BASE}/admin", json=body, headers=HEADERS).status_code == 201
    login = control.post("/api/auth/login", json=body)
    assert login.status_code == 200, login.text


def test_027_fr_001_flag_modes_and_selected_owners(control: TestClient) -> None:
    owner_id = _signup(control, OWNER)
    url = f"{BASE}/flags/weekly_review"
    on = control.put(url, json={"mode": "on"}, headers=HEADERS)
    assert on.status_code == 200 and on.json()["mode"] == "on"
    selected = control.put(
        url, json={"mode": "selected", "owners": [OWNER]}, headers=HEADERS
    )
    assert selected.json() == {"key": "weekly_review", "mode": "selected", "owners": 1}
    service = control.app.state.container.feature_flag_service  # type: ignore[attr-defined]
    view = service.describe(operator_id="probe")
    cohort = next(f for f in view.flags if f.name == "weekly_review").selected_users
    assert [m.account_id for m in cohort] == [owner_id]
    assert control.put(url, json={"mode": "off"}, headers=HEADERS).status_code == 200
    unknown = control.put(
        f"{BASE}/flags/not_a_flag", json={"mode": "on"}, headers=HEADERS
    )
    assert unknown.status_code == 400
    ghost = control.put(
        url,
        json={"mode": "selected", "owners": ["nobody@example.com"]},
        headers=HEADERS,
    )
    assert ghost.status_code == 404


def test_027_fr_001_aged_task_and_owner_readback_are_owner_scoped(
    control: TestClient,
) -> None:
    _signup(control, OWNER)
    _signup(control, OTHER)
    seeded = control.post(
        f"{BASE}/review/aged-task",
        json={"owner_email": OWNER, "days": 30, "title": "Aged synthetic task"},
        headers=HEADERS,
    )
    assert seeded.status_code == 201, seeded.text
    mine = control.get(f"{BASE}/owners/{OWNER}/tasks", headers=HEADERS).json()["tasks"]
    theirs = control.get(f"{BASE}/owners/{OTHER}/tasks", headers=HEADERS).json()[
        "tasks"
    ]
    assert [t["id"] for t in mine] == [seeded.json()["task_id"]]
    assert theirs == []
    ghost = control.get(f"{BASE}/owners/ghost@example.com/tasks", headers=HEADERS)
    assert ghost.status_code == 404


def test_027_fr_001_sweeps_return_counters_and_unknown_is_404(
    control: TestClient,
) -> None:
    for name in ("review", "retention", "purge", "voice", "agents"):
        resp = control.post(f"{BASE}/sweeps/{name}", json={}, headers=HEADERS)
        assert resp.status_code == 200, (name, resp.text)
        body = resp.json()
        assert body and all(isinstance(v, int) for v in body.values())
    nope = control.post(f"{BASE}/sweeps/nope", json={}, headers=HEADERS)
    assert nope.status_code == 404
    reconcile = control.post(f"{BASE}/reconcile", json={}, headers=HEADERS)
    assert reconcile.status_code == 200
    assert reconcile.json() == {"reconciled": 0}
