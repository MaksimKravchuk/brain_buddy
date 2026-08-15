"""The four `/api/admin/feature-flags` routes behind feature 009's gate.

ADR-0019 (2026-08-15) deleted `admin_portal` as a feature flag entirely
(DD-14): the Admin Portal is always reachable by an authenticated,
allow-listed operator, with no flag layered on top. It also deleted the
`DELETE /feature-flags/{flag}` clear-override route (DD-3, DD-15) — a managed
flag's stored mode is the entire answer, so there is nothing left to "clear
back to a deploy default". These tests target that boundary directly.

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core import get_config
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
RELAY = "external_agent_relay"
THIRD_MANAGED_FLAG_NAMES = frozenset({MANAGED, OTHER_MANAGED, RELAY})

SERVICE_LOGGER = "app.services.feature_flag_service"
ADMIN_SERVICE_LOGGER = "app.services.admin_service"

#: Planted in the target account's display name and in the request body so the
#: stored-row-bytes assertion fails loudly if member content ever lands there.
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

    def snapshot(self) -> Any:
        """The store's current flags, for before/after no-write assertions."""

        return self.container.feature_flag_repo.read().flags

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
def world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[_FlagWorld, None, None]:
    """An app with an authenticated operator, member and anonymous client.

    There is no more `admin_portal` flag to stage one way or the other
    (ADR-0019, DD-14): every route behind `require_operator` is reachable to
    an allow-listed operator regardless of any `BRAIN_BUDDY_FEATURE_FLAGS`
    entry.
    """

    w = _build_world(tmp_path, monkeypatch, flags="delivery_canary=internal")
    yield w
    _teardown(w, monkeypatch)


def _all_four_routes(account_id: str) -> list[tuple[str, str, dict | None]]:
    """The one read plus the three mutations — DD-3/DD-15 dropped the
    `DELETE /feature-flags/{flag}` clear-override route, so the count is four,
    not the pre-correction five."""

    return [
        ("GET", FLAGS_ROOT, None),
        ("PUT", f"{FLAGS_ROOT}/{MANAGED}/mode", {"mode": "on"}),
        ("POST", f"{FLAGS_ROOT}/{MANAGED}/selected-users", {"account_id": account_id}),
        ("DELETE", f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}", None),
    ]


def _call(client: TestClient, method: str, path: str, body: dict | None):
    return client.request(method, path, json=body)


def _poison(world: _FlagWorld) -> None:
    """Make every target-facing service and repository method fail loudly.

    A denial must be decided before any of them is consulted, on all four
    routes including `GET` (010-FR-006). Comparing response bodies alone would
    not catch a read that happened and was then discarded.
    """

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a denied request must not touch the runtime store")

    for name in ("describe", "set_mode", "add_selected_user", "remove_selected_user"):
        setattr(world.container.feature_flag_service, name, _explode)
    for name in ("read", "mutate", "scrub_user"):
        setattr(world.container.feature_flag_repo, name, _explode)


def _flag(payload: dict, name: str) -> dict:
    return next(entry for entry in payload["flags"] if entry["name"] == name)


def _enable_cohort(world: _FlagWorld, flag: str = MANAGED) -> None:
    response = world.operator.put(
        f"{FLAGS_ROOT}/{flag}/mode", json={"mode": "selected_users"}
    )
    assert response.status_code == 200, response.text


def _raw_store_rows(world: _FlagWorld) -> str:
    """Every stored row, concatenated, for a privacy-shape sentinel check."""

    with sqlite3.connect(world.container.feature_flag_repo.db_path) as conn:
        return "".join(str(row) for row in conn.execute("SELECT * FROM feature_flags"))


# ---------------------------------------------------------------------------
# C1 — authorization on all four routes, GET included
# ---------------------------------------------------------------------------


def test_010_FR_006_every_route_answers_401_unauthenticated(world: _FlagWorld) -> None:
    """All four routes reject an unauthenticated caller with 401."""

    _poison(world)
    for method, path, body in _all_four_routes(world.member_me["id"]):
        response = _call(world.anonymous, method, path, body)
        assert response.status_code == 401, f"{method} {path}: {response.text}"


def test_010_SC_006_every_route_answers_403_to_a_non_operator(
    world: _FlagWorld,
) -> None:
    """A non-operator gets 403 on every route."""

    _poison(world)
    for method, path, body in _all_four_routes(world.member_me["id"]):
        response = _call(world.member, method, path, body)
        assert response.status_code == 403, f"{method} {path}: {response.text}"


def test_010_DD_14_an_operator_reaches_every_managed_flag_route(
    world: _FlagWorld,
) -> None:
    """An authorized operator always reaches `/admin/feature-flags` — there is
    no flag left that could hide it (DD-14)."""

    for method, path, body in _all_four_routes(world.member_me["id"]):
        response = _call(world.operator, method, path, body)
        assert response.status_code != 404, f"{method} {path}: {response.text}"


def test_010_FR_006_a_denial_introduces_no_new_log_record_type(
    world: _FlagWorld, caplog: pytest.LogCaptureFixture
) -> None:
    """A 401/403 denial keeps 009's own records and adds none of this feature's."""

    caplog.clear()
    with caplog.at_level(logging.INFO):
        world.member.get(FLAGS_ROOT)
        world.anonymous.get(FLAGS_ROOT)

    assert [r for r in caplog.records if r.name == SERVICE_LOGGER] == []
    denials = [r for r in caplog.records if r.name == "app.api.dependencies"]
    assert len(denials) == 2


# ---------------------------------------------------------------------------
# C2 — exact-match add
# ---------------------------------------------------------------------------


def test_010_FR_007_add_accepts_an_exact_account_id_and_an_exact_email(
    world: _FlagWorld,
) -> None:
    """Adding by exact account ID and by exact canonical email both succeed."""

    _enable_cohort(world)
    by_id = world.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users",
        json={"account_id": world.member_me["id"]},
    )
    assert by_id.status_code == 200, by_id.text
    assert [
        member["account_id"]
        for member in _flag(by_id.json(), MANAGED)["selected_users"]
    ] == [world.member_me["id"]]

    _enable_cohort(world, OTHER_MANAGED)
    by_email = world.operator.post(
        f"{FLAGS_ROOT}/{OTHER_MANAGED}/selected-users",
        json={"email": SECOND_USER_EMAIL},
    )
    assert by_email.status_code == 200, by_email.text
    assert [
        member["account_id"]
        for member in _flag(by_email.json(), OTHER_MANAGED)["selected_users"]
    ] == [world.member_me["id"]]


def test_010_SC_007_no_inexact_variant_of_a_real_identifier_adds_anybody(
    world: _FlagWorld,
) -> None:
    """Prefix, suffix, case, whitespace and path-shaped variants all add nobody."""

    _enable_cohort(world)
    account_id = world.member_me["id"]
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
    before = world.snapshot()

    for body in variants:
        response = world.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json=body
        )
        assert response.status_code == 404, f"{body}: {response.text}"
        assert response.json()["message"] == "No account found."

    assert world.snapshot() == before
    listed = world.operator.get(FLAGS_ROOT).json()
    assert _flag(listed, MANAGED)["selected_users"] == []


def test_010_FR_007_an_operator_style_address_without_a_dotted_domain_matches(
    world: _FlagWorld,
) -> None:
    """`admin@localhost` is canonical here, so exact match must still find it.

    A pattern requiring a dotted domain would make a real (and possibly
    operator) account unselectable, the failure 009-FR-003 names explicitly.
    """

    local = world.container.auth_service.seed_admin(
        email="admin@localhost", password=TEST_USER_PASSWORD
    )
    _enable_cohort(world)

    added = world.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"email": "admin@localhost"}
    )

    assert added.status_code == 200, added.text
    assert [
        member["account_id"]
        for member in _flag(added.json(), MANAGED)["selected_users"]
    ] == [local.id]


def test_010_SC_007_no_route_added_by_this_feature_can_enumerate_accounts(
    world: _FlagWorld,
) -> None:
    """No new route lists or searches accounts; the cohort is the only listing."""

    paths = [
        path for path in world.app.openapi()["paths"] if path.startswith("/api/admin")
    ]
    assert sorted(paths) == [
        "/api/admin/accounts/lookup",
        "/api/admin/accounts/{account_id}/revoke-sessions",
        "/api/admin/feature-flags",
        "/api/admin/feature-flags/{flag}/mode",
        "/api/admin/feature-flags/{flag}/selected-users",
        "/api/admin/feature-flags/{flag}/selected-users/{account_id}",
        "/api/admin/status",
    ]


# ---------------------------------------------------------------------------
# C3 — contract, idempotence and mode transitions
# ---------------------------------------------------------------------------


def test_010_SC_001_setting_each_mode_leaves_every_other_flag_untouched(
    world: _FlagWorld,
) -> None:
    """Each mode round-trips and no other managed flag moves as a side effect."""

    for mode in ("off", "on", "selected_users"):
        response = world.operator.put(
            f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": mode}
        )
        assert response.status_code == 200, response.text
        listed = world.operator.get(FLAGS_ROOT).json()
        assert _flag(listed, MANAGED)["mode"] == mode
        assert _flag(listed, OTHER_MANAGED)["mode"] == "off"

    flags_payload = world.member.get("/api/auth/me").json()["feature_flags"]
    assert set(flags_payload) == {
        "delivery_canary",
        "voice_brain_dump",
        "mobile_task_classification",
        "external_agent_relay",
    }


def test_010_FR_005_every_mutation_is_idempotent_and_returns_the_full_state(
    world: _FlagWorld,
) -> None:
    """Repeating any mutation reports success and changes nothing."""

    _enable_cohort(world)
    account_id = world.member_me["id"]
    world.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )
    after_add = world.snapshot()

    repeat_add = world.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )
    assert repeat_add.status_code == 200
    assert world.snapshot() == after_add
    assert {entry["name"] for entry in repeat_add.json()["flags"]} == (
        THIRD_MANAGED_FLAG_NAMES
    )

    first_remove = world.operator.delete(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}"
    )
    assert first_remove.status_code == 200
    after_remove = world.snapshot()
    second_remove = world.operator.delete(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}"
    )
    assert second_remove.status_code == 200
    assert world.snapshot() == after_remove

    repeat_mode = world.operator.put(
        f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "selected_users"}
    )
    assert repeat_mode.status_code == 200
    assert world.snapshot() == after_remove


def test_010_FR_002_a_malformed_mode_is_refused_with_no_partial_write(
    world: _FlagWorld,
) -> None:
    """An unknown mode value is refused at the schema boundary with no write."""

    before = world.snapshot()

    assert (
        world.operator.put(
            f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "sideways"}
        ).status_code
        == 422
    )

    assert world.snapshot() == before


@pytest.mark.parametrize("flag", ["admin_portal", "delivery_canary", "not_a_real_flag"])
def test_010_FR_002_admin_portal_delivery_canary_and_unknown_are_refused(
    world: _FlagWorld, flag: str
) -> None:
    """A mutation naming `admin_portal`, `delivery_canary` or an undeclared
    name is refused as an ordinary undeclared name — `admin_portal` gets no
    distinct code path any more, since it is not a configurable name at all
    (DD-1, DD-14)."""

    before = world.snapshot()

    response = world.operator.put(f"{FLAGS_ROOT}/{flag}/mode", json={"mode": "on"})

    assert response.status_code in (400, 422), f"{flag}: {response.text}"
    assert world.snapshot() == before


def test_010_FR_010_a_cohort_survives_a_mode_round_trip_and_is_locked_meanwhile(
    world: _FlagWorld,
) -> None:
    """`selected_users` → `on` → `selected_users` restores the exact cohort."""

    _enable_cohort(world)
    account_id = world.member_me["id"]
    world.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )

    switched = world.operator.put(f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "on"})
    retained = _flag(switched.json(), MANAGED)
    assert retained["mode"] == "on"
    assert [member["account_id"] for member in retained["selected_users"]] == [
        account_id
    ]

    assert (
        world.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
        ).status_code
        == 400
    )
    assert (
        world.operator.delete(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}"
        ).status_code
        == 400
    )

    back = world.operator.put(
        f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "selected_users"}
    )
    assert [
        member["account_id"] for member in _flag(back.json(), MANAGED)["selected_users"]
    ] == [account_id]


def test_010_DD_15_get_reports_exactly_the_three_managed_flags_mode_always_present(
    world: _FlagWorld,
) -> None:
    """`GET` reports exactly the three managed flags — `external_agent_relay`
    included — each with a `mode` field always present (never null, and never
    the retired `override_mode`/`source`/`deploy_default_state` fields), since
    there is no more inheritance state to represent (DD-3, DD-15)."""

    payload = world.operator.get(FLAGS_ROOT).json()

    names = {entry["name"] for entry in payload["flags"]}
    assert names == THIRD_MANAGED_FLAG_NAMES

    for entry in payload["flags"]:
        assert "mode" in entry
        assert entry["mode"] in {"off", "on", "selected_users"}
        assert "override_mode" not in entry
        assert "source" not in entry
        assert "deploy_default_state" not in entry


def test_010_DD_15_clear_override_route_is_removed_entirely(world: _FlagWorld) -> None:
    """There is no more `DELETE /feature-flags/{flag}` clear-override route
    (DD-3): it must not appear in the OpenAPI schema, and calling it must not
    behave as a working mutation the operator could still rely on."""

    paths = world.app.openapi()["paths"]
    assert f"{FLAGS_ROOT}/{{flag}}" not in paths

    response = world.operator.delete(f"{FLAGS_ROOT}/{MANAGED}")
    assert response.status_code in (404, 405), response.text


def test_010_FR_010_every_mutation_response_is_the_servers_own_authoritative_state(
    world: _FlagWorld,
) -> None:
    """Every mutation returns the server's own post-mutation state, across all
    three managed flags including `external_agent_relay` — the screen must
    re-render from this, never optimistic local state (010-FR-010)."""

    mutated = world.operator.put(f"{FLAGS_ROOT}/{RELAY}/mode", json={"mode": "on"})
    assert mutated.status_code == 200, mutated.text

    server_state = world.operator.get(FLAGS_ROOT).json()
    assert mutated.json() == server_state
    assert _flag(server_state, RELAY)["mode"] == "on"


# ---------------------------------------------------------------------------
# C3a — route-level persistence-failure evidence
# ---------------------------------------------------------------------------


def test_010_SC_005_a_failed_write_surfaces_a_5xx_and_changes_nothing(
    world: _FlagWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A route never reports success for a write the repository could not make."""

    assert (
        world.operator.put(
            f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "on"}
        ).status_code
        == 200
    )
    before = world.snapshot()

    class _FailingConnection(sqlite3.Connection):
        """`sqlite3.Connection.execute` is a read-only slot on the instance,
        so the mid-transaction failure is injected via a `factory=` subclass
        rather than monkeypatching the instance."""

        def execute(self, sql: str, *params: object) -> sqlite3.Cursor:
            if sql.strip().upper().startswith("BEGIN IMMEDIATE"):
                raise sqlite3.OperationalError("disk full")
            return super().execute(sql, *params)

    original_connect = sqlite3.connect

    def _explode(*args: object, **kwargs: object) -> sqlite3.Connection:
        kwargs["factory"] = _FailingConnection
        return original_connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sqlite3, "connect", _explode)

    failed = world.operator.put(f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "off"})
    assert failed.status_code >= 500, failed.text

    monkeypatch.undo()
    assert world.snapshot() == before
    assert _flag(world.operator.get(FLAGS_ROOT).json(), MANAGED)["mode"] == "on"


# ---------------------------------------------------------------------------
# C4 — an unresolvable cohort entry
# ---------------------------------------------------------------------------


def test_010_SC_007_an_unresolvable_stored_id_still_renders_and_is_removable(
    world: _FlagWorld,
) -> None:
    """A stored ID resolving to no account is listed with a null email."""

    _enable_cohort(world)
    world.container.feature_flag_repo.mutate(
        lambda current: {
            **current,
            MANAGED: FlagOverride(
                mode=FlagMode.SELECTED_USERS, selected_users=("user_long_gone",)
            ),
        }
    )

    listed = _flag(world.operator.get(FLAGS_ROOT).json(), MANAGED)
    assert listed["selected_users"] == [{"account_id": "user_long_gone", "email": None}]

    removed = world.operator.delete(
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

    w = _build_world(
        tmp_path, monkeypatch, flags="voice_brain_dump=off", subdir="member-data"
    )
    try:
        _enable_cohort(w)
        account_id = w.member_me["id"]
        w.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
        )

        assert w.member.get("/api/auth/me").json()["feature_flags"][MANAGED] is True
        assert w.operator.get("/api/auth/me").json()["feature_flags"][MANAGED] is False

        w.operator.delete(f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}")

        after = w.member.get("/api/auth/me")
        assert after.status_code == 200, after.text
        assert after.json()["feature_flags"][MANAGED] is False
    finally:
        _teardown(w, monkeypatch)


def test_010_SC_002_purging_an_account_removes_its_id_from_the_cohort(
    world: _FlagWorld,
) -> None:
    """`AccountService.purge_account` scrubs the cohort before deleting (DD-9)."""

    _enable_cohort(world)
    account_id = world.member_me["id"]
    world.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )

    world.container.account_service.purge_account(account_id)

    listed = _flag(world.operator.get(FLAGS_ROOT).json(), MANAGED)
    assert listed["selected_users"] == []
    assert account_id not in _raw_store_rows(world)


# ---------------------------------------------------------------------------
# C6 — auditability
# ---------------------------------------------------------------------------


def test_010_SC_006_each_mutation_route_emits_exactly_one_dedicated_record(
    world: _FlagWorld, caplog: pytest.LogCaptureFixture
) -> None:
    """One content-free record per mutation, and one aggregate per read."""

    _enable_cohort(world)
    account_id = world.member_me["id"]

    caplog.clear()
    with caplog.at_level(logging.INFO):
        world.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
        )
        world.operator.delete(f"{FLAGS_ROOT}/{MANAGED}/selected-users/{account_id}")
        world.operator.put(f"{FLAGS_ROOT}/{MANAGED}/mode", json={"mode": "off"})
        world.operator.get(FLAGS_ROOT)

    ours = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(ours) == 4
    assert sum("action=add_selected_user" in m for m in ours) == 1
    assert sum("action=remove_selected_user" in m for m in ours) == 1
    assert sum("action=set_mode" in m for m in ours) == 1
    assert sum("Runtime flag read" in m for m in ours) == 1
    for message in ours:
        assert SECOND_USER_EMAIL not in message

    # 009's own lookup record still fires, unconditionally, for the add — and
    # deliberately does **not** fire for the GET's cohort-email resolution.
    lookups = [r.getMessage() for r in caplog.records if r.name == ADMIN_SERVICE_LOGGER]
    assert len(lookups) == 1
    assert "Admin lookup" in lookups[0]


def test_010_FR_006_the_get_read_emits_one_aggregate_record_per_call(
    world: _FlagWorld, caplog: pytest.LogCaptureFixture
) -> None:
    """A cohort-resolving read never writes one lookup record per member."""

    _enable_cohort(world)
    world.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users",
        json={"account_id": world.member_me["id"]},
    )

    caplog.clear()
    with caplog.at_level(logging.INFO):
        world.operator.get(FLAGS_ROOT)

    ours = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(ours) == 1
    assert "flags=3" in ours[0]
    assert "resolved_accounts=1" in ours[0]
    assert [r for r in caplog.records if r.name == ADMIN_SERVICE_LOGGER] == []


# ---------------------------------------------------------------------------
# C7 — application-level restart evidence
# ---------------------------------------------------------------------------


def test_010_SC_001_state_survives_a_fresh_application_over_the_same_volume(
    world: _FlagWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh FastAPI application over the same data dir sees the same state."""

    _enable_cohort(world)
    account_id = world.member_me["id"]
    world.operator.post(
        f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"account_id": account_id}
    )
    world.operator.put(f"{FLAGS_ROOT}/{OTHER_MANAGED}/mode", json={"mode": "on"})

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
        assert _flag(payload, MANAGED)["mode"] == "selected_users"
        assert [
            member["account_id"] for member in _flag(payload, MANAGED)["selected_users"]
        ] == [account_id]
        assert _flag(payload, OTHER_MANAGED)["mode"] == "on"
    finally:
        client.close()


# ---------------------------------------------------------------------------
# C8 — request-to-store privacy sentinel
# ---------------------------------------------------------------------------


def test_010_SC_007_no_request_content_ever_reaches_the_stored_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real add through the route stores the ID and nothing else."""

    w = _build_world(
        tmp_path, monkeypatch, flags="delivery_canary=internal", subdir="pii"
    )
    try:
        sentinel_email = f"{EMAIL_SENTINEL_LOCAL}@example.com"
        client, me = _signup(w.app, email=sentinel_email, password=TEST_USER_PASSWORD)
        stored = w.container.user_repo.get_by_id(me["id"])
        assert stored is not None
        w.container.user_repo.save(
            stored.model_copy(update={"display_name": DISPLAY_NAME_SENTINEL})
        )

        _enable_cohort(w)
        added = w.operator.post(
            f"{FLAGS_ROOT}/{MANAGED}/selected-users", json={"email": sentinel_email}
        )
        assert added.status_code == 200, added.text

        raw = _raw_store_rows(w)
        assert me["id"] in raw
        assert DISPLAY_NAME_SENTINEL not in raw
        assert EMAIL_SENTINEL_LOCAL not in raw
        assert "@" not in raw
        client.close()
    finally:
        _teardown(w, monkeypatch)


# ---------------------------------------------------------------------------
# Degraded store at the route boundary (010-FR-004, 010-SC-008)
# ---------------------------------------------------------------------------


def test_010_SC_008_a_degraded_store_reports_degraded_and_refuses_every_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded read is a successful 200 saying so; every mutation is refused."""

    w = _build_world(
        tmp_path, monkeypatch, flags="voice_brain_dump=on", subdir="degraded"
    )
    try:
        with sqlite3.connect(w.container.feature_flag_repo.db_path) as conn:
            conn.execute(
                "UPDATE feature_flags SET mode = ? WHERE flag = ?",
                ("sideways", MANAGED),
            )
            conn.commit()

        listed = w.operator.get(FLAGS_ROOT)
        assert listed.status_code == 200, listed.text
        assert listed.json()["degraded"] is True

        for method, path, body in _all_four_routes(w.member_me["id"])[1:]:
            response = _call(w.operator, method, path, body)
            assert response.status_code == 503, f"{method} {path}: {response.text}"

        # A degraded store resolves every managed flag ineffective for
        # everyone — there is no environment fallback left post-migration
        # (DD-2, DD-15).
        assert w.member.get("/api/auth/me").json()["feature_flags"][MANAGED] is False
    finally:
        _teardown(w, monkeypatch)
