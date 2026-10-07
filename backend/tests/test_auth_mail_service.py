"""Durable email delivery and abuse budgets, using synthetic SQLite accounts."""

from __future__ import annotations

import base64
import multiprocessing
import ssl
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import ModernAuthSettings
from app.repositories.auth_store import AuthStore
from app.services.auth_mail_service import (
    AuthMailError,
    AuthMailRateLimitError,
    AuthMailService,
)
from app.services.auth_secret_box import AuthSecretBox
from tests.auth_process_bootstrap import isolate_app_bootstrap

pytestmark = [
    pytest.mark.allure_label("Authentication & Access", label_type="epic"),
    pytest.mark.allure_label("Modern authentication", label_type="feature"),
    pytest.mark.allure_label(
        "023-FR-008 023-FR-009 023-FR-010 Email proofs", label_type="story"
    ),
]


@dataclass
class Clock:
    value: datetime = datetime(2026, 10, 6, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def settings() -> ModernAuthSettings:
    return ModernAuthSettings(
        public_origin="https://app.example.com",
        api_origin="https://api.example.com",
        smtp_host="smtp.example.com",
        smtp_sender="sender@example.com",
        smtp_username="synthetic-user",
        smtp_password=SecretStr("synthetic-password"),
        current_key_id="k1",
        keyring={"k1": SecretStr(base64.b64encode(b"1" * 32).decode())},
    )


def service(
    root: Path,
    clock: Clock,
    send: Callable[[str, str, str], None] | None = None,
    box: AuthSecretBox | None = None,
) -> AuthMailService:
    return AuthMailService(
        AuthStore(root),
        box or AuthSecretBox({"k1": b"1" * 32}, "k1"),
        settings(),
        send=send or (lambda _recipient, _code, _purpose: None),
        clock=clock,
    )


def challenge(
    mail: AuthMailService, clock: Clock, identifier: str = "c", *, eligible: bool = True
) -> None:
    with mail.store.transaction() as conn:
        conn.execute(
            "INSERT INTO auth_challenges(id,purpose,destination,client_challenge,"
            "eligible,created_at,expires_at,resend_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                identifier,
                "login",
                f"{identifier}@example.com",
                "client",
                int(eligible),
                clock().isoformat(),
                (clock() + timedelta(minutes=10)).isoformat(),
                (clock() + timedelta(seconds=60)).isoformat(),
            ),
        )


def row(mail: AuthMailService, table: str, identifier: str) -> dict[str, object]:
    assert table in {"auth_challenges", "auth_mail_jobs"}
    with mail.store.connection() as conn:
        result = conn.execute(
            f"SELECT * FROM {table} WHERE id=?", (identifier,)
        ).fetchone()
        assert result is not None
        return dict(result)


def test_023_FR_008_delivery_ack_activates_code_and_erases_sealed_payload(
    tmp_path: Path,
) -> None:
    """Only acknowledged delivery activates a code; SMTP runs outside the write transaction."""
    clock = Clock()
    sent: list[tuple[str, str, str]] = []

    def send(recipient: str, code: str, purpose: str) -> None:
        with AuthStore(tmp_path).transaction() as conn:
            assert (
                conn.execute(
                    "SELECT status FROM auth_challenges WHERE id='c'"
                ).fetchone()[0]
                == "pending"
            )
        sent.append((recipient, code, purpose))

    mail = service(tmp_path, clock, send)
    challenge(mail, clock)
    job_id = mail.enqueue("c", "123456")
    queued = row(mail, "auth_mail_jobs", job_id)
    assert "123456" not in str(queued["sealed_payload"])
    assert "c@example.com" not in str(queued["sealed_payload"])
    with mail.store.connection() as conn:
        assert not mail.code_matches(conn, "c", "123456")
    assert mail.dispatch_one()
    assert sent == [("c@example.com", "123456", "login")]
    assert row(mail, "auth_challenges", "c")["status"] == "active"
    assert row(mail, "auth_mail_jobs", job_id)["sealed_payload"] is None
    assert row(mail, "auth_mail_jobs", job_id)["key_id"] is None
    assert mail.verify_code("c", "123456", network="network")
    assert not mail.dispatch_one()


@pytest.mark.parametrize("eligible", [False])
def test_023_FR_010_inert_challenges_never_enqueue(
    tmp_path: Path, eligible: bool
) -> None:
    """An ineligible public challenge cannot acquire delivery or code authority."""
    clock = Clock()
    mail = service(tmp_path, clock)
    challenge(mail, clock, eligible=eligible)
    with pytest.raises(AuthMailError):
        mail.enqueue("c", "123456")
    with mail.store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM auth_mail_jobs").fetchone()[0] == 0
    assert not mail.verify_code("c", "123456", network="network")


def test_023_FR_009_transport_failure_never_retries_or_refunds(tmp_path: Path) -> None:
    """Failed delivery erases its payload and cannot authorize or refund its reserved send."""
    clock = Clock()
    sends: list[str] = []

    def fail(_recipient: str, code: str, _purpose: str) -> None:
        sends.append(code)
        raise OSError("synthetic-password and 123456 must not escape")

    mail = service(tmp_path, clock, fail)
    challenge(mail, clock)
    mail.reserve_send("c@example.com", "client", "network")
    job = mail.enqueue("c", "123456")
    assert mail.dispatch_one()
    assert not mail.dispatch_one()
    assert sends == ["123456"]
    assert row(mail, "auth_mail_jobs", job)["sealed_payload"] is None
    assert row(mail, "auth_challenges", "c")["code_hmac"] is None
    assert not mail.verify_code("c", "123456", network="network")
    with pytest.raises(AuthMailRateLimitError):
        mail.reserve_send("c@example.com", "client", "network")


def test_023_FR_009_crashed_lease_is_invalidated_across_restart(tmp_path: Path) -> None:
    """A worker crash with uncertain delivery leaves a lease that expires without retry."""
    clock = Clock()

    def crash(_recipient: str, _code: str, _purpose: str) -> None:
        raise KeyboardInterrupt

    mail = service(tmp_path, clock, crash)
    challenge(mail, clock)
    job = mail.enqueue("c", "123456")
    with pytest.raises(KeyboardInterrupt):
        mail.dispatch_one()
    clock.advance(31)
    replacement = service(
        tmp_path, clock, lambda *_: pytest.fail("uncertain mail was retried")
    )
    assert not replacement.dispatch_one()
    assert row(replacement, "auth_mail_jobs", job)["status"] == "failed"
    assert row(replacement, "auth_mail_jobs", job)["sealed_payload"] is None
    assert not replacement.verify_code("c", "123456", network="network")


def test_023_FR_008_resend_preserves_expiry_and_guesses_invalidates_old_code(
    tmp_path: Path,
) -> None:
    """Explicit resend changes generation/code without resetting guesses or outer expiry."""
    clock = Clock()
    sent: list[str] = []
    mail = service(tmp_path, clock, lambda _r, code, _p: sent.append(code))
    challenge(mail, clock)
    mail.reserve_send("c@example.com", "client", "network")
    mail.enqueue("c", "123456")
    mail.dispatch_one()
    assert not mail.verify_code("c", "654321", network="network")
    original = row(mail, "auth_challenges", "c")
    with pytest.raises(AuthMailRateLimitError):
        mail.resend("c", network="network")
    clock.advance(60)
    mail.resend("c", network="network")
    pending = row(mail, "auth_challenges", "c")
    assert pending["expires_at"] == original["expires_at"]
    assert pending["failures"] == 1
    assert pending["generation"] == 2
    mail.dispatch_one()
    assert sent[-1] != "123456"
    assert not mail.verify_code("c", "123456", network="network")
    assert mail.verify_code("c", sent[-1], network="network")


def test_023_FR_008_late_old_generation_ack_cannot_activate_replacement(
    tmp_path: Path,
) -> None:
    """A resend racing an in-flight send cannot activate its replacement with the old ACK."""
    clock = Clock()
    sent: list[str] = []
    mail = service(tmp_path, clock)

    def send(_recipient: str, code: str, _purpose: str) -> None:
        sent.append(code)
        if len(sent) == 1:
            clock.advance(60)
            mail.resend("c", network="network")

    mail = service(tmp_path, clock, send)
    challenge(mail, clock)
    mail.reserve_send("c@example.com", "client", "network")
    mail.enqueue("c", "123456")
    assert mail.dispatch_one()
    assert row(mail, "auth_challenges", "c")["status"] == "pending"
    assert mail.dispatch_one()
    assert mail.verify_code("c", sent[-1], network="network")
    assert not mail.verify_code("c", sent[0], network="network")


def test_023_FR_008_failed_guesses_commit_and_five_challenge_limit_survives_restart(
    tmp_path: Path,
) -> None:
    """Five failed guesses persist before rejection; correct code cannot bypass exhaustion."""
    clock = Clock()
    mail = service(tmp_path, clock)
    challenge(mail, clock)
    mail.enqueue("c", "123456")
    mail.dispatch_one()
    for _ in range(5):
        assert not mail.verify_code("c", "654321", network="network")
    replacement = service(tmp_path, clock)
    assert row(replacement, "auth_challenges", "c")["failures"] == 5
    assert not replacement.verify_code("c", "123456", network="network")
    with replacement.store.transaction() as conn:
        assert not replacement.code_matches(conn, "c", "123456")
    with replacement.store.transaction(), pytest.raises(AuthMailError):
        replacement.verify_code("c", "123456", network="network")


@pytest.mark.parametrize(
    "kind,scope,limit",
    [
        ("send", "address", 5),
        ("send", "client", 20),
        ("send", "network", 50),
        ("guess", "address", 10),
        ("guess", "client", 30),
        ("guess", "network", 100),
    ],
)
def test_023_FR_009_rolling_limits_are_independent_and_persistent(
    tmp_path: Path, kind: str, scope: str, limit: int
) -> None:
    """All address/client/network rolling limits survive service/process reconstruction."""
    clock = Clock()
    mail = service(tmp_path, clock)

    def reserve(index: int, worker: AuthMailService) -> None:
        address = "same@example.com" if scope == "address" else f"a{index}@example.com"
        client = "same-client" if scope == "client" else f"client-{index}"
        network = "same-network" if scope == "network" else f"network-{index}"
        getattr(worker, f"reserve_{kind}")(address, client, network)

    for index in range(limit):
        reserve(index, mail)
        if kind == "send" and scope == "address":
            clock.advance(60)
    rotated = service(
        tmp_path, clock, box=AuthSecretBox({"k1": b"1" * 32, "k2": b"2" * 32}, "k2")
    )
    with pytest.raises(AuthMailRateLimitError):
        reserve(limit, rotated)
    clock.advance(3601)
    reserve(limit, rotated)
    with rotated.store.connection() as conn:
        assert not conn.execute(
            "SELECT 1 FROM auth_budgets WHERE key_id='k1'"
        ).fetchone()
        serialized = " ".join(
            str(tuple(value)) for value in conn.execute("SELECT * FROM auth_budgets")
        )
        assert "same@example.com" not in serialized
        assert "same-client" not in serialized
        assert "same-network" not in serialized


def test_023_FR_009_missing_retained_budget_key_fails_closed(tmp_path: Path) -> None:
    """Removing an active key cannot reset its still-live abuse authority."""
    clock = Clock()
    mail = service(tmp_path, clock)
    mail.reserve_guess("c@example.com", "client", "network")
    replacement = service(tmp_path, clock, box=AuthSecretBox({"k2": b"2" * 32}, "k2"))
    with pytest.raises(AuthMailError):
        replacement.reserve_guess("c@example.com", "client", "network")


def test_023_FR_009_concurrent_two_store_reservations_do_not_exceed_client_limit(
    tmp_path: Path,
) -> None:
    """Independent SQLite connections serialize contested shared-client reservations."""
    clock = Clock()
    mail = service(tmp_path, clock)
    other = service(tmp_path, clock)

    def reserve(index: int) -> bool:
        try:
            (mail if index % 2 else other).reserve_guess(
                f"a{index}@example.com", "client", f"n{index}"
            )
            return True
        except AuthMailRateLimitError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(reserve, range(40)))
    assert sum(admitted) == 30


def test_023_FR_008_outer_transaction_rollback_and_finalization_recheck(
    tmp_path: Path,
) -> None:
    """Enqueue/budgets join root transactions; a consumed code fails the final recheck."""
    clock = Clock()
    mail = service(tmp_path, clock)
    with pytest.raises(RuntimeError), mail.store.transaction():
        challenge(mail, clock)
        mail.reserve_send("c@example.com", "client", "network")
        mail.enqueue("c", "123456")
        raise RuntimeError("synthetic rollback")
    with mail.store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM auth_mail_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM auth_budgets").fetchone()[0] == 0
    challenge(mail, clock)
    mail.enqueue("c", "123456")
    mail.dispatch_one()
    assert mail.verify_code("c", "123456", network="network")
    with mail.store.transaction() as conn:
        assert mail.code_matches(conn, "c", "123456")
        conn.execute("UPDATE auth_challenges SET status='consumed' WHERE id='c'")
        assert not mail.code_matches(conn, "c", "123456")


def test_023_FR_008_expiry_invalidates_payload_and_never_dispatches(
    tmp_path: Path,
) -> None:
    """The outer lifetime expires pending delivery and cannot be extended by resend."""
    clock = Clock()
    mail = service(tmp_path, clock, lambda *_: pytest.fail("expired code sent"))
    challenge(mail, clock)
    job = mail.enqueue("c", "123456")
    clock.advance(600)
    assert not mail.dispatch_one()
    assert row(mail, "auth_mail_jobs", job)["sealed_payload"] is None
    assert not mail.verify_code("c", "123456", network="network")
    with pytest.raises(AuthMailError):
        mail.resend("c", network="network")


def _process_budget_reservations(arguments: tuple[str, int]) -> int:
    root, offset = arguments
    mail = service(Path(root), Clock())
    admitted = 0
    for index in range(offset, offset + 20):
        try:
            mail.reserve_guess(f"a{index}@example.com", "process-client", f"n{index}")
            admitted += 1
        except AuthMailRateLimitError:
            continue
    return admitted


def test_023_FR_009_distinct_processes_preserve_shared_budget_limit(
    tmp_path: Path,
) -> None:
    """Separate processes sharing one volume cannot each spend a full client budget."""
    service(tmp_path, Clock())
    with ProcessPoolExecutor(
        max_workers=2,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=isolate_app_bootstrap,
        initargs=(str(tmp_path / "worker-apps"),),
    ) as pool:
        admitted = list(
            pool.map(
                _process_budget_reservations, [(str(tmp_path), 0), (str(tmp_path), 20)]
            )
        )
    assert sum(admitted) == 30


def test_023_FR_009_shared_exhaustion_rejects_valid_code_without_mutating_counter(
    tmp_path: Path,
) -> None:
    """A correct code cannot bypass an exhausted shared budget or refund failures."""
    clock = Clock()
    mail = service(tmp_path, clock)
    challenge(mail, clock)
    mail.enqueue("c", "123456")
    mail.dispatch_one()
    assert mail.verify_code("c", "123456", network="network")
    for _ in range(10):
        mail.reserve_guess("c@example.com", "client", "network")
    with pytest.raises(AuthMailRateLimitError):
        mail.verify_code("c", "123456", network="network")
    with mail.store.transaction() as conn, pytest.raises(AuthMailRateLimitError):
        mail.code_matches(conn, "c", "123456", network="network")
    assert row(mail, "auth_challenges", "c")["failures"] == 0


@pytest.mark.parametrize("mutation", ["client", "destination", "ciphertext", "key"])
def test_023_FR_010_tampered_context_and_missing_key_never_send(
    tmp_path: Path, mutation: str
) -> None:
    """AEAD context changes, corrupted payloads and missing old keys fail without dispatch."""
    clock = Clock()
    mail = service(tmp_path, clock, lambda *_: pytest.fail("tampered payload sent"))
    challenge(mail, clock)
    job = mail.enqueue("c", "123456")
    with mail.store.transaction() as conn:
        if mutation == "client":
            conn.execute(
                "UPDATE auth_challenges SET client_challenge='other' WHERE id='c'"
            )
        elif mutation == "destination":
            conn.execute(
                "UPDATE auth_challenges SET destination='other@example.com' WHERE id='c'"
            )
        elif mutation == "ciphertext":
            conn.execute(
                "UPDATE auth_mail_jobs SET sealed_payload='corrupt' WHERE id=?", (job,)
            )
    if mutation == "key":
        mail = service(
            tmp_path,
            clock,
            lambda *_: pytest.fail("missing key sent"),
            AuthSecretBox({"k2": b"2" * 32}, "k2"),
        )
    assert not mail.dispatch_one()
    assert row(mail, "auth_mail_jobs", job)["sealed_payload"] is None
    assert row(mail, "auth_challenges", "c")["code_hmac"] is None


@pytest.mark.parametrize("tls", ["starttls", "tls"])
def test_023_FR_010_default_smtp_requires_verified_tls_and_bounded_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tls: str
) -> None:
    """The default sender authenticates only after verified TLS, with a 10-second timeout."""
    calls: list[str] = []

    class SMTP:
        def __init__(
            self,
            host: str,
            port: int,
            *,
            timeout: int,
            context: ssl.SSLContext | None = None,
        ) -> None:
            assert host == "smtp.example.com" and port == 587 and timeout == 10
            calls.append("connect")
            if tls == "tls":
                assert context is not None and context.check_hostname
                assert context.verify_mode == ssl.CERT_REQUIRED
                calls.append("secure")

        def __enter__(self) -> SMTP:
            return self

        def __exit__(self, *_: object) -> None:
            calls.append("close")

        def ehlo(self) -> None:
            calls.append("ehlo")

        def starttls(self, *, context: ssl.SSLContext) -> None:
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            calls.append("secure")

        def login(self, username: str, password: str) -> None:
            assert "secure" in calls
            assert username == "synthetic-user" and password == "synthetic-password"
            calls.append("login")

        def send_message(self, message: Any) -> dict[str, object]:
            assert message["To"] == "c@example.com"
            assert "123456" in message.get_content()
            calls.append("send")
            return {}

    monkeypatch.setattr("app.services.auth_mail_service.smtplib.SMTP", SMTP)
    monkeypatch.setattr("app.services.auth_mail_service.smtplib.SMTP_SSL", SMTP)
    clock = Clock()
    mail = AuthMailService(
        AuthStore(tmp_path),
        AuthSecretBox({"k1": b"1" * 32}, "k1"),
        settings().model_copy(update={"smtp_tls": tls}),
        clock=clock,
    )
    challenge(mail, clock)
    mail.enqueue("c", "123456")
    assert mail.dispatch_one()
    assert calls.index("secure") < calls.index("login") < calls.index("send")


def test_023_FR_010_unconfigured_smtp_is_never_contacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Missing configuration fails closed without SMTP contact or sensitive logs."""
    monkeypatch.setattr(
        "app.services.auth_mail_service.smtplib.SMTP",
        lambda *_args, **_kwargs: pytest.fail("unconfigured SMTP contacted"),
    )
    clock = Clock()
    mail = AuthMailService(
        AuthStore(tmp_path),
        AuthSecretBox({"k1": b"1" * 32}, "k1"),
        ModernAuthSettings(),
        clock=clock,
    )
    challenge(mail, clock)
    mail.enqueue("c", "123456")
    assert mail.dispatch_one()
    assert "c@example.com" not in caplog.text
    assert "123456" not in caplog.text
    assert row(mail, "auth_challenges", "c")["code_hmac"] is None


def test_023_FR_008_code_hmac_binds_immutable_intent(tmp_path: Path) -> None:
    """Changing the challenge intent cannot repurpose its already delivered code."""
    clock = Clock()
    mail = service(tmp_path, clock)
    challenge(mail, clock)
    mail.enqueue("c", "123456")
    mail.dispatch_one()
    with mail.store.transaction() as conn:
        assert mail.code_matches(conn, "c", "123456")
        conn.execute("UPDATE auth_challenges SET purpose='recover' WHERE id='c'")
        assert not mail.code_matches(conn, "c", "123456")
