"""Operator authority is not self-claimable (009-FR-012, 009-SC-006).

The allow-list matches on `user.email`, and an email change is unverified, so
without a reservation any *unclaimed* operator address could simply be taken —
by signing up on it, or by moving an existing account onto it — and claiming it
would confer full lookup and session-revoke power. These tests prove both
member-driven paths refuse, that the refusal discloses nothing, and that
`seed_admin` remains the one provisioning path.

Deliberately its own module rather than more cases inside
`test_account_api.py`/`test_auth_routes.py`: those modules build their app
without an operator allow-list, and the reservation only exists when one is
configured.
"""

from __future__ import annotations

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
    BrainBuddyTestClient,
)

#: Configured as an operator but never provisioned — the exact window the
#: reservation closes.
UNCLAIMED_OPERATOR_EMAIL = "unclaimed-operator@example.com"
OPERATOR_PASSWORD = "seeded-operator-password"


@pytest.fixture
def reservation_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, dict], None, None]:
    """An app whose allow-listed operator address has no account behind it."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "reservation-data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS", UNCLAIMED_OPERATOR_EMAIL)
    # `admin_portal` no longer exists as a flag (DD-14): `/admin` needs no
    # staged flag to be reachable by an allow-listed operator.
    monkeypatch.delenv("BRAIN_BUDDY_FEATURE_FLAGS", raising=False)
    get_config.cache_clear()
    app = create_app()

    container: Container = app.state.container
    container.invite_repo.create(Invite(code="invite_member", created_at=utcnow()))
    client = BrainBuddyTestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": SECOND_USER_EMAIL,
            "password": SECOND_USER_PASSWORD,
            "invite_code": "invite_member",
        },
    )
    assert resp.status_code == 201, resp.text

    yield client, resp.json()

    client.close()
    get_config.cache_clear()
    for var in (
        "BRAIN_BUDDY_DATA_DIR",
        "BRAIN_BUDDY_ENV",
        "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS",
        "BRAIN_BUDDY_FEATURE_FLAGS",
    ):
        monkeypatch.delenv(var, raising=False)


def _new_invite(client: TestClient, code: str) -> str:
    container: Container = client.app.state.container  # type: ignore[attr-defined]
    container.invite_repo.create(Invite(code=code, created_at=utcnow()))
    return code


def test_009_FR_012_signup_refuses_a_configured_operator_address(
    reservation_world,
) -> None:
    """The unclaimed operator address cannot be taken through signup."""

    client, _member = reservation_world
    fresh = BrainBuddyTestClient(client.app)  # type: ignore[attr-defined]

    resp = fresh.post(
        "/api/auth/signup",
        json={
            "email": UNCLAIMED_OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD,
            "invite_code": _new_invite(client, "invite_claim"),
        },
    )

    assert resp.status_code == 409
    container: Container = client.app.state.container  # type: ignore[attr-defined]
    assert container.user_repo.get_by_email(UNCLAIMED_OPERATOR_EMAIL) is None
    fresh.close()


def test_009_FR_012_signup_refusal_is_indistinguishable_from_a_taken_address(
    reservation_world,
) -> None:
    """The refusal must not disclose that the address is an operator address."""

    client, _member = reservation_world
    fresh = BrainBuddyTestClient(client.app)  # type: ignore[attr-defined]

    reserved = fresh.post(
        "/api/auth/signup",
        json={
            "email": UNCLAIMED_OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD,
            "invite_code": _new_invite(client, "invite_reserved"),
        },
    )
    taken = fresh.post(
        "/api/auth/signup",
        json={
            "email": SECOND_USER_EMAIL,
            "password": OPERATOR_PASSWORD,
            "invite_code": _new_invite(client, "invite_taken"),
        },
    )

    assert reserved.status_code == taken.status_code == 409
    assert reserved.json()["message"] == taken.json()["message"]
    fresh.close()


def test_009_SC_006_a_member_cannot_move_their_account_onto_an_operator_address(
    reservation_world,
) -> None:
    """The self-service email change is the real escalation path; it refuses.

    And the member is still denied by every `/admin` route afterwards — the
    point of the control is the authorization outcome, not the error code.
    """

    client, member = reservation_world

    resp = client.post(
        "/api/account/email",
        json={
            "new_email": UNCLAIMED_OPERATOR_EMAIL,
            "current_password": SECOND_USER_PASSWORD,
        },
    )

    assert resp.status_code == 400
    assert client.get("/api/auth/me").json()["email"] == member["email"]
    assert client.get("/api/admin/status").status_code == 403
    assert (
        client.post(
            "/api/admin/accounts/lookup", json={"account_id": member["id"]}
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/admin/accounts/{member['id']}/revoke-sessions").status_code
        == 403
    )


def test_009_SC_006_email_change_refusal_does_not_disclose_the_reservation(
    reservation_world,
) -> None:
    """Byte-identical to the already-registered refusal, deliberately."""

    client, _member = reservation_world
    container: Container = client.app.state.container  # type: ignore[attr-defined]
    container.invite_repo.create(Invite(code="invite_other", created_at=utcnow()))
    other = BrainBuddyTestClient(client.app)  # type: ignore[attr-defined]
    assert (
        other.post(
            "/api/auth/signup",
            json={
                "email": "taken@example.com",
                "password": SECOND_USER_PASSWORD,
                "invite_code": "invite_other",
            },
        ).status_code
        == 201
    )

    reserved = client.post(
        "/api/account/email",
        json={
            "new_email": UNCLAIMED_OPERATOR_EMAIL,
            "current_password": SECOND_USER_PASSWORD,
        },
    )
    taken = client.post(
        "/api/account/email",
        json={
            "new_email": "taken@example.com",
            "current_password": SECOND_USER_PASSWORD,
        },
    )

    assert reserved.status_code == taken.status_code
    assert reserved.json()["message"] == taken.json()["message"]
    other.close()


def test_009_FR_012_a_case_variant_of_an_operator_address_is_also_reserved(
    reservation_world,
) -> None:
    """The allow-list is normalized, so the reservation must normalize too."""

    client, _member = reservation_world

    resp = client.post(
        "/api/account/email",
        json={
            "new_email": f"  {UNCLAIMED_OPERATOR_EMAIL.upper()}  ",
            "current_password": SECOND_USER_PASSWORD,
        },
    )

    assert resp.status_code == 400


def test_009_FR_012_seed_admin_still_provisions_the_configured_identity(
    reservation_world,
) -> None:
    """The seed path is deliberately exempt — it is the only provisioning path.

    Once seeded, that identity really is an operator, which is what makes the
    reservation a closure of the self-claim path rather than a lockout.
    """

    client, _member = reservation_world
    container: Container = client.app.state.container  # type: ignore[attr-defined]

    seeded = container.auth_service.seed_admin(
        email=UNCLAIMED_OPERATOR_EMAIL, password=OPERATOR_PASSWORD
    )
    assert seeded.email == UNCLAIMED_OPERATOR_EMAIL

    operator = BrainBuddyTestClient(client.app)  # type: ignore[attr-defined]
    login = operator.post(
        "/api/auth/login",
        json={"email": UNCLAIMED_OPERATOR_EMAIL, "password": OPERATOR_PASSWORD},
    )
    assert login.status_code == 200
    assert operator.get("/api/admin/status").status_code == 200
    operator.close()


def test_009_FR_012_an_unclaimed_operator_address_stays_unauthorized(
    reservation_world,
) -> None:
    """Nobody holds operator power while the configured address has no account."""

    client, _member = reservation_world
    container: Container = client.app.state.container  # type: ignore[attr-defined]

    assert container.user_repo.get_by_email(UNCLAIMED_OPERATOR_EMAIL) is None
    assert client.get("/api/admin/status").status_code == 403
