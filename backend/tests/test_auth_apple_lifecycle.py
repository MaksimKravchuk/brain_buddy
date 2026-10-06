"""Apple grant cleanup and signed-notice effects against real Identity SQLite."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import allure
import pytest
from pydantic import SecretStr

from app.repositories.auth_store import AuthStore
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.schemas.auth import Session, User
from app.services.auth_provider_service import (
    AppleNotification,
    ProviderIdentity,
    ProviderTokens,
)
from app.services.auth_secret_box import AuthSecretBox

pytestmark = [
    allure.epic("Authentication & access"),
    allure.feature("Apple authority lifecycle"),
    allure.story("022-FR-019/021/025; 022-SC-003/005"),
]

NOW = datetime(2026, 10, 6, 15, tzinfo=UTC)
APPLE = "https://appleid.apple.com"
REFRESH_KIND = "refresh_token"


class Gateway:
    def __init__(self) -> None:
        self.revocations: list[tuple[str, str, str]] = []
        self.notification = AppleNotification(
            "event-1",
            "consent-revoked",
            "apple-subject",
            "web-client",
            int(NOW.timestamp()),
            int(NOW.timestamp()),
        )
        self.failure = False
        self.during_revoke: Any = None
        self.verification_failure = False

    def revoke_apple(self, token, issuing_client, *, token_type=REFRESH_KIND) -> None:
        raw = token.get_secret_value() if isinstance(token, SecretStr) else token
        self.revocations.append((raw, issuing_client, token_type))
        if self.during_revoke:
            self.during_revoke()
        if self.failure:
            raise RuntimeError("synthetic provider secret must never escape")

    def verify_notification(self, _payload):
        if self.verification_failure:
            raise ValueError("invalid signed fixture")
        return self.notification


def _tokens(
    *, client: str = "web-client", issued_at: datetime | None = None
) -> ProviderTokens:
    return ProviderTokens(
        ProviderIdentity(
            "apple",
            APPLE,
            "apple-subject",
            "relay@example.com",
            True,
            True,
            client,
            int((issued_at or NOW - timedelta(minutes=1)).timestamp()),
        ),
        client,
        SecretStr("synthetic-refresh-token"),
        "refresh_token",
    )


@pytest.fixture
def fixture(tmp_path: Path):
    store = AuthStore(tmp_path)
    users = UserRepository(tmp_path, store)
    users.create(
        User(id="owner", email="owner@example.com", created_at=NOW - timedelta(days=2))
    )
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO auth_identity_bindings(id,user_id,provider,issuer,namespace,subject,created_at,updated_at,email,is_private_email) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "binding",
                "owner",
                "apple",
                APPLE,
                "brainbuddy",
                "apple-subject",
                (NOW - timedelta(days=1)).isoformat(),
                NOW.isoformat(),
                "relay@example.com",
                1,
            ),
        )
    gateway = Gateway()
    box = AuthSecretBox({"v1": b"1" * 32}, "v1")
    from app.services.auth_apple_lifecycle import AuthAppleLifecycle

    clock = [NOW]
    service = AuthAppleLifecycle(store, box, gateway, clock=lambda: clock[0])
    return store, users, service, gateway, box, clock


def _rows(store: AuthStore, table: str) -> list[sqlite3.Row]:
    with store.connection() as connection:
        return connection.execute(f"SELECT * FROM {table}").fetchall()


def test_022_fr025_grant_is_sealed_and_bound_to_current_identity(fixture):
    """Only the intended Apple binding receives a sealed minimum revocation grant."""
    store, _, service, _, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
    grant = _rows(store, "auth_apple_grants")[0]
    assert "synthetic-refresh-token" not in grant["sealed_payload"]
    assert grant["issuing_client"] == "web-client" and grant["generation"] == 1
    binding = _rows(store, "auth_identity_bindings")[0]
    assert (
        json.loads(binding["payload_json"])["apple_consent_issued_at"]
        == _tokens().identity.issued_at
    )
    assert len(_rows(store, "auth_apple_grants")) == 1


def test_022_fr025_cleanup_revoke_runs_outside_transaction_and_erases_credentials(
    fixture,
):
    """Cleanup leases commit before provider I/O and erase terminal credentials."""
    store, _, service, gateway, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "unlink")
        service.schedule_cleanup(connection, "binding", "unlink")
    assert _rows(store, "auth_apple_grants") == []
    assert len(_rows(store, "auth_apple_cleanup_jobs")) == 1

    def concurrent_write():
        independent = AuthStore(store.root)
        with independent.transaction() as connection:
            connection.execute(
                "UPDATE users SET email_verified_at=NULL WHERE id='owner'"
            )
        with store.connection() as connection:
            assert not connection.in_transaction

    gateway.during_revoke = concurrent_write
    assert service.dispatch_one()
    assert gateway.revocations == [
        ("synthetic-refresh-token", "web-client", "refresh_token")
    ]
    job = _rows(store, "auth_apple_cleanup_jobs")[0]
    assert job["status"] == "delivered"
    assert job["sealed_payload"] is None and job["key_id"] is None
    assert not service.dispatch_one()


def test_022_fr025_failures_are_bounded_to_five_attempts_and_safe_logs(fixture, caplog):
    """Provider failures never expose tokens and stop after five attempts."""
    store, _, service, gateway, _, clock = fixture
    gateway.failure = True
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "unlink")
    for _ in range(5):
        assert service.dispatch_one()
        clock[0] += timedelta(hours=1)
    assert not service.dispatch_one()
    job = _rows(store, "auth_apple_cleanup_jobs")[0]
    assert job["attempts"] == 5 and job["status"] == "failed"
    assert job["sealed_payload"] is None
    assert len(gateway.revocations) == 5
    assert "synthetic-refresh-token" not in caplog.text
    assert "synthetic provider secret" not in caplog.text


def test_022_fr025_active_lease_blocks_replacement_and_pending_jobs_cancel(fixture):
    """A live remote cleanup cannot race a newer same-binding consent generation."""
    from app.services.auth_apple_lifecycle import AuthAppleLifecycleError

    store, _, service, gateway, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "unlink")

    def try_replace():
        with pytest.raises(AuthAppleLifecycleError), store.transaction() as connection:
            service.ensure_replaceable(connection, "binding")

    gateway.during_revoke = try_replace
    assert service.dispatch_one()
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "unlink")
        service.ensure_replaceable(connection, "binding")
        connection.execute(
            "UPDATE auth_identity_bindings SET generation=2 WHERE id='binding'"
        )
        service.record_grant(connection, "binding", _tokens(issued_at=NOW))
    jobs = _rows(store, "auth_apple_cleanup_jobs")
    assert jobs[-1]["status"] == "cancelled" and jobs[-1]["sealed_payload"] is None
    assert not service.dispatch_one()
    assert _rows(store, "auth_apple_grants")[0]["generation"] == 2


def test_022_fr019_job_deadline_is_capped_by_local_purge(fixture):
    """Remote cleanup cannot outlive the local account-purge deadline."""
    store, users, service, gateway, _, clock = fixture
    requested = NOW - timedelta(days=14) + timedelta(minutes=2)
    users.mutate(
        "owner",
        lambda user: user.model_copy(update={"deletion_requested_at": requested}),
    )
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "deletion")
    expiry = datetime.fromisoformat(
        _rows(store, "auth_apple_cleanup_jobs")[0]["expires_at"]
    )
    assert expiry == NOW + timedelta(minutes=2)
    clock[0] += timedelta(minutes=3)
    assert not service.dispatch_one()
    assert gateway.revocations == []
    assert _rows(store, "auth_apple_cleanup_jobs")[0]["sealed_payload"] is None


@pytest.mark.parametrize("event", ["consent-revoked", "account-deleted"])
def test_022_fr025_notices_revoke_only_matching_provider_authority(fixture, event):
    """A signed notice ends Apple authority while retaining the account and other sessions."""
    store, users, service, gateway, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
    sessions = SessionRepository(store.root, store)
    for digest, method, binding in [
        ("apple_session", "apple", "binding"),
        ("password_session", "password", None),
    ]:
        sessions.create(
            Session(
                token_hash=digest,
                user_id="owner",
                created_at=NOW,
                expires_at=NOW + timedelta(days=1),
                auth_method=method,
                provider_binding_id=binding,
            )
        )
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO auth_proofs(digest,user_id,purpose,provider_binding_id,created_at,expires_at) VALUES(?,?,?,?,?,?)",
            (
                "proof",
                "owner",
                "reauth",
                "binding",
                NOW.isoformat(),
                (NOW + timedelta(minutes=5)).isoformat(),
            ),
        )
    gateway.notification = AppleNotification(
        "notice",
        event,
        "apple-subject",
        "web-client",
        int(NOW.timestamp()),
        int(NOW.timestamp()),
    )
    service.process_notification("signed synthetic payload")
    assert _rows(store, "auth_identity_bindings")[0]["state"] == "revoked"
    assert sessions.get("apple_session") is None
    assert sessions.get("password_session") is not None
    assert _rows(store, "auth_proofs") == [] and _rows(store, "auth_apple_grants") == []
    assert users.get_by_id("owner") is not None
    service.process_notification("signed synthetic payload")
    assert len(_rows(store, "auth_apple_notification_receipts")) == 1


def test_022_fr025_delayed_notice_cannot_end_newer_generation(fixture):
    """A notice older than newer validated consent cannot revoke that consent."""
    store, _, service, gateway, _, clock = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        connection.execute(
            "UPDATE auth_identity_bindings SET generation=2 WHERE id='binding'"
        )
        service.record_grant(connection, "binding", _tokens(issued_at=NOW))
    clock[0] += timedelta(minutes=1)
    gateway.notification = AppleNotification(
        "old-event",
        "consent-revoked",
        "apple-subject",
        "web-client",
        int(clock[0].timestamp()),
        int((NOW - timedelta(seconds=10)).timestamp()),
    )
    service.process_notification("signed old fixture")
    assert _rows(store, "auth_identity_bindings")[0]["state"] == "active"
    assert _rows(store, "auth_apple_grants")[0]["generation"] == 2


def test_022_fr025_email_notices_change_only_matching_relay_metadata(fixture):
    """Relay forwarding events neither alter account email nor grant authentication."""
    store, users, service, gateway, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
    gateway.notification = AppleNotification(
        "delivery-event",
        "email-disabled",
        "apple-subject",
        "web-client",
        int(NOW.timestamp()),
        int(NOW.timestamp()),
        "relay@example.com",
        True,
    )
    service.process_notification("signed relay fixture")
    binding = _rows(store, "auth_identity_bindings")[0]
    assert json.loads(binding["payload_json"])["email_delivery_disabled"] is True
    assert binding["state"] == "active"
    assert users.get_by_id("owner").email == "owner@example.com"
    assert len(_rows(store, "auth_apple_grants")) == 1


def test_022_fr025_invalid_signed_notice_has_no_durable_effect(fixture):
    from app.services.auth_apple_lifecycle import AuthAppleLifecycleError

    store, _, service, gateway, _, _ = fixture
    gateway.verification_failure = True
    with pytest.raises(AuthAppleLifecycleError):
        service.process_notification("invalid fixture")
    assert _rows(store, "auth_apple_notification_receipts") == []
    assert _rows(store, "auth_identity_bindings")[0]["state"] == "active"


def test_022_fr025_equal_revocation_requires_strictly_newer_consent(fixture):
    """Ambiguous equal-time revocation requires a newer validated authorization."""
    from app.services.auth_apple_lifecycle import AuthAppleLifecycleError

    store, _, service, _, _, clock = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens(issued_at=NOW))
    service.process_notification("signed equal-time fixture")
    binding = _rows(store, "auth_identity_bindings")[0]
    assert binding["state"] == "revoked"
    assert json.loads(binding["payload_json"])["apple_confirmation_required"] is True
    with pytest.raises(AuthAppleLifecycleError), store.transaction() as connection:
        service.ensure_replaceable(connection, "binding")
        connection.execute(
            "UPDATE auth_identity_bindings SET state='active',generation=2 WHERE id='binding'"
        )
        service.record_grant(connection, "binding", _tokens(issued_at=NOW))
    assert _rows(store, "auth_identity_bindings")[0]["state"] == "revoked"
    clock[0] += timedelta(seconds=1)
    with store.transaction() as connection:
        service.ensure_replaceable(connection, "binding")
        connection.execute(
            "UPDATE auth_identity_bindings SET state='active',generation=2 WHERE id='binding'"
        )
        service.record_grant(connection, "binding", _tokens(issued_at=clock[0]))
    metadata = json.loads(_rows(store, "auth_identity_bindings")[0]["payload_json"])
    assert "apple_confirmation_required" not in metadata
    assert _rows(store, "auth_apple_grants")[0]["generation"] == 2


def test_022_fr025_fifth_inflight_attempt_keeps_replacement_blocked(fixture):
    """A concurrent worker cannot retire an in-flight fifth attempt and permit replacement."""
    from app.services.auth_apple_lifecycle import AuthAppleLifecycleError

    store, _, service, gateway, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "unlink")
        connection.execute("UPDATE auth_apple_cleanup_jobs SET attempts=4")

    def during_fifth():
        assert not service.dispatch_one()
        with pytest.raises(AuthAppleLifecycleError), store.transaction() as connection:
            service.ensure_replaceable(connection, "binding")

    gateway.during_revoke = during_fifth
    assert service.dispatch_one()
    assert _rows(store, "auth_apple_cleanup_jobs")[0]["attempts"] == 5


def test_022_fr025_deadline_erases_secret_but_keeps_inflight_lease(fixture):
    """Expired credentials are erased while an in-flight lease still blocks newer consent."""
    from app.services.auth_apple_lifecycle import AuthAppleLifecycleError

    store, _, service, gateway, _, clock = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "unlink")
        connection.execute(
            "UPDATE auth_apple_cleanup_jobs SET expires_at=?",
            ((NOW + timedelta(seconds=5)).isoformat(),),
        )

    observed = []

    def after_deadline():
        clock[0] += timedelta(seconds=6)
        dispatched = service.dispatch_one()
        job = _rows(store, "auth_apple_cleanup_jobs")[0]
        observed.append((dispatched, job["sealed_payload"], job["status"]))
        with pytest.raises(AuthAppleLifecycleError), store.transaction() as connection:
            service.ensure_replaceable(connection, "binding")

    gateway.during_revoke = after_deadline
    assert service.dispatch_one()
    assert observed == [(False, None, "leased")]
    assert _rows(store, "auth_apple_cleanup_jobs")[0]["status"] == "delivered"


def test_022_fr025_expired_lease_allows_new_generation_without_stale_ack(fixture):
    """An expired lease cannot block consent forever or acknowledge newer generation work."""
    store, _, service, gateway, _, clock = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "unlink")
    observed = []

    def after_lease_expiry():
        clock[0] += timedelta(seconds=31)
        with store.transaction() as connection:
            service.ensure_replaceable(connection, "binding")
            connection.execute(
                "UPDATE auth_identity_bindings SET generation=2 WHERE id='binding'"
            )
            service.record_grant(connection, "binding", _tokens(issued_at=clock[0]))
        observed.append(True)

    gateway.during_revoke = after_lease_expiry
    assert service.dispatch_one()
    assert observed == [True]
    assert _rows(store, "auth_apple_cleanup_jobs")[0]["status"] == "cancelled"
    assert _rows(store, "auth_apple_grants")[0]["generation"] == 2


def test_022_fr025_missing_key_cannot_delay_local_grant_erasure(fixture):
    """Missing encryption keys leave cleanup unconfirmed while erasing local credentials."""
    store, users, service, gateway, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
    service.secret_box = None
    with store.transaction() as connection:
        service.schedule_cleanup(connection, "binding", "deletion")
    assert _rows(store, "auth_apple_grants") == []
    assert _rows(store, "auth_apple_cleanup_jobs")[0]["sealed_payload"] is None
    assert not service.dispatch_one()
    assert gateway.revocations == []
    users.delete("owner")
    assert _rows(store, "auth_apple_cleanup_jobs") == []


def test_022_fr025_key_rotation_reseals_cleanup_under_current_key(fixture):
    """Old grants decrypt with retained keys and cleanup uses the new current key."""
    store, _, service, gateway, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
    service.secret_box = AuthSecretBox({"v1": b"1" * 32, "v2": b"2" * 32}, "v2")
    with store.transaction() as connection:
        service.schedule_cleanup(connection, "binding", "unlink")
    assert _rows(store, "auth_apple_cleanup_jobs")[0]["key_id"] == "v2"
    service.secret_box = AuthSecretBox({"v2": b"2" * 32}, "v2")
    assert service.dispatch_one()
    assert len(gateway.revocations) == 1


def test_022_fr025_issuing_client_tamper_cannot_decrypt_or_revoke(fixture):
    """A changed issuing client fails AEAD binding before any provider call."""
    store, _, service, gateway, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
        service.schedule_cleanup(connection, "binding", "unlink")
        connection.execute(
            "UPDATE auth_apple_cleanup_jobs SET issuing_client='tampered-client'"
        )
    assert not service.dispatch_one()
    assert gateway.revocations == []
    assert _rows(store, "auth_apple_cleanup_jobs")[0]["sealed_payload"] is None


def test_022_fr025_provider_subject_mismatch_cannot_store_grant(fixture):
    """A valid-looking token for another stable subject cannot attach to this binding."""
    from app.services.auth_apple_lifecycle import AuthAppleLifecycleError

    store, _, service, _, _, _ = fixture
    tokens = _tokens()
    foreign = replace(
        tokens, identity=replace(tokens.identity, subject="another-subject")
    )
    with pytest.raises(AuthAppleLifecycleError), store.transaction() as connection:
        service.record_grant(connection, "binding", foreign)
    assert _rows(store, "auth_apple_grants") == []


def test_022_fr025_independent_connections_apply_notice_once(fixture):
    """Independent SQLite authorities atomically record and apply a replayed notice once."""
    from app.services.auth_apple_lifecycle import AuthAppleLifecycle

    store, _, service, gateway, box, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
    services = [
        service,
        AuthAppleLifecycle(AuthStore(store.root), box, gateway, clock=lambda: NOW),
    ]
    barrier = Barrier(2)

    def notify(index):
        barrier.wait(timeout=10)
        services[index].process_notification("same signed fixture")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(notify, range(2)))
    assert len(_rows(store, "auth_apple_notification_receipts")) == 1
    assert _rows(store, "auth_identity_bindings")[0]["state"] == "revoked"


def test_022_fr025_unknown_subject_receipt_is_bounded_and_has_no_raw_identity(fixture):
    """Unknown provider subjects receive the same acknowledgement with only a bounded hashed receipt."""
    store, _, service, gateway, _, _ = fixture
    gateway.notification = replace(
        gateway.notification, jti="unknown-event", subject="unknown-private-subject"
    )
    service.process_notification("signed unknown fixture")
    receipt = _rows(store, "auth_apple_notification_receipts")[0]
    assert "unknown-private-subject" not in str(dict(receipt))
    assert "unknown-event" not in receipt["digest"]
    assert datetime.fromisoformat(receipt["expires_at"]) <= NOW + timedelta(days=8)
    assert _rows(store, "auth_identity_bindings")[0]["state"] == "active"


def test_022_fr025_partial_notification_effect_rolls_back_receipt(fixture, monkeypatch):
    """A failed notice effect rolls back its replay receipt so a safe retry remains possible."""
    store, _, service, _, _, _ = fixture
    with store.transaction() as connection:
        service.record_grant(connection, "binding", _tokens())
    disable = service._disable

    def interrupted(connection, binding, metadata):
        disable(connection, binding, metadata)
        raise RuntimeError("synthetic notice storage interruption")

    monkeypatch.setattr(service, "_disable", interrupted)
    with pytest.raises(RuntimeError):
        service.process_notification("signed fixture")
    assert _rows(store, "auth_apple_notification_receipts") == []
    assert _rows(store, "auth_identity_bindings")[0]["state"] == "active"
    assert len(_rows(store, "auth_apple_grants")) == 1
    monkeypatch.setattr(service, "_disable", disable)
    service.process_notification("signed fixture")
    assert len(_rows(store, "auth_apple_notification_receipts")) == 1
