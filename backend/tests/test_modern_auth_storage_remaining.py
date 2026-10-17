"""Risk-selected storage, sealed-payload and cleanup failure boundaries."""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from unittest.mock import MagicMock

import allure
import httpx
import pytest
from pydantic import SecretStr

from app.core.config import ModernAuthSettings
from app.exceptions import RepositoryError
from app.repositories.auth_metadata import AuthMetadataRepository
from app.repositories.auth_store import AuthStore
from app.repositories.user import UserRepository
from app.schemas.auth import User
from app.services.auth_apple_lifecycle import AuthAppleLifecycleError
from app.services.auth_mail_service import AuthMailError, AuthMailService
from app.services.auth_provider_service import AuthProviderService, ProviderError
from app.services.auth_secret_box import AuthSecretBox, AuthSecretError, SecretContext
from tests import test_auth_apple_lifecycle as apple
from tests import test_auth_mail_service as email
from tests import test_auth_provider_service as provider

apple_fixture = apple.fixture
apple_key = provider.apple_key
rsa_key = provider.rsa_key

pytestmark = [
    allure.epic("Authentication & access"),
    allure.feature("Durable credential failure boundaries"),
    allure.story("023-FR-002/008/010/018/021/025; 023-SC-003/005"),
]


def test_022_fr002_partial_schema_creation_rolls_back(tmp_path, monkeypatch):
    """A failed schema transaction leaves no partially usable authentication tables."""
    from app.repositories import auth_store

    monkeypatch.setattr(auth_store, "_SCHEMA", auth_store._SCHEMA + "\nINVALID SQL;")
    with pytest.raises(RepositoryError):
        AuthStore(tmp_path)
    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            == []
        )


@pytest.mark.parametrize("damage", ["missing", "future_epoch"])
def test_022_fr002_incompatible_ledger_never_becomes_ready(tmp_path, damage):
    """Missing and unrecognized ledgers fail readiness without consulting legacy files."""
    store = AuthStore(tmp_path)
    with store.transaction() as connection:
        if damage == "missing":
            connection.execute("DELETE FROM auth_migration_ledger")
        else:
            connection.execute("UPDATE auth_migration_ledger SET schema_epoch=2")
    with pytest.raises(RepositoryError, match="epoch"):
        AuthStore(tmp_path)
    assert not (tmp_path / "users").exists()


def test_022_fr002_caught_nested_failure_still_aborts_outer_authority(tmp_path):
    """Catching a failed nested write cannot commit sibling credential changes."""
    store = AuthStore(tmp_path)
    users = UserRepository(tmp_path, store)
    with pytest.raises(RepositoryError, match="aborted"), store.transaction():
        users.create(User(id="owner", email="owner@example.com", created_at=apple.NOW))
        assert not store.checkpoint()
        try:
            with store.transaction():
                raise RuntimeError("synthetic nested write failure")
        except RuntimeError:
            pass
    assert users.get_by_id("owner") is None
    assert store.checkpoint()


def test_022_fr018_account_delete_is_owner_scoped_and_cascades_secrets(apple_fixture):
    """Deleting an account erases its metadata and secrets, never another owner's."""
    store, users, lifecycle, _, _, _ = apple_fixture
    users.create(User(id="other", email="other@example.com", created_at=apple.NOW))
    metadata = AuthMetadataRepository(store.root, store)
    with store.transaction() as connection:
        lifecycle.record_grant(connection, "binding", apple._tokens())
        for owner in ("owner", "other"):
            connection.execute(
                "INSERT INTO auth_attempts(id,user_id,provider,intent,channel,client_challenge,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    owner,
                    owner,
                    "google",
                    "login",
                    "web",
                    "client",
                    apple.NOW.isoformat(),
                    (apple.NOW + timedelta(minutes=5)).isoformat(),
                ),
            )
        connection.execute(
            "INSERT INTO auth_handoffs(digest,attempt_id,expires_at) VALUES('handoff','owner',?)",
            ((apple.NOW + timedelta(seconds=60)).isoformat(),),
        )
    users.delete("owner")
    assert apple._rows(store, "auth_handoffs") == []
    assert apple._rows(store, "auth_apple_grants") == []
    assert apple._rows(store, "auth_identity_bindings") == []
    assert [row["user_id"] for row in apple._rows(store, "auth_attempts")] == ["other"]
    assert users.get_by_id("owner") is None
    assert users.get_by_id("other") is not None
    assert metadata.cleanup_expired(now=apple.NOW) == 0


@pytest.mark.parametrize("limit", [0, 1001])
def test_022_fr018_invalid_cleanup_bound_cannot_delete_authority(tmp_path, limit):
    """Invalid maintenance limits fail before opening a deletion transaction."""
    metadata = AuthMetadataRepository(tmp_path)
    with pytest.raises(ValueError, match="limit"):
        metadata.cleanup_expired(now=apple.NOW, limit=limit)


@pytest.mark.parametrize(
    "changes",
    [{"kind": ""}, {"owner_id": None}, {"generation": True}, {"generation": -1}],
)
def test_022_fr021_invalid_secret_context_cannot_authorize(changes):
    """Malformed authority dimensions never produce authenticated payload contexts."""
    with pytest.raises(AuthSecretError):
        SecretContext(**({"kind": "apple_grant"} | changes))


@pytest.mark.parametrize(
    "operation", ["plaintext", "context", "short_envelope", "noncanonical_envelope"]
)
def test_022_fr021_invalid_secret_encodings_have_no_plaintext_fallback(operation):
    """Wrong payload types and noncanonical ciphertext encodings fail with safe errors."""
    box = AuthSecretBox({"v1": b"1" * 32}, "v1")
    context = SecretContext("apple_grant")
    with pytest.raises(AuthSecretError) as error:
        if operation == "plaintext":
            box.seal("synthetic-secret", context)
        elif operation == "context":
            box.seal(b"synthetic-secret", {"kind": "apple_grant"})
        elif operation == "short_envelope":
            box.open(
                "bb-auth.v1.v1." + base64.urlsafe_b64encode(b"short").decode(), context
            )
        else:
            box.open(box.seal(b"synthetic-secret", context) + "=", context)
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("code", ["12345", "１２３４５６", None])
def test_022_fr008_invalid_code_format_and_missing_key_never_verify(code):
    """Malformed codes and unavailable retained keys reject without comparison authority."""
    box = AuthSecretBox({"v1": b"1" * 32}, "v1")
    context = SecretContext("email_code")
    assert not box.verify_code(code, "a" * 64, context, key_id="v1")
    assert not box.verify_code("123456", "a" * 64, context, key_id="missing")


@pytest.mark.parametrize(
    "value,scope",
    [(None, "address"), ("owner@example.com", ""), ("owner@example.com", None)],
)
def test_022_fr021_invalid_budget_dimensions_cannot_make_fingerprints(value, scope):
    """Missing fingerprint dimensions cannot reset or create a different abuse authority."""
    box = AuthSecretBox({"v1": b"1" * 32}, "v1")
    with pytest.raises(AuthSecretError):
        box.budget_fingerprints(value, scope)
    with pytest.raises(AuthSecretError):
        box.grant_digest("")


@pytest.mark.parametrize(
    "operation", ["record", "schedule", "replace", "dispatch", "notice"]
)
def test_022_fr025_apple_transaction_boundaries_fail_without_provider_io(
    apple_fixture, operation
):
    """Apple writes require a transaction and provider I/O refuses a caller-held write."""
    store, _, lifecycle, gateway, _, _ = apple_fixture
    called = []
    gateway.verify_notification = lambda _payload: called.append(True)
    with pytest.raises(AuthAppleLifecycleError) as error:
        if operation in {"dispatch", "notice"}:
            with store.transaction():
                if operation == "dispatch":
                    lifecycle.dispatch_one()
                else:
                    lifecycle.process_notification("synthetic signed payload")
        else:
            with store.connection() as connection:
                if operation == "record":
                    lifecycle.record_grant(connection, "binding", apple._tokens())
                elif operation == "schedule":
                    lifecycle.schedule_cleanup(connection, "binding", "unlink")
                else:
                    lifecycle.ensure_replaceable(connection, "binding")
    assert error.value.status_code == 503
    assert called == gateway.revocations == []
    assert apple._rows(store, "auth_apple_grants") == []


@pytest.mark.parametrize("failure", ["missing_binding", "missing_box", "seal_failure"])
def test_022_fr021_apple_grant_storage_failure_never_commits(
    apple_fixture, failure, monkeypatch
):
    """Unavailable owners or encryption cannot commit a plaintext or partial grant."""
    store, _, lifecycle, _, box, _ = apple_fixture
    binding = "missing" if failure == "missing_binding" else "binding"
    if failure == "missing_box":
        lifecycle.secret_box = None
    elif failure == "seal_failure":

        def unavailable(*_args):
            raise AuthSecretError()

        monkeypatch.setattr(box, "seal", unavailable)
    with pytest.raises(AuthAppleLifecycleError), store.transaction() as connection:
        lifecycle.record_grant(connection, binding, apple._tokens())
    assert apple._rows(store, "auth_apple_grants") == []
    assert (
        json.loads(apple._rows(store, "auth_identity_bindings")[0]["payload_json"])
        == {}
    )


@pytest.mark.parametrize(
    "damage", ["missing_payload", "key_id", "wrong_fields", "wrong_type"]
)
def test_022_fr021_corrupt_apple_cleanup_material_is_erased_without_revoke(
    apple_fixture, damage
):
    """Valid encryption cannot legitimize malformed minimum-grant contents or mismatched key metadata."""
    store, _, lifecycle, gateway, box, _ = apple_fixture
    with store.transaction() as connection:
        lifecycle.record_grant(connection, "binding", apple._tokens())
        lifecycle.schedule_cleanup(connection, "binding", "unlink")
        job = connection.execute("SELECT * FROM auth_apple_cleanup_jobs").fetchone()
        if damage == "missing_payload":
            connection.execute("UPDATE auth_apple_cleanup_jobs SET sealed_payload=NULL")
        elif damage == "key_id":
            connection.execute("UPDATE auth_apple_cleanup_jobs SET key_id='different'")
        else:
            payload = (
                {}
                if damage == "wrong_fields"
                else {"token": [], "token_type": "refresh_token"}
            )
            sealed = box.seal(
                json.dumps(payload).encode(), lifecycle._context(job, "apple_cleanup")
            )
            connection.execute(
                "UPDATE auth_apple_cleanup_jobs SET sealed_payload=?", (sealed,)
            )
    assert not lifecycle.dispatch_one()
    assert gateway.revocations == []
    job = apple._rows(store, "auth_apple_cleanup_jobs")[0]
    assert job["status"] == "failed" and job["sealed_payload"] is None


def test_022_fr025_obsolete_pending_job_never_revokes_new_generation(apple_fixture):
    """Generation mismatch retires queued remote work before contacting Apple."""
    store, _, lifecycle, gateway, _, _ = apple_fixture
    with store.transaction() as connection:
        lifecycle.record_grant(connection, "binding", apple._tokens())
        lifecycle.schedule_cleanup(connection, "binding", "unlink")
        connection.execute("UPDATE auth_identity_bindings SET generation=2")
    assert not lifecycle.dispatch_one()
    assert gateway.revocations == []
    assert apple._rows(store, "auth_apple_cleanup_jobs")[0]["status"] == "cancelled"


def test_022_fr025_cleanup_backoff_prevents_immediate_repeat(apple_fixture):
    """An unconfirmed revocation retains its bounded retry while refusing immediate redelivery."""
    store, _, lifecycle, gateway, _, _ = apple_fixture
    gateway.failure = True
    with store.transaction() as connection:
        lifecycle.record_grant(connection, "binding", apple._tokens())
        lifecycle.schedule_cleanup(connection, "binding", "unlink")
    assert lifecycle.dispatch_one()
    assert not lifecycle.dispatch_one()
    job = apple._rows(store, "auth_apple_cleanup_jobs")[0]
    assert job["status"] == "pending" and job["attempts"] == 1
    assert len(gateway.revocations) == 1


@pytest.mark.parametrize(
    "code,status", [("invalid_proof", 400), ("provider_unavailable", 503)]
)
def test_022_fr025_notification_gateway_failure_has_no_receipt(
    apple_fixture, code, status
):
    """Verification outages and invalid signatures cannot create replay or revocation authority."""
    store, _, lifecycle, gateway, _, _ = apple_fixture

    def rejected(_payload):
        raise ProviderError(code)

    gateway.verify_notification = rejected
    with pytest.raises(AuthAppleLifecycleError) as error:
        lifecycle.process_notification("synthetic invalid payload")
    assert error.value.status_code == status
    assert apple._rows(store, "auth_apple_notification_receipts") == []
    assert apple._rows(store, "auth_identity_bindings")[0]["state"] == "active"


@pytest.mark.parametrize(
    "changes", [{"email": "foreign@example.com"}, {"is_private_email": False}]
)
def test_022_fr025_foreign_relay_notice_cannot_change_delivery_method(
    apple_fixture, changes
):
    """Forwarding notices must match the bound relay destination and private-email profile."""
    store, _, lifecycle, gateway, _, _ = apple_fixture
    gateway.notification = replace(
        gateway.notification,
        **(
            {
                "event_type": "email-disabled",
                "email": "relay@example.com",
                "is_private_email": True,
            }
            | changes
        ),
    )
    lifecycle.process_notification("synthetic signed relay notice")
    binding = apple._rows(store, "auth_identity_bindings")[0]
    assert "email_delivery_disabled" not in json.loads(binding["payload_json"])
    assert binding["state"] == "active"


@pytest.mark.parametrize("operation", ["enqueue", "resend", "verify"])
def test_022_fr008_unknown_mail_challenge_has_no_authority(tmp_path, operation):
    """Missing challenges fail before creating delivery, guess or recovery authority."""
    mail = email.service(tmp_path, email.Clock())
    with pytest.raises(AuthMailError):
        if operation == "enqueue":
            mail.enqueue("missing", "123456")
        elif operation == "resend":
            mail.resend("missing", network="network")
        else:
            mail.verify_code("missing", "123456", network="network")
    assert apple._rows(mail.store, "auth_mail_jobs") == []
    assert apple._rows(mail.store, "auth_budgets") == []


def test_022_fr008_duplicate_enqueue_preserves_original_pending_code(tmp_path):
    """A second enqueue cannot silently replace the code within a challenge generation."""
    clock = email.Clock()
    sent = []
    mail = email.service(tmp_path, clock, send=lambda *args: sent.append(args))
    email.challenge(mail, clock)
    job = mail.enqueue("c", "123456")
    with pytest.raises(AuthMailError):
        mail.enqueue("c", "654321")
    assert len(apple._rows(mail.store, "auth_mail_jobs")) == 1
    assert email.row(mail, "auth_mail_jobs", job)["status"] == "pending"
    assert sent == []
    assert mail.dispatch_one()
    assert sent[0][1] == "123456"


def test_022_fr008_resend_does_not_reuse_randomly_repeated_code(tmp_path, monkeypatch):
    """A random collision regenerates the code without resetting expiry or activating the old proof."""
    clock = email.Clock()
    sent = []
    mail = email.service(tmp_path, clock, send=lambda *args: sent.append(args))
    email.challenge(mail, clock)
    mail.enqueue("c", "123456")
    assert mail.dispatch_one()
    expiry = email.row(mail, "auth_challenges", "c")["expires_at"]
    clock.advance(61)
    values = iter([123456, 654321])
    monkeypatch.setattr(
        "app.services.auth_mail_service.secrets.randbelow", lambda _bound: next(values)
    )
    mail.resend("c", network="network")
    assert mail.dispatch_one()
    assert [message[1] for message in sent] == ["123456", "654321"]
    with mail.store.transaction() as connection:
        assert not mail.code_matches(connection, "c", "123456")
        assert mail.code_matches(connection, "c", "654321")
    assert email.row(mail, "auth_challenges", "c")["expires_at"] == expiry


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"recipient": "c@example.com"},
        {"recipient": "c@example.com", "code": 123456, "purpose": "login"},
    ],
)
def test_022_fr010_semantically_corrupt_sealed_mail_never_sends(tmp_path, payload):
    """Authentic ciphertext with a malformed message structure is erased without activating a code."""
    clock = email.Clock()
    sent = []
    mail = email.service(tmp_path, clock, send=lambda *args: sent.append(args))
    email.challenge(mail, clock)
    job = mail.enqueue("c", "123456")
    with mail.store.transaction() as connection:
        challenge = connection.execute(
            "SELECT * FROM auth_challenges WHERE id='c'"
        ).fetchone()
        sealed = mail.secret_box.seal(
            json.dumps(payload).encode(), mail._context(challenge, "mail_job")
        )
        connection.execute(
            "UPDATE auth_mail_jobs SET sealed_payload=? WHERE id=?", (sealed, job)
        )
    assert not mail.dispatch_one()
    assert sent == []
    assert email.row(mail, "auth_mail_jobs", job)["sealed_payload"] is None
    assert email.row(mail, "auth_challenges", "c")["code_hmac"] is None


def test_022_fr010_smtp_recipient_refusal_never_activates_code(tmp_path, monkeypatch):
    """An SMTP recipient refusal leaves proof unusable and erases the queued secret."""
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    smtp.send_message.return_value = {"c@example.com": (550, b"synthetic refusal")}
    monkeypatch.setattr(
        "app.services.auth_mail_service.smtplib.SMTP", lambda *_args, **_kwargs: smtp
    )
    clock = email.Clock()
    mail = AuthMailService(
        AuthStore(tmp_path),
        AuthSecretBox({"k1": b"1" * 32}, "k1"),
        email.settings(),
        clock=clock,
    )
    email.challenge(mail, clock)
    job = mail.enqueue("c", "123456")
    assert mail.dispatch_one()
    assert email.row(mail, "auth_challenges", "c")["status"] == "failed"
    assert email.row(mail, "auth_mail_jobs", job)["sealed_payload"] is None
    assert not mail.verify_code("c", "123456", network="network")


def test_022_fr010_dispatch_selects_only_one_of_multiple_pending_jobs(tmp_path):
    """Each dispatch acknowledges one selected challenge while leaving another pending."""
    clock = email.Clock()
    sent = []
    mail = email.service(tmp_path, clock, send=lambda *args: sent.append(args))
    for identifier in ("a", "b"):
        email.challenge(mail, clock, identifier)
        mail.enqueue(identifier, "123456")
    assert mail.dispatch_one()
    assert sorted(
        row["status"] for row in apple._rows(mail.store, "auth_challenges")
    ) == ["active", "pending"]
    assert len(sent) == 1
    assert mail.dispatch_one()
    assert len(sent) == 2


@pytest.mark.parametrize(
    "body", [b"[]", b'{"id_token":"synthetic-private","id_token":"duplicate-private"}']
)
def test_022_fr004_provider_response_shape_cannot_supply_identity(apple_key, body):
    """Array and duplicate-member provider responses fail before signature/key lookup."""
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, content=body)

    gateway = AuthProviderService(
        provider.settings(apple_key),
        client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    with pytest.raises(ProviderError) as error:
        provider.exchange_google(gateway)
    assert len(requests) == 1
    assert "synthetic-private" not in str(error.value)


@pytest.mark.parametrize("keys", [None, [], [{}] * 33])
def test_022_fr004_invalid_jwks_collection_cannot_authorize(rsa_key, apple_key, keys):
    """Missing, empty or oversized key collections fail within the bounded refresh profile."""
    token = provider.assertion(rsa_key, provider.claims())
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=(
                {"id_token": token}
                if request.url.path.endswith("/token")
                else {"keys": keys}
            ),
        )

    gateway = AuthProviderService(
        provider.settings(apple_key),
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        clock=lambda: float(provider.NOW),
    )
    with pytest.raises(ProviderError):
        provider.exchange_google(gateway)
    assert len(requests) == 2


@pytest.mark.parametrize("address", [123, "not-an-address", "x" * 321])
def test_022_fr004_signed_invalid_email_cannot_establish_identity(
    rsa_key, apple_key, address
):
    """Even correctly signed provider claims must carry a structurally valid optional mailbox."""
    token = provider.assertion(rsa_key, provider.claims(email=address))
    gateway, _, _ = provider.gateway(rsa_key, apple_key, token)
    with pytest.raises(ProviderError):
        provider.exchange_google(gateway)


@pytest.mark.parametrize(
    "operation",
    [
        "prefix",
        "notification_audience",
        "google_verifier",
        "apple_pkce",
        "revocation_hint",
    ],
)
def test_022_fr004_invalid_provider_options_never_contact_upstream(
    apple_key, operation
):
    """Invalid route, audience and protocol options fail before any external request."""
    requests = []
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: requests.append(request))
    )
    settings = provider.settings(apple_key)
    with pytest.raises(ProviderError):
        if operation == "prefix":
            AuthProviderService(
                settings, client=client, api_prefix="https://foreign.example"
            )
        elif operation == "notification_audience":
            AuthProviderService(
                settings, client=client, notification_audience="foreign-client"
            )
        else:
            gateway = AuthProviderService(settings, client=client)
            if operation == "revocation_hint":
                gateway.revoke_apple(
                    SecretStr("synthetic-grant"),
                    settings.apple_services_id,
                    token_type="id_token",
                )
            else:
                selected = "google" if operation == "google_verifier" else "apple"
                gateway.authorization_url(
                    selected,
                    state="state",
                    nonce="nonce",
                    redirect_uri=gateway.callback_uri(selected),
                    pkce_verifier=(
                        "short" if selected == "google" else provider.VERIFIER
                    ),
                )
    assert requests == []


def test_022_fr004_absent_api_origin_cannot_form_callback():
    """Unavailable callback origin never manufactures an upstream redirect destination."""
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: pytest.fail("unexpected provider IO")
        )
    )
    with pytest.raises(ProviderError):
        AuthProviderService(ModernAuthSettings(), client=client).callback_uri("google")


def test_022_fr025_native_apple_cannot_use_web_redirect(rsa_key, apple_key):
    """A valid native assertion cannot turn its exchange into a web-redirect transaction."""
    token = provider.assertion(rsa_key, provider.claims("apple", aud="com.example.app"))
    gateway, requests, _ = provider.gateway(rsa_key, apple_key, token)
    with pytest.raises(ProviderError):
        gateway.exchange_apple(
            "synthetic-code",
            nonce=provider.NONCE,
            native_identity_token=token,
            redirect_uri=gateway.callback_uri("apple"),
        )
    assert all(request.method == "GET" for request in requests)


def test_022_fr025_signed_notification_requires_encoded_event_object(
    rsa_key, apple_key
):
    """A signed wrong event representation cannot become notification authority."""
    gateway, _, _ = provider.gateway(rsa_key, apple_key, "unused")
    token = provider.assertion(
        rsa_key,
        provider.notification_claims(
            events={
                "type": "account-deleted",
                "sub": "subject",
                "event_time": provider.NOW,
            }
        ),
    )
    with pytest.raises(ProviderError):
        gateway.verify_notification(token)


def test_022_fr021_apple_signing_engine_failure_never_sends_code(
    apple_key, monkeypatch
):
    """Client-secret signing failure exposes only a coarse error and never exchanges a code."""
    requests = []
    gateway = AuthProviderService(
        provider.settings(apple_key),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: requests.append(request))
        ),
    )

    def unavailable(_key):
        raise ValueError("synthetic private signing engine detail")

    monkeypatch.setattr(
        "app.services.auth_provider_service.ECKey.import_key", unavailable
    )
    with pytest.raises(ProviderError) as error:
        gateway.exchange_apple(
            "synthetic-code",
            nonce=provider.NONCE,
            redirect_uri=gateway.callback_uri("apple"),
        )
    assert requests == []
    assert "private signing" not in str(error.value)
