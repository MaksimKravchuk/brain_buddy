"""Purpose-separated proof hashes and protected short-lived auth payloads."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import ModernAuthSettings
from app.services.auth_secret_box import AuthSecretBox, AuthSecretError, SecretContext


def context() -> SecretContext:
    return SecretContext(
        kind="apple_grant",
        attempt_id="attempt",
        binding_id="binding",
        owner_id="owner",
        client_id="client",
        generation=2,
    )


def box() -> AuthSecretBox:
    return AuthSecretBox({"key-1": b"1" * 32}, "key-1")


def test_023_FR_021_sealed_payload_has_random_nonce_and_no_plaintext() -> None:
    """Repeated sealing protects plaintext with fresh authenticated encryption."""
    secret_box = box()
    payload = b"synthetic-refresh-grant"
    first = secret_box.seal(payload, context())
    second = secret_box.seal(payload, context())
    assert first != second
    assert payload.decode() not in first
    assert secret_box.open(first, context()) == payload
    assert secret_box.open(second, context()) == payload
    assert "111111111111" not in repr(secret_box)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "mail_job"),
        ("attempt_id", "other-attempt"),
        ("binding_id", "other-binding"),
        ("owner_id", "other-owner"),
        ("client_id", "other-client"),
        ("generation", 3),
    ],
)
def test_023_FR_021_every_context_dimension_is_authenticated(
    field: str, value: str | int
) -> None:
    """Changing payload purpose, attempt, binding, owner, client or generation fails."""
    secret_box = box()
    sealed = secret_box.seal(b"synthetic-refresh-grant", context())
    replacement: dict[str, Any] = {field: value}
    with pytest.raises(AuthSecretError, match="authentication secret"):
        secret_box.open(sealed, replace(context(), **replacement))


@pytest.mark.parametrize("mutation", ["ciphertext", "key", "version", "malformed"])
def test_023_FR_021_tamper_unknown_keys_and_malformed_envelopes_fail_safely(
    mutation: str,
) -> None:
    """Tampering and malformed envelopes raise a generic secret-free error."""
    secret_box = box()
    sealed = secret_box.seal(b"synthetic-refresh-grant", context())
    if mutation == "ciphertext":
        parts = sealed.split(".")
        blob = bytearray(base64.urlsafe_b64decode(parts[-1]))
        blob[-1] ^= 1
        parts[-1] = base64.urlsafe_b64encode(blob).decode()
        sealed = ".".join(parts)
    elif mutation == "key":
        sealed = sealed.replace("key-1", "unknown-key")
    elif mutation == "version":
        sealed = sealed.replace("v1", "v0")
    else:
        sealed = "synthetic-plaintext-fallback"
    with pytest.raises(AuthSecretError) as error:
        secret_box.open(sealed, context())
    assert sealed not in str(error.value)
    assert "synthetic" not in str(error.value)


def test_023_FR_021_envelope_key_id_cannot_be_swapped_even_for_identical_master() -> (
    None
):
    """The envelope key ID is authenticated independently of master material."""
    secret_box = AuthSecretBox({"key-1": b"1" * 32, "key-2": b"1" * 32}, "key-1")
    sealed = secret_box.seal(b"synthetic", context()).replace("key-1", "key-2")
    with pytest.raises(AuthSecretError):
        secret_box.open(sealed, context())


def test_023_FR_023_rotation_preserves_old_decrypt_and_budget_authority() -> None:
    """Retained keys protect old payloads and prevent reset of active abuse windows."""
    original = box()
    sealed = original.seal(b"synthetic", context())
    original_fingerprints = original.budget_fingerprints(
        "address@example.com", "address"
    )
    rotated = AuthSecretBox({"key-1": b"1" * 32, "key-2": b"2" * 32}, "key-2")
    assert rotated.open(sealed, context()) == b"synthetic"
    fingerprints = rotated.budget_fingerprints("address@example.com", "address")
    assert fingerprints["key-1"] == original_fingerprints["key-1"]
    assert fingerprints["key-2"] != fingerprints["key-1"]
    assert rotated.current_key_id == "key-2"
    assert rotated.key_ids == ("key-2", "key-1")
    assert ".key-2." in rotated.seal(b"synthetic", context())
    with pytest.raises(AuthSecretError):
        AuthSecretBox({"key-2": b"2" * 32}, "key-2").open(sealed, context())


def test_023_FR_008_codes_use_keyed_context_bound_digest_and_retained_key_verification() -> (
    None
):
    """Six-digit codes use purpose-separated HMAC and survive controlled key rotation."""
    original = box()
    digest = original.code_digest("123456", context())
    assert digest != hashlib.sha256(b"123456").hexdigest()
    assert digest != original.budget_fingerprints("123456", "code")["key-1"]
    assert original.verify_code("123456", digest, context(), key_id="key-1")
    assert not original.verify_code("654321", digest, context(), key_id="key-1")
    assert not original.verify_code(
        "123456", digest, replace(context(), kind="mail_job"), key_id="key-1"
    )
    rotated = AuthSecretBox({"key-1": b"1" * 32, "key-2": b"2" * 32}, "key-2")
    assert rotated.verify_code("123456", digest, context(), key_id="key-1")
    assert not rotated.verify_code("123456", digest, context(), key_id="key-2")
    assert len(AuthSecretBox.grant_digest("high-entropy-synthetic-grant")) == 64
    assert (
        AuthSecretBox.grant_digest("high-entropy-synthetic-grant")
        == hashlib.sha256(b"high-entropy-synthetic-grant").hexdigest()
    )


@pytest.mark.parametrize(
    "keys,current",
    [
        ({}, "missing"),
        ({"key": b"short-secret"}, "key"),
        ({"key": b"x" * 33}, "key"),
        ({"key": b"x" * 32}, "absent"),
        ({"bad.id": b"x" * 32}, "bad.id"),
    ],
)
def test_023_FR_021_invalid_keyring_raises_only_safe_error(
    keys: dict[str, bytes], current: str
) -> None:
    """Missing keys and wrong key lengths never generate restart keys or leak values."""
    with pytest.raises(AuthSecretError) as error:
        AuthSecretBox(keys, current)
    assert "short-secret" not in str(error.value)
    assert str(error.value) == "Invalid authentication secret configuration or payload."


def test_023_FR_003_build_from_unavailable_settings_fails_closed() -> None:
    """Secret-box construction fails safely without usable deployment keys."""
    with pytest.raises(AuthSecretError):
        AuthSecretBox.from_settings(ModernAuthSettings())
    settings = ModernAuthSettings(
        current_key_id="key",
        keyring={"key": SecretStr(base64.b64encode(b"x" * 32).decode())},
    )
    assert AuthSecretBox.from_settings(settings).current_key_id == "key"
