"""A CLI grant issues one distinct session under the shared Identity authority."""

import asyncio
import json
import multiprocessing
import re
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta

import allure
import pytest

from app.exceptions import RepositoryError, StorageUnavailableError
from app.repositories.cli_auth import CliAuthRepository
from app.repositories.feature_flag import FlagMode, FlagOverride
from app.services.cli_auth import CliAuthError, CliAuthService
from app.utils.time import utcnow

pytestmark = [
    allure.epic("Authentication & Access"),
    allure.feature("CLI authorization"),
    allure.story("Explicit browser approval and one-time session exchange"),
]


@pytest.fixture
def live_cli(api_client):
    container = api_client.app.state.container
    config = api_client.app.state.config.model_copy(
        update={"cli_verification_origin": "https://app.example.com"}
    )
    api_client.app.state.config = config
    container.cli_auth_service = CliAuthService(
        auth_service=container.auth_service,
        feature_flags=container.feature_flag_service,
        origin=config.cli_verification_origin,
    )
    container.feature_flag_repo.mutate(
        lambda flags: flags | {"cli_auth": FlagOverride(mode=FlagMode.ON)}
    )
    return api_client, container.cli_auth_service


def approve(client, grant):
    return client.post(
        "/api/auth/device/decision",
        json={"user_code": grant["user_code"], "decision": "approve"},
        headers={"Origin": "https://app.example.com"},
    )


def test_024_FR_013_014_SC_004_approval_mints_distinct_session_once(live_cli):
    client, service = live_cli
    source = client.cookies.get(client.app.state.config.session.cookie_name)
    grant = client.post("/api/auth/device/start", json={}).json()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", grant["device_code"])
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", grant["user_code"])
    assert grant["expires_in"] == 600 and grant["interval"] == 5
    assert grant["verification_uri_complete"].endswith(
        "#user_code=" + grant["user_code"]
    )
    assert approve(client, grant).status_code == 200
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    issued = client.post(
        "/api/auth/device/token", json={"device_code": grant["device_code"]}
    )
    assert issued.status_code == 200
    assert issued.json()["account"]["id"] == client.get("/api/auth/me").json()["id"]
    assert client.cookies.get(issued.json()["cookie_name"]) != source
    assert "HttpOnly" in issued.headers["set-cookie"]
    assert "token" not in issued.text and grant["device_code"] not in issued.text
    replay = client.post(
        "/api/auth/device/token", json={"device_code": grant["device_code"]}
    )
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "authorization_consumed"


def test_024_FR_013_poll_rate_state_commits_across_restart(live_cli):
    _, service = live_cli
    grant = service.start()
    for expected in ["slow_down", "slow_down"]:
        with pytest.raises(CliAuthError, match=expected):
            service.token(grant["device_code"])
    restarted = CliAuthService(
        auth_service=service.auth, feature_flags=service.flags, origin=service.origin
    )
    with service.repo.store.connection() as connection:
        row = connection.execute("SELECT interval FROM cli_device_grants").fetchone()
    assert row["interval"] == 15
    with pytest.raises(CliAuthError, match="slow_down"):
        restarted.token(grant["device_code"])


@pytest.mark.parametrize("origin", [None, "null", "https://foreign.example"])
def test_024_FR_013_foreign_origin_never_decides(live_cli, origin):
    client, _ = live_cli
    grant = client.post("/api/auth/device/start", json={}).json()
    response = client.post(
        "/api/auth/device/decision",
        json={"user_code": grant["user_code"], "decision": "approve"},
        headers={} if origin is None else {"Origin": origin},
    )
    assert response.status_code == 403
    assert grant["user_code"] not in response.text
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "body",
    [
        b'{"device_code":"private-sentinel","extra":1}',
        b'{"device_code":["private-sentinel"]}',
        b"{private-sentinel",
        b" " * 1025,
    ],
)
def test_024_FR_010_013_bounded_nonreflecting_body(live_cli, body):
    client, _ = live_cli
    response = client.post(
        "/api/auth/device/token",
        content=body,
        headers={"Content-Type": "application/json", "Content-Length": "1"},
    )
    assert response.status_code in {413, 422}
    assert "private-sentinel" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_024_FR_013_source_logout_blocks_exchange(live_cli):
    client, service = live_cli
    grant = service.start()
    assert approve(client, grant).status_code == 200
    client.post("/api/auth/logout")
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    with pytest.raises(CliAuthError):
        service.token(grant["device_code"])
    with service.repo.store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_024_FR_013_expired_grants_are_erased_even_off(live_cli):
    client, service = live_cli
    grant = service.start()
    approve(client, grant)
    service.flags.repository.mutate(
        lambda flags: flags | {"cli_auth": FlagOverride(mode=FlagMode.OFF)}
    )
    service.clock = lambda: utcnow() + timedelta(seconds=601)
    assert service.cleanup() == 1
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM cli_device_grants").fetchone()[0]
            == 0
        )


def test_024_FR_013_private_proof_and_short_code_are_hashed(live_cli):
    _, service = live_cli
    grant = service.start()
    with service.repo.store.connection() as connection:
        encoded = json.dumps(
            dict(connection.execute("SELECT * FROM cli_device_grants").fetchone())
        )
    assert grant["device_code"] not in encoded
    assert grant["user_code"].replace("-", "") not in encoded


def test_024_FR_013_issuance_failure_rolls_back_session_and_consumption(
    live_cli, monkeypatch
):
    client, service = live_cli
    grant = service.start()
    assert approve(client, grant).status_code == 200
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    original = service.auth._create_session

    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic failure before commit")

    monkeypatch.setattr(service.auth, "_create_session", fail_after_insert)
    with pytest.raises(RuntimeError):
        service.token(grant["device_code"])
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT state FROM cli_device_grants").fetchone()[0]
            == "approved"
        )
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    monkeypatch.setattr(service.auth, "_create_session", original)
    assert (
        service.token(grant["device_code"])[0].id
        == client.get("/api/auth/me").json()["id"]
    )


def _exchange_process(settings, proof, ready, go, results):
    from app.container import build_container
    from app.core.config import AppConfig

    service = build_container(AppConfig.model_validate(settings)).cli_auth_service
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    ready.put(True)
    if not go.wait(20):
        results.put("barrier_timeout")
        return
    try:
        service.token(proof)
        results.put("issued")
    except CliAuthError as error:
        results.put(error.code)


def test_024_FR_013_independent_processes_commit_exactly_one_session(live_cli):
    client, service = live_cli
    grant = service.start()
    assert approve(client, grant).status_code == 200
    context = multiprocessing.get_context("spawn")
    ready, results, go = context.Queue(), context.Queue(), context.Event()
    settings = client.app.state.config.model_dump(mode="json")
    children = [
        context.Process(
            target=_exchange_process,
            args=(settings, grant["device_code"], ready, go, results),
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            child.start()
        assert ready.get(timeout=30) and ready.get(timeout=30)
        go.set()
        outcomes = sorted([results.get(timeout=20), results.get(timeout=20)])
        assert outcomes == ["authorization_consumed", "issued"]
        for child in children:
            child.join(20)
            assert child.exitcode == 0
        with service.repo.store.connection() as connection:
            assert (
                connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2
            )
            assert (
                connection.execute("SELECT state FROM cli_device_grants").fetchone()[0]
                == "consumed"
            )
    finally:
        go.set()
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(5)


def test_024_FR_013_optional_flag_absence_survives_unrelated_write_and_restart(
    container,
):
    repository = container.feature_flag_repo
    assert "cli_auth" not in repository.read().flags
    repository.mutate(lambda flags: flags)
    repository.scrub_user("nonexistent-account")
    # Existing required inventory stays healthy without seeding the optional row.
    assert repository.read().degraded is False
    assert "cli_auth" not in repository.read().flags


def test_024_FR_013_explicit_flag_activation_preserves_existing_rows(live_cli):
    _, service = live_cli
    before = service.flags.repository.read().flags
    after = service.flags.repository.mutate(
        lambda flags: flags | {"cli_auth": FlagOverride(mode=FlagMode.OFF)}
    )
    assert {name: entry for name, entry in before.items() if name != "cli_auth"} == {
        name: entry for name, entry in after.flags.items() if name != "cli_auth"
    }
    with pytest.raises(CliAuthError, match="cli_auth_unavailable"):
        service.start()


def test_024_FR_013_commit_failure_never_exposes_or_consumes(live_cli, monkeypatch):
    client, service = live_cli
    grant = service.start()
    approve(client, grant)
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    store = service.repo.store

    class FailingCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("Synthetic commit failure")

    original = store._connect

    def failing_connection():
        connection = sqlite3.connect(store.db_path, factory=FailingCommit)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    monkeypatch.setattr(store, "_connect", failing_connection)
    with pytest.raises(StorageUnavailableError):
        service.token(grant["device_code"])
    monkeypatch.setattr(store, "_connect", original)
    with store.connection() as connection:
        assert (
            connection.execute("SELECT state FROM cli_device_grants").fetchone()[0]
            == "approved"
        )
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_024_FR_008_013_chunked_body_stops_before_unbounded_buffering(live_cli):
    import httpx

    client, _ = live_cli
    seen = []

    async def chunks():
        for size in [512, 512, 1, 100000]:
            seen.append(size)
            yield b" " * size

    async def execute():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as stream_client:
            response = await stream_client.post(
                "/api/auth/device/token",
                content=chunks(),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 413
            assert response.headers["Cache-Control"] == "no-store"

    asyncio.run(execute())
    assert seen == [512, 512, 1]


def test_024_FR_013_final_exposure_change_rolls_back_issuance(live_cli, monkeypatch):
    client, service = live_cli
    grant = service.start()
    approve(client, grant)
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    original = service.auth._create_session

    def turn_off_after_mint(*args, **kwargs):
        issued = original(*args, **kwargs)
        service.flags.repository.mutate(
            lambda flags: flags | {"cli_auth": FlagOverride(mode=FlagMode.OFF)}
        )
        return issued

    monkeypatch.setattr(service.auth, "_create_session", turn_off_after_mint)
    with pytest.raises(CliAuthError, match="cli_auth_unavailable"):
        service.token(grant["device_code"])
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT state FROM cli_device_grants").fetchone()[0]
            == "approved"
        )
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_024_FR_013_corrupt_grant_is_erased_without_quarantine(live_cli):
    _, service = live_cli
    grant = service.start()
    with service.repo.store.transaction() as connection:
        connection.execute("UPDATE cli_device_grants SET expires_at='corrupt' ")
    with pytest.raises(CliAuthError, match="invalid_device_code"):
        service.token(grant["device_code"])
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM cli_device_grants").fetchone()[0]
            == 0
        )


def test_024_FR_013_shared_store_has_full_durability_and_hash_bounds(live_cli):
    _, service = live_cli
    with service.repo.store.connection() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:password@example.com",
        "https://app.example.com/path",
        "https://app.example.com?",
        "https://app.example.com#",
        "https://app.example.com:0",
        "https://*.example.com",
        "http://example.com",
        "https://app.example.com:invalid",
    ],
)
def test_024_FR_013_verification_origin_never_derives_from_untrusted_url(origin):
    from app.core.config import AppConfig

    with pytest.raises(ValueError):
        AppConfig(cli_verification_origin=origin)


def test_024_FR_013_loopback_verification_is_development_only():
    from app.core.config import AppConfig, AppEnvironment

    assert (
        AppConfig(cli_verification_origin="http://localhost:80").cli_verification_origin
        == "http://localhost"
    )
    with pytest.raises(ValueError):
        AppConfig(
            environment=AppEnvironment.PRODUCTION,
            cli_verification_origin="http://localhost:3000",
        )


def test_024_FR_013_browser_lookup_and_decisions_are_source_bound(live_cli):
    client, service = live_cli
    grant = service.start()
    headers = {"Origin": service.origin}
    lookup = client.post(
        "/api/auth/device/request",
        json={"user_code": grant["user_code"]},
        headers=headers,
    )
    assert lookup.json()["state"] == "pending"
    assert approve(client, grant).status_code == 200
    assert approve(client, grant).status_code == 200
    conflict = client.post(
        "/api/auth/device/decision",
        json={"user_code": grant["user_code"], "decision": "deny"},
        headers=headers,
    )
    assert conflict.status_code == 409
    source = client.cookies.get(client.app.state.config.session.cookie_name)
    user = service.auth.get_user_for_token(source)
    other_token, _ = service.auth._create_session(user.id)
    with pytest.raises(CliAuthError, match="cli_auth_unavailable"):
        service.browser(grant["user_code"], other_token)
    assert service.browser(grant["user_code"], source)["state"] == "approved"


def test_024_FR_013_selected_cohort_is_checked_for_browser_and_exchange(live_cli):
    client, service = live_cli
    source = client.cookies.get(client.app.state.config.session.cookie_name)
    user = service.auth.get_user_for_token(source)
    service.flags.repository.mutate(
        lambda flags: flags | {"cli_auth": FlagOverride(mode=FlagMode.SELECTED_USERS)}
    )
    grant = service.start()
    assert approve(client, grant).status_code == 404
    service.flags.repository.mutate(
        lambda flags: flags
        | {
            "cli_auth": FlagOverride(
                mode=FlagMode.SELECTED_USERS, selected_users=(user.id,)
            )
        }
    )
    assert approve(client, grant).status_code == 200
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    service.flags.repository.mutate(
        lambda flags: flags | {"cli_auth": FlagOverride(mode=FlagMode.SELECTED_USERS)}
    )
    with pytest.raises(CliAuthError, match="cli_auth_unavailable"):
        service.token(grant["device_code"])


def test_024_FR_013_pending_and_expiry_errors_commit_state(live_cli):
    _, service = live_cli
    grant = service.start()
    now = utcnow()
    service.clock = lambda: now + timedelta(seconds=6)
    with pytest.raises(CliAuthError, match="authorization_pending"):
        service.token(grant["device_code"])
    service.clock = lambda: now + timedelta(seconds=601)
    with pytest.raises(CliAuthError, match="authorization_expired"):
        service.token(grant["device_code"])
    with pytest.raises(CliAuthError, match="invalid_device_code"):
        service.token(grant["device_code"])


def test_024_FR_013_start_capacity_is_durable_and_prunes_expired(live_cli):
    _, service = live_cli
    now = service.clock().timestamp()
    with service.repo.store.transaction() as connection:
        for number in range(1024):
            connection.execute(
                "INSERT INTO cli_device_grants(device_hash,code_hash,created_at,expires_at,state,interval,next_poll_at) VALUES(?,?,?,?,'pending',5,?)",
                (f"{number:064x}", f"{number:064x}", now, now + 600, now + 5),
            )
    with pytest.raises(CliAuthError, match="rate_limited"):
        service.start()
    service.clock = lambda: datetime.fromtimestamp(now + 601, UTC)
    service.start()
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM cli_device_grants").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("provider", ["google", "apple"])
@pytest.mark.parametrize("change", ["generation", "revoked", "version"])
def test_024_FR_013_provider_and_version_changes_prevent_issuance(
    live_cli, provider, change
):
    client, service = live_cli
    original_source = client.cookies.get(client.app.state.config.session.cookie_name)
    user = service.auth.get_user_for_token(original_source)
    binding_id = "synthetic-cli-binding"
    with service.repo.store.transaction() as connection:
        connection.execute(
            "INSERT INTO auth_identity_bindings(id,user_id,provider,issuer,namespace,subject,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                binding_id,
                user.id,
                provider,
                "synthetic-issuer",
                "web",
                "synthetic-subject",
                utcnow().isoformat(),
                utcnow().isoformat(),
            ),
        )
    source, _ = service.auth._create_session(
        user.id, auth_method=provider, provider_binding_id=binding_id
    )
    grant = service.start()
    service.browser(grant["user_code"], source, "approve")
    with service.repo.store.transaction() as connection:
        if change == "generation":
            connection.execute(
                "UPDATE auth_identity_bindings SET generation=generation+1 WHERE id=?",
                (binding_id,),
            )
        elif change == "revoked":
            connection.execute(
                "UPDATE auth_identity_bindings SET state='revoked' WHERE id=?",
                (binding_id,),
            )
        else:
            service.auth.user_repo.mutate(
                user.id,
                lambda fresh: fresh.model_copy(
                    update={"auth_version": fresh.auth_version + 1}
                ),
            )
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    with pytest.raises(CliAuthError, match="cli_auth_unavailable"):
        service.token(grant["device_code"])
    with service.repo.store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2


def test_024_FR_013_issued_cli_session_survives_source_logout_but_not_bulk_revocation(
    live_cli,
):
    client, service = live_cli
    source = client.cookies.get(client.app.state.config.session.cookie_name)
    grant = service.start()
    approve(client, grant)
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    user, issued, _ = service.token(grant["device_code"])
    service.auth.logout(source)
    assert service.auth.get_user_for_token(issued).id == user.id
    service.auth.session_repo.delete_all_for_user(user.id)
    assert service.auth.get_user_for_token(issued) is None


def test_024_FR_013_denial_is_terminal_and_never_issues_a_session(live_cli):
    client, service = live_cli
    grant = service.start()
    denied = client.post(
        "/api/auth/device/decision",
        json={"user_code": grant["user_code"], "decision": "deny"},
        headers={"Origin": service.origin},
    )
    assert denied.json() == {"state": "denied"}
    with pytest.raises(CliAuthError, match="authorization_denied"):
        service.token(grant["device_code"])
    assert approve(client, grant).status_code == 409
    with service.repo.store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_024_FR_013_browser_expiry_erasure_and_missing_source_are_opaque(live_cli):
    client, service = live_cli
    grant = service.start()
    raw = client.cookies.get(client.app.state.config.session.cookie_name)
    for source in (None, "missing-session"):
        with pytest.raises(CliAuthError, match="cli_auth_unavailable"):
            service.browser(grant["user_code"], source)
    service.clock = lambda: utcnow() + timedelta(seconds=601)
    with pytest.raises(CliAuthError, match="cli_auth_unavailable"):
        service.browser(grant["user_code"], raw)
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM cli_device_grants").fetchone()[0]
            == 0
        )
    client.cookies.clear()
    response = client.post(
        "/api/auth/device/request",
        json={"user_code": grant["user_code"]},
        headers={"Origin": service.origin},
    )
    assert response.status_code == 404 and grant["user_code"] not in response.text


def test_024_FR_013_code_collisions_retry_then_fail_without_overwriting(
    live_cli, monkeypatch
):
    _, service = live_cli
    from app.services import cli_auth

    monkeypatch.setattr(cli_auth.secrets, "choice", lambda _: "A")
    initial = service.start()
    with pytest.raises(CliAuthError, match="cli_auth_unavailable") as exhausted:
        service.start()
    assert exhausted.value.status_code == 503
    codes = iter("AAAAAAAA" + "BBBBBBBB")
    monkeypatch.setattr(cli_auth.secrets, "choice", lambda _: next(codes))
    retry = service.start()
    assert retry["user_code"] == "BBBB-BBBB"
    assert initial["device_code"] != retry["device_code"]
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM cli_device_grants").fetchone()[0]
            == 2
        )


def test_024_FR_013_incompatible_schema_is_rejected_without_repair(live_cli):
    _, service = live_cli
    with service.repo.store.transaction() as connection:
        connection.execute(
            "ALTER TABLE cli_device_grants ADD COLUMN unreviewed_authority TEXT"
        )
    with pytest.raises(RepositoryError, match="schema is incompatible"):
        CliAuthRepository(service.repo.store)
    with service.repo.store.connection() as connection:
        assert "unreviewed_authority" in [
            row["name"]
            for row in connection.execute("PRAGMA table_info(cli_device_grants)")
        ]


def test_024_FR_013_privacy_sweep_erases_corrupt_authority_when_off(live_cli, caplog):
    client, service = live_cli
    service.start()
    with service.repo.store.transaction() as connection:
        connection.execute(
            "UPDATE cli_device_grants SET state='approved',source_hash='private-sentinel'"
        )
    service.flags.repository.mutate(
        lambda flags: flags | {"cli_auth": FlagOverride(mode=FlagMode.OFF)}
    )
    from app.main import _run_privacy_maintenance_sweep

    _run_privacy_maintenance_sweep(client.app.state.container)
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM cli_device_grants").fetchone()[0]
            == 0
        )
    assert "private-sentinel" not in caplog.text
    assert "Invalid CLI authorization grants erased" in caplog.text


def test_024_FR_013_expiry_during_mint_rolls_back_both_changes(live_cli, monkeypatch):
    client, service = live_cli
    grant = service.start()
    approve(client, grant)
    now = utcnow()
    service.clock = lambda: now + timedelta(seconds=6)
    original = service.auth._create_session

    def mint_then_expire(*args, **kwargs):
        result = original(*args, **kwargs)
        service.clock = lambda: now + timedelta(seconds=601)
        return result

    monkeypatch.setattr(service.auth, "_create_session", mint_then_expire)
    with pytest.raises(CliAuthError, match="authorization_expired"):
        service.token(grant["device_code"])
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT state FROM cli_device_grants").fetchone()[0]
            == "approved"
        )
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_024_FR_013_oversized_wrong_media_and_rate_errors_are_safe(live_cli):
    client, service = live_cli
    response = client.post(
        "/api/auth/device/start",
        content="private-sentinel",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 415 and "private-sentinel" not in response.text
    for _ in range(10):
        assert client.post("/api/auth/device/start", json={}).status_code == 200
    limited = client.post("/api/auth/device/start", json={})
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.headers["Cache-Control"] == "no-store"
    assert service.start_limit.key_count == 1


def test_024_FR_013_browser_budget_counts_bad_codes_and_blocks_guessing(live_cli):
    client, service = live_cli
    grant = service.start()
    headers = {"Origin": service.origin}
    for _ in range(12):
        assert (
            client.post(
                "/api/auth/device/request",
                json={"user_code": grant["user_code"]},
                headers=headers,
            ).status_code
            == 200
        )
    missing = ("A" if grant["user_code"][0] != "A" else "B") + grant["user_code"][1:]
    for _ in range(10):
        assert (
            client.post(
                "/api/auth/device/request", json={"user_code": missing}, headers=headers
            ).status_code
            == 404
        )
    for code in (missing, grant["user_code"]):
        blocked = client.post(
            "/api/auth/device/request", json={"user_code": code}, headers=headers
        )
        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"] == "60"
    assert service.browser_limit.key_count == 1


@pytest.mark.parametrize("correlation", [None, "correlation-sentinel"])
def test_024_FR_008_013_validation_never_reflects_proof_on_configured_paths(
    live_cli, correlation
):
    client, _ = live_cli
    from fastapi.exceptions import RequestValidationError
    from starlette.requests import Request

    from app.api.errors import handle_request_validation

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("app.example.com", 443),
            "path": "/api/auth/device/token",
            "query_string": b"",
            "headers": [],
            "app": client.app,
        }
    )
    request.state.correlation_id = correlation
    response = asyncio.run(
        handle_request_validation(
            request,
            RequestValidationError(
                [
                    {
                        "input": "private-sentinel",
                        "msg": "private-sentinel",
                        "ctx": {"secret": "private-sentinel"},
                    }
                ]
            ),
        )
    )
    assert response.status_code == 422 and b"private-sentinel" not in response.body
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers.get("X-Correlation-ID") == correlation


def test_024_FR_013_export_excludes_grants_and_hard_purge_erases_bound_rows(live_cli):
    client, service = live_cli
    source = client.cookies.get(client.app.state.config.session.cookie_name)
    user = service.auth.get_user_for_token(source)
    grant = service.start()
    approve(client, grant)
    account = client.app.state.container.account_service
    _, spool = account.export_account_data(user)
    try:
        with zipfile.ZipFile(spool) as archive:
            manifest = json.loads(archive.read("export_manifest.json"))
            assert any("CLI device grants" in item for item in manifest["excluded"])
            for name in archive.namelist():
                data = archive.read(name)
                assert grant["device_code"].encode() not in data
                assert service.auth.hash_session_token(source).encode() not in data
    finally:
        spool.close()
    account.purge_account(user.id)
    with service.repo.store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM cli_device_grants").fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def _interrupted_exchange(settings, proof, ready, resume):
    from app.container import build_container
    from app.core.config import AppConfig

    service = build_container(AppConfig.model_validate(settings)).cli_auth_service
    service.clock = lambda: utcnow() + timedelta(seconds=6)
    original = service.auth._create_session

    def paused_mint(*args, **kwargs):
        result = original(*args, **kwargs)
        ready.put(True)
        if not resume.wait(20):
            raise RuntimeError("Owned test barrier timed out")
        return result

    service.auth._create_session = paused_mint
    service.token(proof)


def test_024_FR_013_process_termination_rolls_back_consumption_and_mint(live_cli):
    client, service = live_cli
    grant = service.start()
    approve(client, grant)
    context = multiprocessing.get_context("spawn")
    ready, resume = context.Queue(), context.Event()
    child = context.Process(
        target=_interrupted_exchange,
        args=(
            client.app.state.config.model_dump(mode="json"),
            grant["device_code"],
            ready,
            resume,
        ),
    )
    try:
        child.start()
        assert ready.get(timeout=30)
        child.terminate()
        child.join(10)
        assert not child.is_alive()
        with service.repo.store.connection() as connection:
            assert (
                connection.execute("SELECT state FROM cli_device_grants").fetchone()[0]
                == "approved"
            )
            assert (
                connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
            )
        service.clock = lambda: utcnow() + timedelta(seconds=6)
        assert (
            service.token(grant["device_code"])[0].id
            == client.get("/api/auth/me").json()["id"]
        )
    finally:
        # A process killed in Event.wait() can leave its condition lock held.
        # This termination test never resumes the child or touches that event.
        if child.is_alive():
            child.terminate()
        child.join(5)
