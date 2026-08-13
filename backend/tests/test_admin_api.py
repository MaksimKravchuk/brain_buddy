"""Tests for the /api/admin routes: fail-closed authz, exact lookup, revoke.

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it. That is
how 009-FR-009 passed the gate with no `SameSite`/`HttpOnly` assertion in the
tree at all.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core import get_config
from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow

from .conftest import (
    SECOND_USER_EMAIL,
    SECOND_USER_PASSWORD,
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    BrainBuddyTestClient,
)

OPERATOR_LOGGER = "app.api.dependencies"
SERVICE_LOGGER = "app.services.admin_service"

#: Planted in a target account's display name and in request bodies so a log
#: assertion fails loudly if any raw input or member content reaches a record
#: (009-FR-008, 009-SC-004).
DISPLAY_NAME_SENTINEL = "ZZSENTINELDISPLAYNAMEZZ"
BODY_CANARY = "ZZCANARYRAWBODYZZ"


def _signup(app, *, email: str, password: str) -> tuple[TestClient, dict]:
    container: Container = app.state.container
    invite_code = f"invite_{email}"
    container.invite_repo.create(Invite(code=invite_code, created_at=utcnow()))
    client = BrainBuddyTestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "invite_code": invite_code},
    )
    assert resp.status_code == 201, resp.text
    return client, resp.json()


def _seed_operator(app, *, email: str, password: str) -> tuple[TestClient, dict]:
    """Provision the operator the only way 009-FR-012 allows, then sign in.

    A configured operator address is reserved, so `POST /api/auth/signup`
    refuses it; `seed_admin` is the single provisioning path.
    """

    container: Container = app.state.container
    container.auth_service.seed_admin(email=email, password=password)
    client = BrainBuddyTestClient(app)
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return client, resp.json()


def _build_admin_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, flags: str):
    data_root = tmp_path / "admin-data"
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS", TEST_USER_EMAIL)
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", flags)
    get_config.cache_clear()
    app = create_app()

    operator_client, operator_me = _seed_operator(
        app, email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD
    )
    member_client, member_me = _signup(
        app, email=SECOND_USER_EMAIL, password=SECOND_USER_PASSWORD
    )
    return app, operator_client, operator_me, member_client, member_me


def _teardown_admin_world(operator_client, member_client, monkeypatch) -> None:
    operator_client.close()
    member_client.close()
    get_config.cache_clear()
    for var in (
        "BRAIN_BUDDY_DATA_DIR",
        "BRAIN_BUDDY_ENV",
        "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS",
        "BRAIN_BUDDY_FEATURE_FLAGS",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def admin_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, dict, TestClient, dict], None, None]:
    """One app with `admin_portal=on`: an operator and a non-operator member.

    The flag state is set explicitly rather than inherited: the default is OFF
    (009-FR-013), so a fixture that stayed silent would mask every
    authorization outcome behind a 404 for the operator.
    """

    _app, operator_client, operator_me, member_client, member_me = _build_admin_world(
        tmp_path, monkeypatch, flags="admin_portal=on"
    )
    yield operator_client, operator_me, member_client, member_me
    _teardown_admin_world(operator_client, member_client, monkeypatch)


@pytest.fixture
def admin_world_flag_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, dict, TestClient, dict], None, None]:
    """The same world with `admin_portal` left at its default-OFF state."""

    _app, operator_client, operator_me, member_client, member_me = _build_admin_world(
        tmp_path, monkeypatch, flags=""
    )
    yield operator_client, operator_me, member_client, member_me
    _teardown_admin_world(operator_client, member_client, monkeypatch)


@pytest.fixture
def anonymous_flag_off_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    """An unauthenticated client against a default-OFF admin portal."""

    data_root = tmp_path / "admin-off-anon"
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS", TEST_USER_EMAIL)
    monkeypatch.delenv("BRAIN_BUDDY_FEATURE_FLAGS", raising=False)
    get_config.cache_clear()
    client = BrainBuddyTestClient(create_app())
    yield client
    client.close()
    get_config.cache_clear()


def _messages(caplog: pytest.LogCaptureFixture, logger: str) -> str:
    """The admin records only, joined.

    Deliberately filtered by logger: `caplog` captures everything that reaches
    the root logger, including the pre-existing `app.api.middleware` access
    line that stamps the raw path of *every* request in the repository. That
    line is not an admin record and is not what 009-FR-008 governs — folding
    it in would make these assertions test the platform access log instead.
    """

    return "\n".join(
        record.getMessage() for record in caplog.records if record.name == logger
    )


def test_009_FR_002_unauthenticated_lookup_is_401(
    anonymous_api_client: TestClient,
) -> None:
    resp = anonymous_api_client.post(
        "/api/admin/accounts/lookup", json={"account_id": "user_anything"}
    )
    assert resp.status_code == 401


def test_009_FR_002_unauthenticated_revoke_is_401(
    anonymous_api_client: TestClient,
) -> None:
    resp = anonymous_api_client.post(
        "/api/admin/accounts/user_anything/revoke-sessions"
    )
    assert resp.status_code == 401


def test_009_FR_002_non_operator_lookup_is_403(admin_world) -> None:
    _operator_client, _operator_me, member_client, _member_me = admin_world
    resp = member_client.post(
        "/api/admin/accounts/lookup", json={"account_id": "user_anything"}
    )
    assert resp.status_code == 403
    assert "id" not in resp.json()


def test_009_FR_002_non_operator_revoke_is_403(admin_world) -> None:
    _operator_client, operator_me, member_client, _member_me = admin_world
    resp = member_client.post(
        f"/api/admin/accounts/{operator_me['id']}/revoke-sessions"
    )
    assert resp.status_code == 403


def test_009_FR_002_denial_does_not_vary_with_target_existence(admin_world) -> None:
    """A 403 must look identical whether the target account exists or not."""

    _operator_client, operator_me, member_client, _member_me = admin_world

    existing = member_client.post(
        "/api/admin/accounts/lookup", json={"account_id": operator_me["id"]}
    )
    missing = member_client.post(
        "/api/admin/accounts/lookup", json={"account_id": "user_does_not_exist"}
    )

    assert existing.status_code == missing.status_code == 403
    assert existing.json()["message"] == missing.json()["message"]


def test_009_FR_003_operator_looks_up_by_account_id(admin_world) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == member_me["id"]
    assert body["email"] == SECOND_USER_EMAIL


def test_009_FR_003_operator_looks_up_by_email(admin_world) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"email": SECOND_USER_EMAIL}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == member_me["id"]


def test_009_FR_003_lookup_rejects_neither_field(admin_world) -> None:
    operator_client, *_ = admin_world
    resp = operator_client.post("/api/admin/accounts/lookup", json={})
    assert resp.status_code == 422


def test_009_FR_003_lookup_rejects_both_fields(admin_world) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup",
        json={"account_id": member_me["id"], "email": SECOND_USER_EMAIL},
    )
    assert resp.status_code == 422


def test_009_FR_003_lookup_no_exact_match_is_404(admin_world) -> None:
    operator_client, *_ = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": "user_does_not_exist"}
    )
    assert resp.status_code == 404


def test_009_FR_004_lookup_response_has_only_the_four_allowed_fields(
    admin_world,
) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
    )
    assert resp.status_code == 200
    assert set(resp.json()) == {"id", "email", "display_name", "deletion_requested"}


def test_009_FR_007_revoke_sessions_unknown_account_is_404(admin_world) -> None:
    operator_client, *_ = admin_world
    resp = operator_client.post(
        "/api/admin/accounts/user_does_not_exist/revoke-sessions"
    )
    assert resp.status_code == 404


def test_009_FR_007_revoke_sessions_is_idempotent_on_zero_active_sessions(
    admin_world,
) -> None:
    operator_client, _operator_me, _member_client, member_me = admin_world
    # The member's own signup session is still live; log it out server-side
    # by revoking it once, then prove a second revoke still reports success.
    first = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
    )
    assert first.status_code == 200
    assert first.json()["revoked_count"] >= 1

    second = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
    )
    assert second.status_code == 200
    assert second.json()["revoked_count"] == 0


def test_009_FR_007_revoke_sessions_signs_the_account_out_everywhere(
    admin_world,
) -> None:
    operator_client, _operator_me, member_client, member_me = admin_world
    assert member_client.get("/api/auth/me").status_code == 200

    resp = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
    )
    assert resp.status_code == 200

    assert member_client.get("/api/auth/me").status_code == 401


def test_009_FR_010_existing_auth_me_is_unaffected_by_this_feature(
    admin_world,
) -> None:
    """The whole `/api/auth/me` body is pinned, not just `id`.

    With `admin_portal` ON for this operator, the member-facing payload must
    still carry exactly the pre-feature key set — no `admin_portal` key, no
    other addition (009-FR-010, 009-FR-013).
    """

    operator_client, operator_me, _member_client, _member_me = admin_world
    resp = operator_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == operator_me["id"]
    assert set(body) == {
        "id",
        "email",
        "display_name",
        "deletion_cancelled",
        "feature_flags",
    }
    assert "admin_portal" not in body["feature_flags"]


def test_009_FR_010_member_feature_flags_never_gain_the_admin_portal_key(
    admin_world,
) -> None:
    """A non-operator's login and me payloads are byte-shape unchanged."""

    _operator_client, _operator_me, member_client, _member_me = admin_world

    login = member_client.post(
        "/api/auth/login",
        json={"email": SECOND_USER_EMAIL, "password": SECOND_USER_PASSWORD},
    )
    assert login.status_code == 200
    me = member_client.get("/api/auth/me")
    assert me.status_code == 200

    for body in (login.json(), me.json()):
        assert "admin_portal" not in body["feature_flags"]
        assert set(body["feature_flags"]) == {
            "delivery_canary",
            "voice_brain_dump",
            "mobile_task_classification",
            "external_agent_relay",
        }


def test_009_FR_002_status_operator_sees_is_operator_true(admin_world) -> None:
    operator_client, *_ = admin_world
    resp = operator_client.get("/api/admin/status")
    assert resp.status_code == 200
    assert resp.json() == {"is_operator": True}


def test_009_FR_002_status_unauthenticated_is_401(
    anonymous_api_client: TestClient,
) -> None:
    resp = anonymous_api_client.get("/api/admin/status")
    assert resp.status_code == 401


def test_009_FR_002_status_non_operator_is_403(admin_world) -> None:
    _operator_client, _operator_me, member_client, _member_me = admin_world
    resp = member_client.get("/api/admin/status")
    assert resp.status_code == 403
    assert "is_operator" not in resp.json()


def test_009_FR_008_status_401_log_carries_no_token_cookie_or_email(
    anonymous_api_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A denied, unauthenticated call must not leak the bogus cookie it was denied for (009-SC-004)."""

    bogus_token = (
        "not-a-real-session-token"  # noqa: S105 - test fixture, not a real secret
    )
    with caplog.at_level(logging.WARNING, logger="app.api.dependencies"):
        resp = anonymous_api_client.get(
            "/api/admin/status",
            cookies={"brainbuddy_session": bogus_token},
        )
    assert resp.status_code == 401

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert bogus_token not in joined
    assert "@" not in joined


def test_009_FR_008_status_403_log_has_account_id_but_not_email(
    admin_world, caplog: pytest.LogCaptureFixture
) -> None:
    """A denied, authenticated non-operator's id is loggable; their email is not (009-SC-004)."""

    _operator_client, _operator_me, member_client, member_me = admin_world

    with caplog.at_level(logging.WARNING, logger="app.api.dependencies"):
        resp = member_client.get("/api/admin/status")
    assert resp.status_code == 403

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert member_me["id"] in joined
    assert member_me["email"] not in joined


# ---------------------------------------------------------------------------
# 009-FR-013 / 009-SC-007 — default-OFF rollout flag, authorization first
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/admin/status"),
        ("POST", "/api/admin/accounts/lookup"),
        ("POST", "/api/admin/accounts/user_anything/revoke-sessions"),
    ],
)
def test_009_FR_013_flag_off_still_answers_401_to_an_unauthenticated_caller(
    anonymous_flag_off_client: TestClient, method: str, path: str
) -> None:
    """Authorization is evaluated before the rollout gate (founder decision).

    With `admin_portal` OFF the unauthenticated answer stays 401, so the flag
    can never soften the authentication boundary (ADR-0008: exposure control,
    never authorization).
    """

    resp = anonymous_flag_off_client.request(method, path, json={"account_id": "x"})
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/admin/status"),
        ("POST", "/api/admin/accounts/lookup"),
        ("POST", "/api/admin/accounts/user_anything/revoke-sessions"),
    ],
)
def test_009_FR_013_flag_off_still_answers_403_to_an_authenticated_non_operator(
    admin_world_flag_off, method: str, path: str
) -> None:
    """A non-operator's response is flag-invariant, so it discloses no rollout.

    403 with the flag OFF and 403 with it ON — identical, which is what makes
    the design's non-disclosure claim true at the API level.
    """

    _operator_client, _operator_me, member_client, _member_me = admin_world_flag_off
    resp = member_client.request(method, path, json={"account_id": "x"})
    assert resp.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/admin/status"),
        ("POST", "/api/admin/accounts/lookup"),
        ("POST", "/api/admin/accounts/user_anything/revoke-sessions"),
    ],
)
def test_009_SC_007_flag_off_answers_404_to_an_allow_listed_operator(
    admin_world_flag_off, method: str, path: str
) -> None:
    """Only an operator sees the feature-absent 404 — the repository convention."""

    operator_client, _operator_me, _member_client, member_me = admin_world_flag_off
    body = {"account_id": member_me["id"]} if path.endswith("lookup") else None
    resp = operator_client.request(method, path, json=body)
    assert resp.status_code == 404


def test_009_SC_007_turning_the_flag_on_restores_lookup_and_revoke(
    admin_world,
) -> None:
    """The flag-ON world is the SC-001..SC-003 behavior, with nothing else changed."""

    operator_client, _operator_me, _member_client, member_me = admin_world

    assert operator_client.get("/api/admin/status").status_code == 200
    lookup = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
    )
    assert lookup.status_code == 200
    revoke = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
    )
    assert revoke.status_code == 200


def test_009_FR_013_flag_off_denial_for_an_operator_touches_no_target_account(
    admin_world_flag_off, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 404 is decided before AdminService is asked anything."""

    from app.services.admin_service import AdminService

    def _explode(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("AdminService.find_account ran behind a disabled flag")

    monkeypatch.setattr(AdminService, "find_account", _explode)

    operator_client, _operator_me, _member_client, member_me = admin_world_flag_off
    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 009-FR-011 — the capability probe is a distinct, high-signal log event
# ---------------------------------------------------------------------------


def test_009_FR_011_probe_denial_is_distinguishable_from_a_data_route_denial(
    admin_world, caplog: pytest.LogCaptureFixture
) -> None:
    """Ordinary navigation must not be indistinguishable from a real attempt."""

    _operator_client, _operator_me, member_client, member_me = admin_world

    with caplog.at_level(logging.WARNING, logger=OPERATOR_LOGGER):
        assert member_client.get("/api/admin/status").status_code == 403
        probe = _messages(caplog, OPERATOR_LOGGER)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=OPERATOR_LOGGER):
        assert (
            member_client.post(
                "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
            ).status_code
            == 403
        )
        data = _messages(caplog, OPERATOR_LOGGER)

    assert "event=admin_capability_probe" in probe
    assert "event=admin_data_route" in data
    assert probe != data
    assert "route=/api/admin/status" in probe
    assert "route=/api/admin/accounts/lookup" in data


def test_009_FR_011_status_route_is_only_reachable_by_an_operator(
    admin_world,
) -> None:
    operator_client, _operator_me, member_client, _member_me = admin_world
    assert operator_client.get("/api/admin/status").json() == {"is_operator": True}
    assert "is_operator" not in member_client.get("/api/admin/status").json()


# ---------------------------------------------------------------------------
# 009-FR-008 / 009-SC-004 — the per-event denial record matrix
# ---------------------------------------------------------------------------


def test_009_SC_004_401_record_carries_route_correlation_and_outcome_only(
    anonymous_api_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """An unauthenticated denial has no resolved operator to name — by design."""

    bogus = "not-a-real-session-token"  # noqa: S105 - fixture, not a secret
    with caplog.at_level(logging.WARNING, logger=OPERATOR_LOGGER):
        resp = anonymous_api_client.post(
            f"/api/admin/accounts/{BODY_CANARY}/revoke-sessions",
            cookies={"brainbuddy_session": bogus},
        )
    assert resp.status_code == 401

    joined = _messages(caplog, OPERATOR_LOGGER)
    assert "route=/api/admin/accounts/{account_id}/revoke-sessions" in joined
    assert "correlation=" in joined
    assert "outcome=no_valid_session" in joined
    assert "operator=" not in joined
    assert bogus not in joined
    assert BODY_CANARY not in joined
    assert "@" not in joined


def test_009_SC_004_403_record_carries_the_operator_but_never_a_target(
    admin_world, caplog: pytest.LogCaptureFixture
) -> None:
    """A denial is decided before any target is resolved, so none can be named."""

    _operator_client, _operator_me, member_client, member_me = admin_world

    with caplog.at_level(logging.WARNING, logger=OPERATOR_LOGGER):
        resp = member_client.post(
            "/api/admin/accounts/lookup",
            json={"email": f"{BODY_CANARY}@example.com"},
        )
    assert resp.status_code == 403

    joined = _messages(caplog, OPERATOR_LOGGER)
    assert f"operator={member_me['id']}" in joined
    assert "outcome=not_an_operator" in joined
    assert "correlation=" in joined
    assert BODY_CANARY not in joined
    assert member_me["email"] not in joined
    assert "@" not in joined


def test_009_SC_004_denied_lookup_never_reaches_the_admin_service(
    admin_world, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deny before touch, proved by poisoning the target-facing methods."""

    from app.services.admin_service import AdminService

    def _explode(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("a denied admin request reached AdminService")

    monkeypatch.setattr(AdminService, "find_account", _explode)
    monkeypatch.setattr(AdminService, "revoke_sessions", _explode)

    _operator_client, _operator_me, member_client, member_me = admin_world

    assert (
        member_client.post(
            "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
        ).status_code
        == 403
    )
    assert (
        member_client.post(
            f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
        ).status_code
        == 403
    )


def test_009_SC_002_a_denied_revoke_leaves_the_target_sessions_valid(
    admin_world,
) -> None:
    """The effect, not just the status: the operator is still signed in after."""

    operator_client, operator_me, member_client, _member_me = admin_world

    resp = member_client.post(
        f"/api/admin/accounts/{operator_me['id']}/revoke-sessions"
    )
    assert resp.status_code == 403
    assert operator_client.get("/api/auth/me").status_code == 200


def test_009_SC_004_successful_lookup_record_names_the_resolved_account_only(
    admin_world, caplog: pytest.LogCaptureFixture
) -> None:
    """Sentinels planted in the display name and the request body must not leak."""

    operator_client, operator_me, member_client, member_me = admin_world
    assert (
        member_client.patch(
            "/api/account/profile", json={"display_name": DISPLAY_NAME_SENTINEL}
        ).status_code
        == 200
    )

    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        resp = operator_client.post(
            "/api/admin/accounts/lookup", json={"account_id": member_me["id"]}
        )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == DISPLAY_NAME_SENTINEL

    joined = _messages(caplog, SERVICE_LOGGER)
    assert f"operator={operator_me['id']}" in joined
    assert f"account={member_me['id']}" in joined
    assert "outcome=found" in joined
    assert DISPLAY_NAME_SENTINEL not in joined
    assert member_me["email"] not in joined
    assert "@" not in joined


def test_009_SC_004_successful_lookup_by_email_never_logs_the_submitted_key(
    admin_world, caplog: pytest.LogCaptureFixture
) -> None:
    """The submitted key is raw request input and is itself an email."""

    operator_client, _operator_me, _member_client, member_me = admin_world

    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        resp = operator_client.post(
            "/api/admin/accounts/lookup", json={"email": SECOND_USER_EMAIL}
        )
    assert resp.status_code == 200

    joined = _messages(caplog, SERVICE_LOGGER)
    assert SECOND_USER_EMAIL not in joined
    assert f"account={member_me['id']}" in joined


def test_009_SC_004_revoke_record_is_captured_separately_from_the_lookup(
    admin_world, caplog: pytest.LogCaptureFixture
) -> None:
    operator_client, operator_me, _member_client, member_me = admin_world

    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        resp = operator_client.post(
            f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
        )
    assert resp.status_code == 200

    joined = _messages(caplog, SERVICE_LOGGER)
    assert "Admin session revoke" in joined
    assert "Admin lookup" not in joined
    assert f"operator={operator_me['id']}" in joined
    assert f"account={member_me['id']}" in joined
    assert "outcome=revoked" in joined
    assert "@" not in joined


# ---------------------------------------------------------------------------
# 009-FR-003 — exact match, end to end, including path-traversal variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    ["upper", "spaced", "prefix", "suffix", "traversal", "traversal_encoded"],
)
def test_009_SC_001_near_match_variants_of_a_real_account_id_return_404(
    admin_world, variant: str
) -> None:
    """A variant of a real id must never resolve to that account.

    `traversal` matters twice over: `UserRepository` builds a file path from
    the id, so `../users/<id>` would otherwise resolve to the same record and
    a revoke would report 2xx for an id that is not an account.
    """

    operator_client, _operator_me, _member_client, member_me = admin_world
    real = member_me["id"]
    candidate = {
        "upper": real.upper(),
        "spaced": f" {real} ",
        "prefix": real[:-2],
        "suffix": f"{real}x",
        "traversal": f"../users/{real}",
        "traversal_encoded": f"..%2Fusers%2F{real}",
    }[variant]

    resp = operator_client.post(
        "/api/admin/accounts/lookup", json={"account_id": candidate}
    )
    assert resp.status_code == 404


def test_009_SC_001_near_match_email_variants_return_404(admin_world) -> None:
    operator_client, *_ = admin_world
    for candidate in (
        SECOND_USER_EMAIL.upper(),
        f" {SECOND_USER_EMAIL} ",
        SECOND_USER_EMAIL[:-2],
        f"x{SECOND_USER_EMAIL}",
    ):
        resp = operator_client.post(
            "/api/admin/accounts/lookup", json={"email": candidate}
        )
        assert resp.status_code == 404, candidate


def test_009_FR_007_revoke_rejects_a_traversal_variant_of_a_real_account_id(
    admin_world,
) -> None:
    """A variant must 404, never a 2xx `revoked_count: 0` that reads as success."""

    operator_client, _operator_me, member_client, member_me = admin_world

    resp = operator_client.post(
        f"/api/admin/accounts/..%2Fusers%2F{member_me['id']}/revoke-sessions"
    )
    assert resp.status_code == 404
    # And the real account's session is untouched by the rejected variant.
    assert member_client.get("/api/auth/me").status_code == 200


def test_009_SC_003_revoke_invalidates_two_concurrent_sessions(admin_world) -> None:
    """Both live sessions are gone, read back through the API, not from a count."""

    operator_client, _operator_me, member_client, member_me = admin_world

    second_device = BrainBuddyTestClient(member_client.app)
    login = second_device.post(
        "/api/auth/login",
        json={"email": SECOND_USER_EMAIL, "password": SECOND_USER_PASSWORD},
    )
    assert login.status_code == 200
    assert member_client.get("/api/auth/me").status_code == 200
    assert second_device.get("/api/auth/me").status_code == 200

    resp = operator_client.post(
        f"/api/admin/accounts/{member_me['id']}/revoke-sessions"
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_count"] == 2
    assert member_client.get("/api/auth/me").status_code == 401
    assert second_device.get("/api/auth/me").status_code == 401
    second_device.close()


# ---------------------------------------------------------------------------
# 009-FR-002 — the two session-resolution paths cannot diverge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cookies",
    [
        {},
        {"brainbuddy_session": "unknown-token"},
        {"brainbuddy_session": ""},
    ],
    ids=["missing", "unknown", "empty"],
)
def test_009_FR_002_require_operator_and_get_current_user_reject_alike(
    admin_world, cookies: dict[str, str]
) -> None:
    """`require_operator` resolves the cookie itself (plan key decision 7).

    That deliberate duplication is only safe while both paths accept and
    reject the same cookie states; this pins them together.
    """

    _operator_client, _operator_me, member_client, _member_me = admin_world
    bare = BrainBuddyTestClient(member_client.app)

    admin = bare.get("/api/admin/status", cookies=cookies)
    member = bare.get("/api/auth/me", cookies=cookies)

    assert admin.status_code == member.status_code == 401
    bare.close()


def test_009_FR_002_both_session_paths_accept_the_same_valid_cookie(
    admin_world,
) -> None:
    operator_client, *_ = admin_world
    assert operator_client.get("/api/auth/me").status_code == 200
    assert operator_client.get("/api/admin/status").status_code == 200


# ---------------------------------------------------------------------------
# 009-FR-009 — the same-origin properties this feature relies on
# ---------------------------------------------------------------------------


def test_009_FR_009_session_cookie_is_httponly_and_samesite_lax(
    admin_world,
) -> None:
    """FR-009 rests entirely on these two properties, so they are pinned."""

    operator_client, *_ = admin_world
    resp = operator_client.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert resp.status_code == 200
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_009_FR_009_admin_routes_carry_no_permissive_cross_origin_header(
    admin_world,
) -> None:
    """No CORS middleware is configured anywhere; a regression must fail here."""

    operator_client, _operator_me, _member_client, member_me = admin_world

    for resp in (
        operator_client.get(
            "/api/admin/status", headers={"Origin": "https://evil.example"}
        ),
        operator_client.post(
            f"/api/admin/accounts/{member_me['id']}/revoke-sessions",
            headers={"Origin": "https://evil.example"},
        ),
    ):
        lowered = {key.lower() for key in resp.headers}
        assert "access-control-allow-origin" not in lowered
        assert "access-control-allow-credentials" not in lowered


# ---------------------------------------------------------------------------
# 009-FR-008 — the logged route template is canonical across framework versions
# ---------------------------------------------------------------------------


class _FakeRoute:
    """Just the one attribute `_admin_route` reads off `scope["route"]`."""

    def __init__(self, path: str) -> None:
        self.path = path


def _route_for(path_or_route, *, api_prefix: str = "/api") -> str:
    from types import SimpleNamespace

    from app.api.dependencies import _admin_route

    request = SimpleNamespace(scope={"route": path_or_route})
    config = SimpleNamespace(api_prefix=api_prefix)
    return _admin_route(request, config)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mounted", "router_local", "canonical"),
    [
        ("/api/admin/status", "/status", "/api/admin/status"),
        (
            "/api/admin/accounts/lookup",
            "/accounts/lookup",
            "/api/admin/accounts/lookup",
        ),
        (
            "/api/admin/accounts/{account_id}/revoke-sessions",
            "/accounts/{account_id}/revoke-sessions",
            "/api/admin/accounts/{account_id}/revoke-sessions",
        ),
    ],
)
def test_009_FR_008_route_template_is_canonical_for_both_framework_shapes(
    mounted: str, router_local: str, canonical: str
) -> None:
    """`scope["route"]` is version-dependent; the audit record must not be.

    Older FastAPI/Starlette set `scope["route"]` to the route as registered on
    the application, carrying the `include_router` prefix. Newer versions let
    the innermost matching router set it, so the same request yields a
    router-local template with no prefix. The 009-FR-008 record has to read
    identically either way, or the audit stream silently changes shape on a
    dependency bump inside the declared range.
    """

    assert _route_for(_FakeRoute(mounted)) == canonical
    assert _route_for(_FakeRoute(router_local)) == canonical


def test_009_FR_008_an_already_prefixed_template_is_not_prefixed_twice() -> None:
    """Guards the obvious wrong fix: unconditional prepending."""

    assert _route_for(_FakeRoute("/api/admin/status")).count("/api/admin") == 1


def test_009_FR_008_a_non_default_api_prefix_still_yields_one_canonical_route() -> None:
    """The prefix is read from configuration, not hard-coded."""

    assert _route_for(_FakeRoute("/status"), api_prefix="/v2") == "/v2/admin/status"
    assert (
        _route_for(_FakeRoute("/v2/admin/status"), api_prefix="/v2")
        == "/v2/admin/status"
    )


@pytest.mark.parametrize(
    "route",
    [None, object(), _FakeRoute(""), _FakeRoute("accounts/lookup")],
    ids=["missing", "no-path-attr", "empty", "not-absolute"],
)
def test_009_FR_008_an_unresolvable_route_stays_redacted_and_fail_closed(
    route,
) -> None:
    """No template, no guess: never fall back to the raw caller-supplied path."""

    assert _route_for(route) == "unmatched"
