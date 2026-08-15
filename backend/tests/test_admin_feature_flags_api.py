"""The five `/api/admin/feature-flags` routes behind feature 009's gate.

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core import get_config
from app.exceptions import RepositoryError
from app.main import create_app
from app.repositories.feature_flag import FlagMode, FlagOverride
from app.schemas.auth import Invite
from app.utils.time import utcnow

from .conftest import (
    SECOND_USER_EMAIL,
    SECOND_USER_PASSWORD,
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    BrainBuddyTestClient,
)

FLAGS_ROOT = "/api/admin/feature-flags"
MANAGED = "voice_brain_dump"
OTHER_MANAGED = "mobile_task_classification"

SERVICE_LOGGER = "app.services.feature_flag_service"
ADMIN_SERVICE_LOGGER = "app.services.admin_service"

#: Planted in the target account's display name and in the request body so the
#: document-bytes assertion fails loudly if member content ever lands there.
DISPLAY_NAME_SENTINEL = "ZZSENTINELDISPLAYNAMEZZ"
EMAIL_SENTINEL_LOCAL = "zzsentinelemailzz"


def _signup(app: Any, *, email: str, password: str) -> tuple[TestClient, dict]:
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


def _seed_operator(app: Any, *, email: str, password: str) -> tuple[TestClient, dict]:
    container: Container = app.state.container
    container.auth_service.seed_admin(email=email, password=password)
    client = BrainBuddyTestClient(app)
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return client, resp.json()


class _FlagWorld:
    """One app with an operator, a plain member, and an anonymous client."""

    def __init__(self, app: Any, data_root: Path) -> None:
        self.app = app
        self.data_root = data_root
        self.container: Container = app.state.container
        self.operator, self.operator_me = _seed_operator(
            app, email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD
        )
        self.member, self.member_me = _signup(
            app, email=SECOND_USER_EMAIL, password=SECOND_USER_PASSWORD
        )
        self.anonymous = BrainBuddyTestClient(app)

    @property
    def document(self) -> Path:
        return self.container.feature_flag_repo.document_path

    def document_bytes(self) -> bytes | None:
        return self.document.read_bytes() if self.document.exists() else None

    def close(self) -> None:
        self.operator.close()
        self.member.close()
        self.anonymous.close()


def _build_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    flags: str,
    internal_users: str | None = None,
    subdir: str = "flag-data",
) -> _FlagWorld:
    data_root = tmp_path / subdir
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS", TEST_USER_EMAIL)
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", flags)
    if internal_users is None:
        monkeypatch.delenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", raising=False)
    else:
        monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", internal_users)
    get_config.cache_clear()
    return _FlagWorld(create_app(), data_root)


def _teardown(world: _FlagWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    world.close()
    get_config.cache_clear()
    for var in (
        "BRAIN_BUDDY_DATA_DIR",
        "BRAIN_BUDDY_ENV",
        "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS",
        "BRAIN_BUDDY_FEATURE_FLAGS",
        "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def portal_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[_FlagWorld, None, None]:
    """An app with `admin_portal=on` — the flag state must be set explicitly."""

    world = _build_world(tmp_path, monkeypatch, flags="admin_portal=on")
    yield world
    _teardown(world, monkeypatch)


@pytest.fixture
def portal_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[_FlagWorld, None, None]:
    """The same app with `admin_portal` not effective for anyone."""

    world = _build_world(tmp_path, monkeypatch, flags="admin_portal=off")
    yield world
    _teardown(world, monkeypatch)


def _all_five_routes(account_id: str) -> list[tuple[str, str, dict | None]]:
    """The one read plus the four mutations, matching FR-006's own count."""

    return [
        ("GET", FLAGS_ROOT, None),
        ("PUT", f"{FLAGS_ROOT}/{MANAGED}/mode", {"mode": "on"}),
        ("DELETE", f"{FLAGS_ROOT}/{MANAGED}", None),
        ("POST", f"{FLAGS_ROOT}/{MANAGED}/selected-users", {"account_id": account_id}),
        ("DELETE", f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}", None),
    ]


def _call(client: TestClient, method: str, path: str, body: dict | None):
    return client.request(method, path, json=body)


def _poison(world: _FlagWorld) -> None:
    """Make every target-facing service and repository method fail loudly.

    A denial must be decided before any of them is consulted, on all five
    routes including `GET` (010-FR-006). Comparing response bodies alone would
    not catch a read that happened and was then discarded.
    """

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a denied request must not touch the runtime store")

    for name in (
        "describe",
        "set_mode",
        "clear_override",
        "add_selected_user",
        "remove_selected_user",
    ):
        setattr(world.container.feature_flag_service, name, _explode)
    for name in ("read", "mutate", "clear", "scrub_user"):
        setattr(world.container.feature_flag_repo, name, _explode)


def _flag(payload: dict, name: str) -> dict:
    return next(entry for entry in payload["flags"] if entry["name"] == name)


# ---------------------------------------------------------------------------
# C1 — authorization on all five routes, GET included
# ---------------------------------------------------------------------------


def test_010_FR_006_every_route_answers_401_unauthenticated(
    portal_on: _FlagWorld,
) -> None:
    """All five routes reject an unauthenticated caller with 401."""

    _poison(portal_on)
    for method, path, body in _all_five_routes(portal_on.member_me["id"]):
        response = _call(portal_on.anonymous, method, path, body)
        assert response.status_code == 401, f"{method} {path}: {response.text}"
    assert portal_on.document_bytes() is None


@pytest.mark.parametrize("portal_state", ["on", "off"])
def test_010_SC_006_every_route_answers_403_to_a_non_operator_in_both_flag_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, portal_state: str
) -> None:
    """A non-operator gets 403 whether or not `admin_portal` is effective."""

    world = _build_world(
        tmp_path,
        monkeypatch,
        flags=f"admin_portal={portal_state}",
        subdir=f"flag-data-{portal_state}",
    )
    try:
        _poison(world)
        for method, path, body in _all_five_routes(world.member_me["id"]):
            response = _call(world.member, method, path, body)
            assert response.status_code == 403, f"{method} {path}: {response.text}"
        assert world.document_bytes() is None
    finally:
        _teardown(world, monkeypatch)


def test_010_SC_006_every_route_answers_404_to_an_operator_when_the_portal_is_off(
    portal_off: _FlagWorld,
) -> None:
    """An authorized operator sees the fail-closed 404 when the portal is off."""

    _poison(portal_off)
    for method, path, body in _all_five_routes(portal_off.member_me["id"]):
        response = _call(portal_off.operator, method, path, body)
        assert response.status_code == 404, f"{method} {path}: {response.text}"
    assert portal_off.document_bytes() is None


def test_010_FR_006_a_denial_introduces_no_new_log_record_type(
    portal_off: _FlagWorld, caplog: pytest.LogCaptureFixture
) -> None:
    """A denial keeps 009's own records and adds none of this feature's."""

    caplog.clear()
    with caplog.at_level(logging.INFO):
        portal_off.operator.get(FLAGS_ROOT)
        portal_off.member.get(FLAGS_ROOT)
        portal_off.anonymous.get(FLAGS_ROOT)

    assert [r for r in caplog.records if r.name == SERVICE_LOGGER] == []
    denials = [r for r in caplog.records if r.name == "app.api.dependencies"]
    assert len(denials) == 3


# ---------------------------------------------------------------------------
# C2 — exact-match add
# ---------------------------------------------------------------------------


def _enable_cohort(world: _FlagWorld, flag: str = MANAGED) -> None:
    response = world.operator.put(
        f"{FLAGS_ROOT}/{flag}/mode", json={"mode": "selected_users"}
    )
    assert response.status_code == 200, response.text


def test_010_FR_007_add_accepts_an_exact_account_id_and_an_exact_email(
    portal_on: _FlagWorld,
) -> None:
    """Adding by exact account ID and by exact canonical email both succeed."""

    _enable_cohort(portal_on)
    by_id = portal_on.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users",
        json={"account_id": portal_on.member_me["id"]},
    )
    assert by_id.status_code == 200, by_id.text
    assert [
        member["account_id"]
        for member in _flag(by_id.json(), MANAGED)["selected_users"]
    ] == [portal_on.member_me["id"]]

    _enable_cohort(portal_on, OTHER_MANAGED)
    by_email = portal_on.operator.post(
        f"{FLAGS_ROOT}/{OTHER_MANAGED}/selected-users",
        json={"email": SECOND_USER_EMAIL},
    )
    assert by_email.status_code == 200, by_email.text
    assert [
        member["account_id"]
        for member in _flag(by_email.json(), OTHER_MANAGED)["selected_users"]
    ] == [portal_on.member_me["id"]]


def test_010_SC_007_no_inexact_variant_of_a_real_identifier_adds_anybody(
    portal_on: _FlagWorld,
) -> None:
    """Prefix, suffix, case, whitespace and path-shaped variants all add nobody."""

    _enable_cohort(portal_on)
    account_id = portal_on.member_me["id"]
    variants = [
        {"account_id": account_id[:-1]},
        {"account_id": account_id + "x"},
        {"account_id": account_id.upper()},
        {"account_id": f" {account_id} "},
        {"account_id": f"../users/{account_id}"},
        {"account_id": f"users/{account_id}"},
        {"account_id": f"{account_id}.json"},
        {"email": SECOND_USER_EMAIL[:-1]},
        {"email": SECOND_USER_EMAIL.upper()},
        {"email": f" {SECOND_USER_EMAIL} "},
    ]
    before = portal_on.document_bytes()

    for body in variants:
        response = portal_on.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json=body
        )
        assert response.status_code == 404, f"{body}: {response.text}"
        assert response.json()["message"] == "No account found."

    assert portal_on.document_bytes() == before
    listed = portal_on.operator.get(FLAGS_ROOT).json()
    assert _flag(listed, MANAGED)["selected_users"] == []


def test_010_FR_007_an_operator_style_address_without_a_dotted_domain_matches(
    portal_on: _FlagWorld,
) -> None:
    """`admin@localhost` is canonical here, so exact match must still find it.

    A pattern requiring a dotted domain would make a real (and possibly
    operator) account unselectable, the failure 009-FR-003 names explicitly.
    """

    local = portal_on.container.auth_service.seed_admin(
        email="admin@localhost", password=TEST_USER_PASSWORD
    )
    _enable_cohort(portal_on)

    added = portal_on.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"email": "admin@localhost"}
    )

    assert added.status_code == 200, added.text
    assert [
        member["account_id"]
        for member in _flag(added.json(), MANAGED)["selected_users"]
    ] == [local.id]


def test_010_SC_007_no_route_added_by_this_feature_can_enumerate_accounts(
    portal_on: _FlagWorld,
) -> None:
    """No new route lists or searches accounts; the cohort is the only listing."""

    paths = [
        path
        for path in portal_on.app.openapi()["paths"]
        if path.startswith("/api/admin")
    ]
    assert sorted(paths) == [
        "/api/admin/accounts/lookup",
        "/api/admin/accounts/{account_id}/revoke-sessions",
        "/api/admin/feature-flags",
        "/api/admin/feature-flags/{flag}",
        "/api/admin/feature-flags/{flag}/mode",
        "/api/admin/feature-flags/{flag}/selected-users",
        "/api/admin/feature-flags/{flag}/selected-users/{account_id}",
        "/api/admin/status",
    ]


# ---------------------------------------------------------------------------
# C3 — contract, idempotence and mode transitions
# ---------------------------------------------------------------------------


def test_010_FR_003_get_reports_exactly_the_two_managed_flags_with_dd3_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read reports DD-3's three independent fields and no unmanaged flag."""

    world = _build_world(
        tmp_path,
        monkeypatch,
        flags=(
            "admin_portal=on,delivery_canary=on,external_agent_relay=on,"
            "voice_brain_dump=internal,mobile_task_classification=off"
        ),
        subdir="dd3-data",
    )
    try:
        payload = world.operator.get(FLAGS_ROOT).json()
        assert payload["degraded"] is False
        assert [entry["name"] for entry in payload["flags"]] == [
            MANAGED,
            OTHER_MANAGED,
        ]

        inheriting = _flag(payload, MANAGED)
        assert inheriting["override_mode"] is None
        assert inheriting["source"] == "deploy_default"
        assert inheriting["deploy_default_state"] == "internal"

        world.operator.put(f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "off"})
        overridden = _flag(world.operator.get(FLAGS_ROOT).json(), MANAGED)
        assert overridden["override_mode"] == "off"
        assert overridden["source"] == "runtime"
        # Always present, even under an override, so the operator can see what
        # "Use deploy default" would fall back to before clicking it (DD-3).
        assert overridden["deploy_default_state"] == "internal"
    finally:
        _teardown(world, monkeypatch)


def test_010_SC_001_setting_each_mode_leaves_every_other_flag_untouched(
    portal_on: _FlagWorld,
) -> None:
    """Each mode round-trips and no other flag moves as a side effect."""

    for mode in ("off", "on", "selected_users"):
        response = portal_on.operator.put(
            f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": mode}
        )
        assert response.status_code == 200, response.text
        listed = portal_on.operator.get(FLAGS_ROOT).json()
        assert _flag(listed, MANAGED)["override_mode"] == mode
        assert _flag(listed, OTHER_MANAGED)["override_mode"] is None

    stored = json.loads(portal_on.document.read_text(encoding="utf-8"))
    assert set(stored) == {MANAGED}
    flags_payload = portal_on.member.get("/api/auth/me").json()["feature_flags"]
    assert set(flags_payload) == {
        "delivery_canary",
        "voice_brain_dump",
        "mobile_task_classification",
        "external_agent_relay",
    }


def test_010_FR_005_every_mutation_is_idempotent_and_returns_the_full_state(
    portal_on: _FlagWorld,
) -> None:
    """Repeating any mutation reports success and changes nothing."""

    _enable_cohort(portal_on)
    account_id = portal_on.member_me["id"]
    portal_on.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )
    after_add = portal_on.document_bytes()

    repeat_add = portal_on.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )
    assert repeat_add.status_code == 200
    assert portal_on.document_bytes() == after_add
    assert [entry["name"] for entry in repeat_add.json()["flags"]] == [
        MANAGED,
        OTHER_MANAGED,
    ]

    first_remove = portal_on.operator.delete(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}"
    )
    assert first_remove.status_code == 200
    after_remove = portal_on.document_bytes()
    second_remove = portal_on.operator.delete(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}"
    )
    assert second_remove.status_code == 200
    assert portal_on.document_bytes() == after_remove

    repeat_mode = portal_on.operator.put(
        f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "selected_users"}
    )
    assert repeat_mode.status_code == 200
    assert portal_on.document_bytes() == after_remove

    assert portal_on.operator.delete(f"{FLAGS_ROOT}/{MANAGED}").status_code == 200
    cleared = portal_on.document_bytes()
    assert portal_on.operator.delete(f"{FLAGS_ROOT}/{MANAGED}").status_code == 200
    assert portal_on.document_bytes() == cleared


def test_010_FR_002_a_malformed_mode_or_an_unknown_flag_is_refused(
    portal_on: _FlagWorld,
) -> None:
    """Bad modes and unmanaged flag names are refused with no partial write."""

    refused_flags = [
        "admin_portal",
        "delivery_canary",
        "external_agent_relay",
        "not_a_flag_at_all",
    ]
    for flag in refused_flags:
        assert (
            portal_on.operator.put(
                f"{FLAGS_ROOT}/{flag}/mode", json={"mode": "on"}
            ).status_code
            == 400
        )
        assert portal_on.operator.delete(f"{FLAGS_ROOT}/{flag}").status_code == 400
        assert (
            portal_on.operator.post(
                f"{FLAGS_ROOT}/{flag}/selected-users", json={"account_id": "user_x"}
            ).status_code
            == 400
        )
        assert (
            portal_on.operator.delete(
                f"{FLAGS_ROOT}/{flag}/selected-users/user_x"
            ).status_code
            == 400
        )

    assert (
        portal_on.operator.put(
            f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "sideways"}
        ).status_code
        == 422
    )
    assert portal_on.document_bytes() is None


def test_010_FR_010_a_cohort_survives_a_mode_round_trip_and_is_locked_meanwhile(
    portal_on: _FlagWorld,
) -> None:
    """`selected_users` → `on` → `selected_users` restores the exact cohort."""

    _enable_cohort(portal_on)
    account_id = portal_on.member_me["id"]
    portal_on.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )

    switched = portal_on.operator.put(
        f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "on"}
    )
    retained = _flag(switched.json(), MANAGED)
    assert retained["override_mode"] == "on"
    assert [member["account_id"] for member in retained["selected_users"]] == [
        account_id
    ]

    assert (
        portal_on.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
        ).status_code
        == 400
    )
    assert (
        portal_on.operator.delete(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}"
        ).status_code
        == 400
    )

    back = portal_on.operator.put(
        f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "selected_users"}
    )
    assert [
        member["account_id"] for member in _flag(back.json(), MANAGED)["selected_users"]
    ] == [account_id]


def test_010_FR_003_clearing_an_override_deletes_the_retained_cohort_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlike a mode change, clearing deletes the whole entry, cohort included."""

    world = _build_world(
        tmp_path,
        monkeypatch,
        flags="admin_portal=on,voice_brain_dump=internal",
        subdir="clear-data",
    )
    try:
        _enable_cohort(world)
        world.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users",
            json={"account_id": world.member_me["id"]},
        )

        cleared = world.operator.delete(f"{FLAGS_ROOT}/{MANAGED}")
        assert cleared.status_code == 200, cleared.text
        entry = _flag(cleared.json(), MANAGED)
        assert entry["override_mode"] is None
        assert entry["source"] == "deploy_default"
        assert entry["deploy_default_state"] == "internal"
        assert entry["selected_users"] == []

        reread = _flag(world.operator.get(FLAGS_ROOT).json(), MANAGED)
        assert reread["override_mode"] is None
        assert reread["selected_users"] == []
        assert MANAGED not in json.loads(world.document.read_text(encoding="utf-8"))
    finally:
        _teardown(world, monkeypatch)


# ---------------------------------------------------------------------------
# C3a — route-level persistence-failure evidence
# ---------------------------------------------------------------------------


def test_010_SC_005_a_failed_write_surfaces_a_5xx_and_changes_nothing(
    portal_on: _FlagWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A route never reports success for a write the repository could not make."""

    assert (
        portal_on.operator.put(
            f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "on"}
        ).status_code
        == 200
    )
    before = portal_on.document_bytes()

    def _explode(*args: Any, **kwargs: Any) -> None:
        raise RepositoryError("the write path is unavailable")

    monkeypatch.setattr("app.repositories.feature_flag.atomic_write", _explode)

    failed = portal_on.operator.put(
        f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "off"}
    )
    assert failed.status_code >= 500, failed.text

    monkeypatch.undo()
    assert portal_on.document_bytes() == before
    assert (
        _flag(portal_on.operator.get(FLAGS_ROOT).json(), MANAGED)["override_mode"]
        == "on"
    )


# ---------------------------------------------------------------------------
# C4 — an unresolvable cohort entry
# ---------------------------------------------------------------------------


def test_010_SC_007_an_unresolvable_stored_id_still_renders_and_is_removable(
    portal_on: _FlagWorld,
) -> None:
    """A stored ID resolving to no account is listed with a null email."""

    _enable_cohort(portal_on)
    portal_on.container.feature_flag_repo.mutate(
        lambda current: {
            **current,
            MANAGED: FlagOverride(
                mode=FlagMode.SELECTED_USERS, selected_users=("user_long_gone",)
            ),
        }
    )

    listed = _flag(portal_on.operator.get(FLAGS_ROOT).json(), MANAGED)
    assert listed["selected_users"] == [{"account_id": "user_long_gone", "email": None}]

    removed = portal_on.operator.delete(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users/user_long_gone"
    )
    assert removed.status_code == 200, removed.text
    assert _flag(removed.json(), MANAGED)["selected_users"] == []


# ---------------------------------------------------------------------------
# C5 — member-visible effect and purge
# ---------------------------------------------------------------------------


def test_010_SC_002_a_cohort_change_is_visible_on_the_next_me_without_a_signout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selecting and unselecting an account flips its `/auth/me` flag only."""

    world = _build_world(
        tmp_path,
        monkeypatch,
        flags="admin_portal=on,voice_brain_dump=off",
        subdir="member-data",
    )
    try:
        _enable_cohort(world)
        account_id = world.member_me["id"]
        world.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
        )

        assert world.member.get("/api/auth/me").json()["feature_flags"][MANAGED] is True
        assert (
            world.operator.get("/api/auth/me").json()["feature_flags"][MANAGED] is False
        )

        world.operator.delete(f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}")

        after = world.member.get("/api/auth/me")
        assert after.status_code == 200, after.text
        assert after.json()["feature_flags"][MANAGED] is False
    finally:
        _teardown(world, monkeypatch)


def test_010_SC_002_purging_an_account_removes_its_id_from_the_cohort(
    portal_on: _FlagWorld,
) -> None:
    """`AccountService.purge_account` scrubs the cohort before deleting (DD-9)."""

    _enable_cohort(portal_on)
    account_id = portal_on.member_me["id"]
    portal_on.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )

    portal_on.container.account_service.purge_account(account_id)

    listed = _flag(portal_on.operator.get(FLAGS_ROOT).json(), MANAGED)
    assert listed["selected_users"] == []
    assert account_id not in portal_on.document.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# C6 — auditability
# ---------------------------------------------------------------------------


def test_010_SC_006_each_mutation_route_emits_exactly_one_dedicated_record(
    portal_on: _FlagWorld, caplog: pytest.LogCaptureFixture
) -> None:
    """One content-free record per mutation, and one aggregate per read."""

    _enable_cohort(portal_on)
    account_id = portal_on.member_me["id"]

    caplog.clear()
    with caplog.at_level(logging.INFO):
        portal_on.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
        )
        portal_on.operator.delete(f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}")
        portal_on.operator.put(f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "off"})
        portal_on.operator.delete(f"{FLAGS_ROOT}/{MANAGED}")
        portal_on.operator.get(FLAGS_ROOT)

    ours = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(ours) == 5
    assert sum("action=add_selected_user" in m for m in ours) == 1
    assert sum("action=remove_selected_user" in m for m in ours) == 1
    assert sum("action=set_mode" in m for m in ours) == 1
    assert sum("action=clear_override" in m for m in ours) == 1
    assert sum("Runtime flag read" in m for m in ours) == 1
    for message in ours:
        assert SECOND_USER_EMAIL not in message

    # 009's own lookup record still fires, unconditionally, for the add — and
    # deliberately does **not** fire for the GET's cohort-email resolution.
    lookups = [r.getMessage() for r in caplog.records if r.name == ADMIN_SERVICE_LOGGER]
    assert len(lookups) == 1
    assert "Admin lookup" in lookups[0]


def test_010_FR_006_the_get_read_emits_one_aggregate_record_per_call(
    portal_on: _FlagWorld, caplog: pytest.LogCaptureFixture
) -> None:
    """A cohort-resolving read never writes one lookup record per member."""

    _enable_cohort(portal_on)
    portal_on.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users",
        json={"account_id": portal_on.member_me["id"]},
    )

    caplog.clear()
    with caplog.at_level(logging.INFO):
        portal_on.operator.get(FLAGS_ROOT)

    ours = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(ours) == 1
    assert "flags=2" in ours[0]
    assert "resolved_accounts=1" in ours[0]
    assert [r for r in caplog.records if r.name == ADMIN_SERVICE_LOGGER] == []


# ---------------------------------------------------------------------------
# C7 — application-level restart evidence
# ---------------------------------------------------------------------------


def test_010_SC_001_state_survives_a_fresh_application_over_the_same_volume(
    portal_on: _FlagWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh FastAPI application over the same data dir sees the same state."""

    _enable_cohort(portal_on)
    account_id = portal_on.member_me["id"]
    portal_on.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )
    portal_on.operator.put(f"{FLAGS_ROOT}/{OTHER_MANAGED}/mode", json={"mode": "on"})

    get_config.cache_clear()
    restarted = create_app()
    client = BrainBuddyTestClient(restarted)
    try:
        signed_in = client.post(
            "/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
        )
        assert signed_in.status_code == 200, signed_in.text
        payload = client.get(FLAGS_ROOT).json()
        assert _flag(payload, MANAGED)["override_mode"] == "selected_users"
        assert [
            member["account_id"] for member in _flag(payload, MANAGED)["selected_users"]
        ] == [account_id]
        assert _flag(payload, OTHER_MANAGED)["override_mode"] == "on"
    finally:
        client.close()


# ---------------------------------------------------------------------------
# C8 — request-to-document privacy sentinel
# ---------------------------------------------------------------------------


def test_010_SC_007_no_request_content_ever_reaches_the_stored_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real add through the route stores the ID and nothing else."""

    world = _build_world(tmp_path, monkeypatch, flags="admin_portal=on", subdir="pii")
    try:
        sentinel_email = f"{EMAIL_SENTINEL_LOCAL}@example.com"
        client, me = _signup(
            world.app, email=sentinel_email, password=TEST_USER_PASSWORD
        )
        stored = world.container.user_repo.get_by_id(me["id"])
        assert stored is not None
        world.container.user_repo.save(
            stored.model_copy(update={"display_name": DISPLAY_NAME_SENTINEL})
        )

        _enable_cohort(world)
        added = world.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"email": sentinel_email}
        )
        assert added.status_code == 200, added.text

        raw = world.document.read_text(encoding="utf-8")
        assert me["id"] in raw
        assert DISPLAY_NAME_SENTINEL not in raw
        assert EMAIL_SENTINEL_LOCAL not in raw
        assert "@" not in raw
        client.close()
    finally:
        _teardown(world, monkeypatch)


# ---------------------------------------------------------------------------
# Degraded store at the route boundary (010-FR-004, 010-SC-008)
# ---------------------------------------------------------------------------


def test_010_SC_008_a_degraded_store_reports_degraded_and_refuses_every_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded read is a successful 200 saying so; every mutation is refused."""

    world = _build_world(
        tmp_path,
        monkeypatch,
        flags="admin_portal=on,voice_brain_dump=on",
        subdir="degraded",
    )
    try:
        world.document.parent.mkdir(parents=True, exist_ok=True)
        world.document.write_text("{not json at all", encoding="utf-8")
        before = world.document_bytes()

        listed = world.operator.get(FLAGS_ROOT)
        assert listed.status_code == 200, listed.text
        assert listed.json()["degraded"] is True

        for method, path, body in _all_five_routes(world.member_me["id"])[1:]:
            response = _call(world.operator, method, path, body)
            assert response.status_code == 503, f"{method} {path}: {response.text}"

        assert world.document_bytes() == before
        # Every flag still resolves from the deploy baseline while degraded.
        assert world.member.get("/api/auth/me").json()["feature_flags"][MANAGED] is True
    finally:
        _teardown(world, monkeypatch)
