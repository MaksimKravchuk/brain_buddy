"""Versioned auth-only master keys with purpose-separated HMAC and AEAD.

No clock, storage, provider I/O or fallback keys live here. Retain prior keys
until their encrypted payloads and abuse-budget windows have been cleaned up.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

if TYPE_CHECKING:
    from app.core.config import ModernAuthSettings

_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_ERROR = "Invalid authentication secret configuration or payload."
_VERSION = "bb-auth.v1"
_HKDF_SALT = b"brain-buddy:modern-auth:v1"


class AuthSecretError(ValueError):
    """A safe configuration/payload error that never includes input material."""

    def __init__(self) -> None:
        super().__init__(_ERROR)


@dataclass(frozen=True, slots=True)
class SecretContext:
    """Immutable purpose and authority dimensions authenticated with a payload."""

    kind: str
    attempt_id: str = ""
    binding_id: str = ""
    owner_id: str = ""
    client_id: str = ""
    generation: int = 0

    def __post_init__(self) -> None:
        if (
            not self.kind
            or any(
                not isinstance(value, str)
                for value in (
                    self.kind,
                    self.attempt_id,
                    self.binding_id,
                    self.owner_id,
                    self.client_id,
                )
            )
            or not isinstance(self.generation, int)
            or isinstance(self.generation, bool)
            or self.generation < 0
        ):
            raise AuthSecretError()


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
    except TypeError, ValueError:
        raise AuthSecretError() from None


class AuthSecretBox:
    """Use the current key for new material and explicit old IDs for reads."""

    def __init__(self, keys: Mapping[str, bytes], current_key_id: str) -> None:
        if (
            not isinstance(keys, Mapping)
            or not keys
            or not isinstance(current_key_id, str)
            or current_key_id not in keys
        ):
            raise AuthSecretError()
        for key_id, master in keys.items():
            if (
                not isinstance(key_id, str)
                or not _KEY_ID.fullmatch(key_id)
                or not isinstance(master, bytes)
                or len(master) != 32
            ):
                raise AuthSecretError()
        self._current_key_id = current_key_id
        self._keys = MappingProxyType(
            {
                key_id: MappingProxyType(
                    {
                        purpose: HKDF(
                            algorithm=hashes.SHA256(),
                            length=32,
                            salt=_HKDF_SALT,
                            info=f"brain-buddy:modern-auth:v1:{purpose}".encode(),
                        ).derive(master)
                        for purpose in ("hmac-code", "hmac-budget", "aead")
                    }
                )
                for key_id, master in keys.items()
            }
        )

    def __repr__(self) -> str:
        return "AuthSecretBox(<protected>)"

    @classmethod
    def from_settings(cls, settings: ModernAuthSettings) -> AuthSecretBox:
        if not settings.crypto_ready:
            raise AuthSecretError()
        try:
            keys = {
                key_id: base64.b64decode(secret.get_secret_value(), validate=True)
                for key_id, secret in settings.keyring.items()
            }
        except ValueError, binascii.Error:
            raise AuthSecretError() from None
        return cls(keys, settings.current_key_id)

    @property
    def current_key_id(self) -> str:
        return self._current_key_id

    @property
    def key_ids(self) -> tuple[str, ...]:
        return (
            self.current_key_id,
            *(key_id for key_id in self._keys if key_id != self.current_key_id),
        )

    def _key(self, key_id: str, purpose: str) -> bytes:
        try:
            return self._keys[key_id][purpose]
        except KeyError, TypeError:
            raise AuthSecretError() from None

    @staticmethod
    def _aad(context: SecretContext, key_id: str) -> bytes:
        if not isinstance(context, SecretContext):
            raise AuthSecretError()
        return _canonical({"version": _VERSION, "key_id": key_id, **asdict(context)})

    def seal(self, plaintext: bytes, context: SecretContext) -> str:
        if not isinstance(plaintext, bytes):
            raise AuthSecretError()
        key_id = self.current_key_id
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key(key_id, "aead")).encrypt(
            nonce, plaintext, self._aad(context, key_id)
        )
        return f"{_VERSION}.{key_id}.{base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii')}"

    def open(self, envelope: str, context: SecretContext) -> bytes:
        try:
            namespace, version, key_id, encoded = envelope.split(".")
            if f"{namespace}.{version}" != _VERSION:
                raise AuthSecretError()
            blob = base64.b64decode(encoded, altchars=b"-_", validate=True)
            if (
                len(blob) < 28
                or base64.urlsafe_b64encode(blob).decode("ascii") != encoded
            ):
                raise AuthSecretError()
            return AESGCM(self._key(key_id, "aead")).decrypt(
                blob[:12], blob[12:], self._aad(context, key_id)
            )
        except AttributeError, TypeError, ValueError, binascii.Error, InvalidTag:
            raise AuthSecretError() from None

    def code_digest(
        self, code: str, context: SecretContext, *, key_id: str | None = None
    ) -> str:
        if not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None:
            raise AuthSecretError()
        selected = self.current_key_id if key_id is None else key_id
        return hmac.new(
            self._key(selected, "hmac-code"),
            self._aad(context, selected) + b"\0" + code.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def verify_code(
        self, code: str, digest: str, context: SecretContext, *, key_id: str
    ) -> bool:
        try:
            candidate = self.code_digest(code, context, key_id=key_id)
            return (
                isinstance(digest, str)
                and re.fullmatch(r"[a-f0-9]{64}", digest) is not None
                and hmac.compare_digest(candidate, digest)
            )
        except AuthSecretError:
            return False

    def budget_fingerprints(self, value: str, scope: str) -> Mapping[str, str]:
        if not isinstance(value, str) or not isinstance(scope, str) or not scope:
            raise AuthSecretError()
        message = _canonical({"scope": scope, "value": value})
        return MappingProxyType(
            {
                key_id: hmac.new(
                    self._key(key_id, "hmac-budget"), message, hashlib.sha256
                ).hexdigest()
                for key_id in self.key_ids
            }
        )

    @staticmethod
    def grant_digest(value: str) -> str:
        """SHA-256 is appropriate only for unpredictable high-entropy grants."""

        if not isinstance(value, str) or not value:
            raise AuthSecretError()
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
