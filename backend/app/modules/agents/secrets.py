"""Authenticated encryption for external-agent connection credentials.

A connector secret is write-only after save (FR-003): it is sealed with AES-GCM
under a key that lives outside the data directory, and the sealed blob is bound
to the owner, the connection, *and* the purpose it was sealed for, so a copied
database row cannot be replayed against a different owner, a different
connection, or a different role in the protocol.

Key material is supplied as ``<key_id>:<base64 32-byte key>`` entries, newest
first. The first entry seals new secrets; every entry can open an existing one,
which is what makes rotation a configuration change rather than a migration.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from collections import OrderedDict

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import AppEnvironment
from app.schemas.common import StorageBaseModel

_KEY_BYTES = 32
_NONCE_BYTES = 12
_EPHEMERAL_KEY_ID = "ephemeral"

AAD_OUTBOUND_CREDENTIAL = "outbound-credential"
"""The credential BrainBuddy sends *to* the user's agent."""

AAD_INBOUND_SIGNING_SECRET = "inbound-signing-secret"
"""The secret the user's agent signs its reports *with*."""

AAD_SIGNING_SECRET_RECEIPT = "signing-secret-receipt"
"""A one-time replacement secret held only for lost-response recovery."""

_AAD_SCHEME = "brain-buddy/agent-relay"


def secret_aad(purpose: str, *, owner_id: str, connection_id: str) -> str:
    """The authenticated context one relay secret is sealed under.

    Every component matters. ``purpose`` keeps an outbound credential from ever
    being opened as an inbound signing secret; ``owner_id`` and
    ``connection_id`` together mean a row lifted out of the database
    authenticates only where it was written. The encoding is canonical JSON so
    the exact bytes cannot drift as fields are added.
    """

    return json.dumps(
        {
            "v": 1,
            "scheme": _AAD_SCHEME,
            "purpose": purpose,
            "owner_id": owner_id,
            "connection_id": connection_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class SecretsUnavailable(RuntimeError):
    """Key material is missing or malformed, so no credential may be stored."""


class SecretDecryptionFailed(RuntimeError):
    """A sealed credential could not be opened and must not be used."""


class SealedSecret(StorageBaseModel):
    """A credential at rest: base64 ``nonce || ciphertext || tag`` plus its key."""

    key_id: str
    ciphertext: str


def parse_secret_keys(raw: str | None) -> OrderedDict[str, bytes]:
    """Parse ``id:base64key`` entries, newest first, or refuse the whole set."""

    if raw is None or not raw.strip():
        raise SecretsUnavailable(
            "No external-agent relay key material is configured."
        )

    keys: OrderedDict[str, bytes] = OrderedDict()
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        key_id, separator, encoded = candidate.partition(":")
        key_id = key_id.strip()
        encoded = encoded.strip()
        if not separator or not key_id or not encoded:
            raise SecretsUnavailable(
                "External-agent relay keys must be '<key_id>:<base64 key>' entries."
            )
        if key_id in keys:
            raise SecretsUnavailable(
                f"External-agent relay key id '{key_id}' is declared more than once."
            )
        try:
            material = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SecretsUnavailable(
                f"External-agent relay key '{key_id}' is not valid base64."
            ) from exc
        if len(material) != _KEY_BYTES:
            raise SecretsUnavailable(
                f"External-agent relay key '{key_id}' must decode to "
                f"{_KEY_BYTES} bytes."
            )
        keys[key_id] = material

    if not keys:
        raise SecretsUnavailable(
            "No external-agent relay key material is configured."
        )
    return keys


class SecretBox:
    """Seals and opens connector credentials under a rotating key set."""

    def __init__(self, keys: OrderedDict[str, bytes]) -> None:
        if not keys:
            raise SecretsUnavailable(
                "No external-agent relay key material is configured."
            )
        self._keys = keys
        self._active_key_id = next(iter(keys))

    def __repr__(self) -> str:
        # Never render key material: this object shows up in tracebacks.
        return f"SecretBox(key_ids={list(self._keys)!r})"

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    def seal(self, plaintext: str, *, aad: str) -> SealedSecret:
        """Encrypt ``plaintext``, authenticating ``aad`` alongside it."""

        nonce = os.urandom(_NONCE_BYTES)
        cipher = AESGCM(self._keys[self._active_key_id])
        blob = cipher.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        return SealedSecret(
            key_id=self._active_key_id,
            ciphertext=base64.b64encode(nonce + blob).decode("ascii"),
        )

    def _mac(self, key_id: str, message: str) -> str:
        return hmac.new(
            self._keys[key_id], message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def fingerprint(self, message: str) -> str:
        """A keyed, key-id-tagged fingerprint of ``message``.

        Used where a value has to be *compared* but must never be stored or
        recoverable — request equivalence for idempotency, and the lookup hash
        of an idempotency key itself. A plain digest would not do: these inputs
        are low-entropy enough (a short reply, a bearer token, a UUID) that an
        attacker holding the database could confirm a guess by hashing it. With
        the key ring's material mixed in, a stolen row proves nothing without a
        key that never lives in the data directory.
        """

        return f"{self._active_key_id}:{self._mac(self._active_key_id, message)}"

    def fingerprint_candidates(self, message: str) -> list[str]:
        """Every fingerprint ``message`` could be stored under, active first.

        Lookup has to survive a key rotation: a record written yesterday under
        the previous key must still be found today, for as long as that key
        remains configured. Once it is retired the record is simply unfindable,
        which fails closed — a retry then conflicts rather than replaying.
        """

        return [f"{key_id}:{self._mac(key_id, message)}" for key_id in self._keys]

    def fingerprint_matches(self, stored: str, message: str) -> bool:
        """Whether ``stored`` is this message's fingerprint under any live key."""

        key_id, separator, digest = stored.partition(":")
        if not separator or key_id not in self._keys:
            return False
        return hmac.compare_digest(digest, self._mac(key_id, message))

    def open(self, sealed: SealedSecret, *, aad: str) -> str:
        """Decrypt a sealed credential, or refuse if anything fails to verify."""

        key = self._keys.get(sealed.key_id)
        if key is None:
            raise SecretDecryptionFailed(
                f"No key material for external-agent key id '{sealed.key_id}'."
            )
        try:
            raw = base64.b64decode(sealed.ciphertext, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SecretDecryptionFailed("Sealed credential is not valid base64.") from exc
        if len(raw) <= _NONCE_BYTES:
            raise SecretDecryptionFailed("Sealed credential is truncated.")
        try:
            plaintext = AESGCM(key).decrypt(
                raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], aad.encode("utf-8")
            )
        except InvalidTag as exc:
            raise SecretDecryptionFailed(
                "Sealed credential failed authentication."
            ) from exc
        return plaintext.decode("utf-8")


def build_secret_box(raw_keys: str | None, *, environment: AppEnvironment) -> SecretBox:
    """Build the process's secret box, failing closed in production.

    Development and test deployments fall back to a per-process ephemeral key so
    the feature is usable locally without ceremony. That key dies with the
    process, which is the honest behaviour: restart and previously saved
    credentials are unreadable and must be re-entered.
    """

    if raw_keys is not None and raw_keys.strip():
        return SecretBox(parse_secret_keys(raw_keys))
    if environment is AppEnvironment.PRODUCTION:
        raise SecretsUnavailable(
            "BRAIN_BUDDY_AGENT_RELAY_KEYS must be set in production before "
            "external-agent connections can store credentials."
        )
    return SecretBox(OrderedDict({_EPHEMERAL_KEY_ID: os.urandom(_KEY_BYTES)}))


__all__ = [
    "AAD_INBOUND_SIGNING_SECRET",
    "AAD_OUTBOUND_CREDENTIAL",
    "AAD_SIGNING_SECRET_RECEIPT",
    "SealedSecret",
    "SecretBox",
    "SecretDecryptionFailed",
    "SecretsUnavailable",
    "build_secret_box",
    "parse_secret_keys",
    "secret_aad",
]
