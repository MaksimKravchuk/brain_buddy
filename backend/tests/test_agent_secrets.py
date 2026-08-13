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
    AAD_PURPOSE_INBOUND_SIGNING,
    AAD_PURPOSE_OUTBOUND_CREDENTIAL,
    SealedSecret,
    SecretBox,
    SecretDecryptionFailed,
    SecretsUnavailable,
    build_secret_box,
    fingerprint_key_id,
    parse_secret_keys,
    secret_aad,
)

KEY_V1 = base64.b64encode(b"\x01" * 32).decode()
KEY_V2 = base64.b64encode(b"\x02" * 32).decode()
MAX_KEY_ID_CHARS = 64


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
            AAD_PURPOSE_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_1"
        )
        return aad, box.seal("hermes-token-value", aad=aad).ciphertext

    def test_the_aad_names_the_purpose_owner_and_connection(self) -> None:
        """Each component is present, so none of them can be swapped silently."""

        aad = secret_aad(
            AAD_PURPOSE_OUTBOUND_CREDENTIAL, owner_id="user_a", connection_id="conn_1"
        )

        assert AAD_PURPOSE_OUTBOUND_CREDENTIAL in aad
        assert "user_a" in aad
        assert "conn_1" in aad

    def test_a_row_cannot_be_transplanted_to_another_owner(
        self, box: SecretBox
    ) -> None:
        """Same connection ID, different owner: the seal no longer authenticates."""

        sealed = box.seal(
            "hermes-token-value",
            aad=secret_aad(
                AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                owner_id="user_a",
                connection_id="conn_1",
            ),
        )

        with pytest.raises(SecretDecryptionFailed):
            box.open(
                sealed,
                aad=secret_aad(
                    AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                    owner_id="user_b",
                    connection_id="conn_1",
                ),
            )

    def test_a_row_cannot_be_transplanted_to_another_connection(
        self, box: SecretBox
    ) -> None:
        """Same owner, different connection: still refused."""

        sealed = box.seal(
            "hermes-token-value",
            aad=secret_aad(
                AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                owner_id="user_a",
                connection_id="conn_1",
            ),
        )

        with pytest.raises(SecretDecryptionFailed):
            box.open(
                sealed,
                aad=secret_aad(
                    AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                    owner_id="user_a",
                    connection_id="conn_2",
                ),
            )

    def test_purposes_are_domain_separated(self, box: SecretBox) -> None:
        """An outbound credential can never be opened as a signing secret."""

        sealed = box.seal(
            "hermes-token-value",
            aad=secret_aad(
                AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                owner_id="user_a",
                connection_id="conn_1",
            ),
        )

        with pytest.raises(SecretDecryptionFailed):
            box.open(
                sealed,
                aad=secret_aad(
                    AAD_PURPOSE_INBOUND_SIGNING,
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
                    AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                    owner_id="user_a",
                    connection_id="conn_1",
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


def test_fingerprints_anchor_to_the_oldest_key_not_the_active_one() -> None:
    """Sealing follows the newest key; comparison identity follows the oldest.

    A fingerprint is written once and looked up later, possibly by an instance
    that has not been given the new key yet. Anchoring it to the newest key
    would make every rotation invisible to the rest of the fleet.
    """

    rotated = SecretBox(parse_secret_keys(f"v2:{KEY_V2},v1:{KEY_V1}"))

    assert rotated.active_key_id == "v2"
    assert rotated.anchor_key_id == "v1"
    assert rotated.key_ids == ("v2", "v1")
    assert rotated.fingerprint("message").startswith("v1:")


def test_every_generation_of_the_ring_agrees_on_the_anchored_fingerprint() -> None:
    """The overlap invariant: a shared oldest key means a shared fingerprint."""

    stale = SecretBox(parse_secret_keys(f"v1:{KEY_V1}"))
    rotated = SecretBox(parse_secret_keys(f"v2:{KEY_V2},v1:{KEY_V1}"))

    assert rotated.fingerprint("message") == stale.fingerprint("message")
    assert stale.fingerprint_matches(rotated.fingerprint("message"), "message")
    assert rotated.fingerprint_matches(stale.fingerprint("message"), "message")


def test_lookup_still_offers_a_candidate_for_every_configured_key() -> None:
    """A record written under any live key stays findable after rotation."""

    rotated = SecretBox(parse_secret_keys(f"v2:{KEY_V2},v1:{KEY_V1}"))

    candidates = rotated.fingerprint_candidates("message")

    assert [candidate.partition(":")[0] for candidate in candidates] == ["v2", "v1"]
    assert rotated.fingerprint("message") in candidates


def test_a_retired_key_is_no_longer_a_candidate_or_a_match() -> None:
    """Dropping a key makes its records unfindable — the fail-closed trigger."""

    rotated = SecretBox(parse_secret_keys(f"v2:{KEY_V2},v1:{KEY_V1}"))
    written_under_v1 = rotated.fingerprint("message")

    retired = SecretBox(parse_secret_keys(f"v2:{KEY_V2}"))

    assert written_under_v1 not in retired.fingerprint_candidates("message")
    assert retired.fingerprint_matches(written_under_v1, "message") is False


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


@pytest.mark.parametrize(
    "key_id",
    [
        "relay key",
        "relay,key",
        "relay:key",
        "relay\tkey",
        "relay\nkey",
        "clé",
        ".relay",
        "relay-",
        "a" * (MAX_KEY_ID_CHARS + 1),
    ],
)
def test_noncanonical_configured_key_ids_are_refused(key_id: str) -> None:
    """Configuration labels have one bounded ASCII spelling, never a normalised one."""

    with pytest.raises(SecretsUnavailable, match="key id") as refused:
        parse_secret_keys(f"{key_id}:{KEY_V1}")

    assert KEY_V1 not in str(refused.value)


@pytest.mark.parametrize(
    "key_id", ["v1", "kid-0", "relay.prod_v2-2026", "a" * MAX_KEY_ID_CHARS]
)
def test_canonical_configured_key_ids_are_preserved(key_id: str) -> None:
    """Existing labels and the full conservative grammar round-trip unchanged."""

    assert list(parse_secret_keys(f"{key_id}:{KEY_V1}")) == [key_id]


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


@pytest.mark.parametrize("key_id", ["relay key", "relay,key", "relay:key", "clé"])
def test_secret_box_construction_cannot_bypass_key_id_validation(key_id: str) -> None:
    """Programmatic construction enforces the same labels as environment parsing."""

    material = b"\x01" * 32
    with pytest.raises(SecretsUnavailable, match="key id") as refused:
        SecretBox(OrderedDict({key_id: material}))

    assert repr(material) not in str(refused.value)


def test_malformed_fingerprint_never_matches(box: SecretBox) -> None:
    """A stored digest without a live key identifier cannot validate a guess."""

    assert box.fingerprint_matches("not-a-keyed-fingerprint", "message") is False


def test_fingerprints_match_only_the_original_message_across_live_keys() -> None:
    """Rotated key rings find old fingerprints without accepting a changed message."""

    old = SecretBox(parse_secret_keys(f"v1:{KEY_V1}"))
    old_fingerprint = old.fingerprint("same request")
    rotated = SecretBox(parse_secret_keys(f"v2:{KEY_V2},v1:{KEY_V1}"))

    candidates = rotated.fingerprint_candidates("same request")
    assert candidates[0].startswith("v2:")
    assert candidates[1] == old_fingerprint
    assert rotated.fingerprint_matches(old_fingerprint, "same request") is True
    assert rotated.fingerprint_matches(old_fingerprint, "changed request") is False


def test_a_written_fingerprint_reads_back_as_its_key_id(box: SecretBox) -> None:
    """The parser and the writer are one format, checked against each other."""

    written = box.fingerprint("message")

    assert fingerprint_key_id(written) == "v1"
    assert written.partition(":")[2] == box.fingerprint("message").partition(":")[2]


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "v1",
        "v1:",
        ":" + "a" * 64,
        "v1:" + "a" * 63,
        "v1:" + "a" * 65,
        "v1:" + "g" * 64,
        # hexdigest() is lowercase, so an upper-case digest was never ours.
        "v1:" + "A" * 64,
        "v1:v2:" + "a" * 64,
        "v1:" + "a" * 64 + ":v2",
        "v1: " + "a" * 63,
        "relay key:" + "a" * 64,
        "relay,key:" + "a" * 64,
        "relay\tkey:" + "a" * 64,
        "relay\nkey:" + "a" * 64,
        "clé:" + "a" * 64,
        ".relay:" + "a" * 64,
        "relay-:" + "a" * 64,
        "a" * (MAX_KEY_ID_CHARS + 1) + ":" + "a" * 64,
    ],
)
def test_a_value_that_is_not_a_fingerprint_has_no_key_id(stored: str) -> None:
    """Anything but the exact written shape reads as unparseable, not as a key id.

    Splitting on the first colon would happily call ``v1`` or ``v1:`` the key id
    ``v1``, which is how an unreadable record gets mistaken for a live one.
    """

    assert fingerprint_key_id(stored) is None


@pytest.mark.parametrize("stored", ["v1", "v1:", "v1:" + "a" * 63, "v1:" + "A" * 64])
def test_a_malformed_fingerprint_is_refused_even_under_a_live_key(
    box: SecretBox, stored: str
) -> None:
    """A live key id is not enough: the digest half has to be readable too."""

    assert box.fingerprint_matches(stored, "message") is False


def test_truncated_sealed_secret_is_refused(box: SecretBox) -> None:
    """A nonce without authenticated ciphertext is never passed to AES-GCM."""

    truncated = SealedSecret(
        key_id=box.active_key_id,
        ciphertext=base64.b64encode(b"x" * 12).decode(),
    )

    with pytest.raises(SecretDecryptionFailed, match="truncated"):
        box.open(truncated, aad="conn_1")


def test_non_base64_sealed_secret_is_refused(box: SecretBox) -> None:
    """Malformed persisted ciphertext fails closed before decryption."""

    malformed = SealedSecret(key_id=box.active_key_id, ciphertext="%%%")

    with pytest.raises(SecretDecryptionFailed, match="valid base64"):
        box.open(malformed, aad="conn_1")


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
