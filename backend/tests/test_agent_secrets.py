"""Credential-at-rest guarantees for external-agent connections (FR-003).

A saved connector secret is never returned after save and never persisted in
plaintext. These tests pin the storage primitive itself: authenticated
encryption, binding to the owning connection, key rotation, and a fail-closed
production posture when no key material is configured.
"""

from __future__ import annotations

import base64
from collections import OrderedDict

import pytest

from app.core.config import AppEnvironment
from app.modules.agents.secrets import (
    AAD_INBOUND_SIGNING_SECRET,
    AAD_OUTBOUND_CREDENTIAL,
    SealedSecret,
    SecretBox,
    SecretDecryptionFailed,
    SecretsUnavailable,
    build_secret_box,
    parse_secret_keys,
    secret_aad,
)

KEY_V1 = base64.b64encode(b"\x01" * 32).decode()
KEY_V2 = base64.b64encode(b"\x02" * 32).decode()


@pytest.fixture
def box() -> SecretBox:
    return SecretBox(parse_secret_keys(f"v1:{KEY_V1}"))


def test_sealing_then_opening_round_trips_the_secret(box: SecretBox) -> None:
    """A sealed credential opens back to exactly what was saved."""

    sealed = box.seal("hermes-token-value", aad="conn_1")

    assert box.open(sealed, aad="conn_1") == "hermes-token-value"


def test_ciphertext_never_contains_the_plaintext(box: SecretBox) -> None:
    """The stored blob leaks nothing about the credential."""

    sealed = box.seal("hermes-token-value", aad="conn_1")

    assert "hermes-token-value" not in sealed.ciphertext
    assert b"hermes-token-value" not in base64.b64decode(sealed.ciphertext)


def test_each_seal_uses_a_fresh_nonce(box: SecretBox) -> None:
    """Sealing the same value twice must not produce the same ciphertext."""

    first = box.seal("same-token", aad="conn_1")
    second = box.seal("same-token", aad="conn_1")

    assert first.ciphertext != second.ciphertext
    assert box.open(first, aad="conn_1") == box.open(second, aad="conn_1")


def test_a_ciphertext_cannot_be_moved_to_another_connection(box: SecretBox) -> None:
    """The connection ID is authenticated, so a stolen row cannot be relocated."""

    sealed = box.seal("hermes-token-value", aad="conn_1")

    with pytest.raises(SecretDecryptionFailed):
        box.open(sealed, aad="conn_2")


class TestOwnerBoundAssociatedData:
    """The AAD every relay secret is sealed under names owner *and* connection.

    Binding the connection alone leaves one gap: a row copied between two
    owners' connections that happen to share an ID, or a future ID scheme that
    is not globally unique, would still authenticate. Naming the owner closes
    it, and naming the purpose stops an outbound credential from ever being
    opened as if it were an inbound signing secret.
    """

    def _sealed(self, box: SecretBox) -> tuple[str, str]:
        aad = secret_aad(
            AAD_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_1"
        )
        return aad, box.seal("hermes-token-value", aad=aad).ciphertext

    def test_the_aad_names_the_purpose_owner_and_connection(self) -> None:
        """Each component is present, so none of them can be swapped silently."""

        aad = secret_aad(
            AAD_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_1"
        )

        assert AAD_OUTBOUND_CREDENTIAL in aad
        assert "user_a" in aad
        assert "conn_1" in aad

    def test_a_row_cannot_be_transplanted_to_another_owner(
        self, box: SecretBox
    ) -> None:
        """Same connection ID, different owner: the seal no longer authenticates."""

        sealed = box.seal(
            "hermes-token-value",
            aad=secret_aad(
                AAD_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_1"
            ),
        )

        with pytest.raises(SecretDecryptionFailed):
            box.open(
                sealed,
                aad=secret_aad(
                    AAD_OUTBOUND_CREDENTIAL, owner_id="user_b", connection_id="conn_1"
                ),
            )

    def test_a_row_cannot_be_transplanted_to_another_connection(
        self, box: SecretBox
    ) -> None:
        """Same owner, different connection: still refused."""

        sealed = box.seal(
            "hermes-token-value",
            aad=secret_aad(
                AAD_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_1"
            ),
        )

        with pytest.raises(SecretDecryptionFailed):
            box.open(
                sealed,
                aad=secret_aad(
                    AAD_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_2"
                ),
            )

    def test_purposes_are_domain_separated(self, box: SecretBox) -> None:
        """An outbound credential can never be opened as a signing secret."""

        sealed = box.seal(
            "hermes-token-value",
            aad=secret_aad(
                AAD_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_1"
            ),
        )

        with pytest.raises(SecretDecryptionFailed):
            box.open(
                sealed,
                aad=secret_aad(
                    AAD_INBOUND_SIGNING_SECRET,
                    owner_id="user_a",
                    connection_id="conn_1",
                ),
            )

    def test_a_bare_connection_id_no_longer_opens_a_relay_secret(
        self, box: SecretBox
    ) -> None:
        """Any row sealed under the old connection-only AAD fails closed."""

        legacy = box.seal("hermes-token-value", aad="conn_1")

        with pytest.raises(SecretDecryptionFailed):
            box.open(
                legacy,
                aad=secret_aad(
                    AAD_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_1"
                ),
            )


def test_tampered_ciphertext_is_rejected(box: SecretBox) -> None:
    """AES-GCM authentication rejects a modified blob rather than returning junk."""

    sealed = box.seal("hermes-token-value", aad="conn_1")
    raw = bytearray(base64.b64decode(sealed.ciphertext))
    raw[-1] ^= 0xFF
    tampered = sealed.model_copy(
        update={"ciphertext": base64.b64encode(bytes(raw)).decode()}
    )

    with pytest.raises(SecretDecryptionFailed):
        box.open(tampered, aad="conn_1")


def test_rotation_seals_with_the_active_key_and_still_opens_the_retired_one() -> None:
    """Adding a new active key keeps previously sealed credentials readable."""

    old = SecretBox(parse_secret_keys(f"v1:{KEY_V1}"))
    sealed_with_v1 = old.seal("legacy-token", aad="conn_1")

    rotated = SecretBox(parse_secret_keys(f"v2:{KEY_V2},v1:{KEY_V1}"))
    assert rotated.open(sealed_with_v1, aad="conn_1") == "legacy-token"

    fresh = rotated.seal("new-token", aad="conn_1")
    assert fresh.key_id == "v2"
    assert rotated.open(fresh, aad="conn_1") == "new-token"


def test_a_ciphertext_sealed_with_an_unknown_key_is_refused() -> None:
    """Losing key material fails loudly instead of silently returning nothing."""

    sealed = SecretBox(parse_secret_keys(f"v2:{KEY_V2}")).seal("token", aad="conn_1")
    other = SecretBox(parse_secret_keys(f"v1:{KEY_V1}"))

    with pytest.raises(SecretDecryptionFailed):
        other.open(sealed, aad="conn_1")


def test_repr_of_a_secret_box_never_exposes_key_material() -> None:
    """A box in a traceback or log line must not print its keys."""

    box = SecretBox(parse_secret_keys(f"v1:{KEY_V1}"))

    assert KEY_V1 not in repr(box)
    assert "\x01" * 32 not in repr(box)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "v1",
        "v1:",
        ":abcd",
        "v1:not-base64!!",
        # 16 bytes — AES-128 is not accepted; we require a 256-bit key.
        f"v1:{base64.b64encode(b'x' * 16).decode()}",
        f"v1:{KEY_V1},v1:{KEY_V2}",
    ],
)
def test_malformed_key_configuration_is_refused(raw: str) -> None:
    """Bad key configuration fails at parse time, not at first use."""

    with pytest.raises(SecretsUnavailable):
        parse_secret_keys(raw)


def test_blank_entries_around_a_valid_key_are_ignored() -> None:
    """Operator-friendly separators do not create phantom key declarations."""

    keys = parse_secret_keys(f", v1:{KEY_V1},")

    assert list(keys) == ["v1"]


def test_an_all_blank_key_list_is_refused() -> None:
    """A non-empty string of separators still contains no usable key material."""

    with pytest.raises(SecretsUnavailable):
        parse_secret_keys(", ,")


def test_secret_box_refuses_an_empty_parsed_key_set() -> None:
    """Direct construction cannot bypass the key configuration fail-closed rule."""

    with pytest.raises(SecretsUnavailable):
        SecretBox(OrderedDict())


def test_malformed_fingerprint_never_matches(box: SecretBox) -> None:
    """A stored digest without a live key identifier cannot validate a guess."""

    assert box.fingerprint_matches("not-a-keyed-fingerprint", "message") is False


def test_truncated_sealed_secret_is_refused(box: SecretBox) -> None:
    """A nonce without authenticated ciphertext is never passed to AES-GCM."""

    truncated = SealedSecret(
        key_id=box.active_key_id,
        ciphertext=base64.b64encode(b"x" * 12).decode(),
    )

    with pytest.raises(SecretDecryptionFailed, match="truncated"):
        box.open(truncated, aad="conn_1")


def test_production_without_configured_keys_fails_closed() -> None:
    """A production deployment must not silently run without key material."""

    with pytest.raises(SecretsUnavailable):
        build_secret_box(None, environment=AppEnvironment.PRODUCTION)


def test_development_without_configured_keys_gets_an_ephemeral_key() -> None:
    """Local development still works, with a key that dies with the process."""

    box = build_secret_box(None, environment=AppEnvironment.DEVELOPMENT)
    sealed = box.seal("dev-token", aad="conn_1")

    assert box.open(sealed, aad="conn_1") == "dev-token"


def test_configured_keys_are_used_in_every_environment() -> None:
    """An explicitly configured key is honoured regardless of environment."""

    box = build_secret_box(f"v1:{KEY_V1}", environment=AppEnvironment.PRODUCTION)
    sealed = box.seal("prod-token", aad="conn_1")

    assert sealed.key_id == "v1"
    assert box.open(sealed, aad="conn_1") == "prod-token"


def test_two_ephemeral_development_boxes_do_not_share_a_key() -> None:
    """Ephemeral keys are per-process, so restarts invalidate old ciphertext."""

    first = build_secret_box(None, environment=AppEnvironment.DEVELOPMENT)
    second = build_secret_box(None, environment=AppEnvironment.DEVELOPMENT)
    sealed = first.seal("dev-token", aad="conn_1")

    with pytest.raises(SecretDecryptionFailed):
        second.open(sealed, aad="conn_1")
