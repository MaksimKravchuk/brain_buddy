"""Stateless, fixed-endpoint provider exchange and signed-identity profiles.

Durable attempt binding, account authority, proof consumption, Apple grant
sealing and notification replay/effects belong to the coordinating service.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from email_validator import EmailNotValidError, validate_email
from joserfc import jws, jwt
from joserfc.errors import JoseError
from joserfc.jwk import ECKey, RSAKey
from pydantic import SecretStr

from app.core.config import ModernAuthSettings

Provider = Literal["google", "apple"]
ProviderErrorCode = Literal[
    "invalid_proof", "provider_unavailable", "method_unavailable"
]
RevocationTokenType = Literal["refresh_token", "access_token"]
_REFRESH_KIND: RevocationTokenType = "refresh_token"
_ACCESS_KIND: RevocationTokenType = "access_token"
_GOOGLE_ISSUER = "https://accounts.google.com"
_APPLE_ISSUER = "https://appleid.apple.com"
_ENDPOINTS: Mapping[str, tuple[str, str, str]] = {
    "google": (
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        "https://www.googleapis.com/oauth2/v3/certs",
    ),
    "apple": (
        "https://appleid.apple.com/auth/authorize",
        "https://appleid.apple.com/auth/token",
        "https://appleid.apple.com/auth/keys",
    ),
}
_APPLE_REVOKE = "https://appleid.apple.com/auth/revoke"
_DOMAIN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\Z"
)
_CLOCK_SKEW = 60
_MAX_JWT_BYTES = 16_384
_MAX_RESPONSE_BYTES = 262_144


class ProviderError(ValueError):
    """A coarse outcome with no input, assertion or upstream error details."""

    def __init__(self, code: ProviderErrorCode = "invalid_proof") -> None:
        super().__init__("Provider authentication could not be completed.")
        self.code = code


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider: Provider
    issuer: str
    subject: str = field(repr=False)
    email: str | None = field(repr=False)
    email_authoritative: bool
    is_private_email: bool
    audience: str
    issued_at: int
    namespace: str = "brainbuddy"


@dataclass(frozen=True, slots=True)
class ProviderTokens:
    identity: ProviderIdentity
    issuing_client: str
    revocation_token: SecretStr | None = field(default=None, repr=False)
    revocation_token_type: RevocationTokenType | None = None


@dataclass(frozen=True, slots=True)
class AppleNotification:
    jti: str = field(repr=False)
    event_type: str
    subject: str = field(repr=False)
    audience: str
    issued_at: int
    event_time: int
    email: str | None = field(default=None, repr=False)
    is_private_email: bool | None = None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderError()
        result[key] = value
    return result


class _UniqueJSONDecoder(json.JSONDecoder):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(object_pairs_hook=_unique_object, **kwargs)


def _text(value: object, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
    ):
        raise ProviderError()
    return value


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderError()
    return value


def _boolean(value: object, *, apple: bool) -> bool:
    if isinstance(value, bool):
        return value
    if apple and value in ("true", "false"):
        return value == "true"
    raise ProviderError()


def _email(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 320:
        raise ProviderError()
    try:
        validate_email(value, check_deliverability=False)
    except EmailNotValidError:
        raise ProviderError() from None
    return value.strip().lower()


class AuthProviderService:
    """Verify fixed provider profiles using bounded, non-retried HTTP calls."""

    def __init__(
        self,
        settings: ModernAuthSettings,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        api_prefix: str = "/api",
        notification_audience: str | None = None,
    ) -> None:
        if not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", api_prefix):
            raise ProviderError("method_unavailable")
        self._settings = settings
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else httpx.Client(timeout=10, follow_redirects=False)
        )
        self._clock = clock
        self._api_prefix = api_prefix
        self._notification_audience = (
            notification_audience
            or settings.apple_services_id
            or settings.apple_native_app_id
        )
        if notification_audience is not None and notification_audience not in {
            settings.apple_services_id,
            settings.apple_native_app_id,
        }:
            raise ProviderError("method_unavailable")
        self._jwks: dict[str, tuple[float, dict[str, RSAKey]]] = {}
        self._last_key_refresh: dict[str, float] = {}
        self._key_lock = threading.Lock()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _require(self, provider: str, *, native: bool = False) -> Provider:
        if provider == "google" and self._settings.google_available:
            return "google"
        if provider == "apple" and (
            self._settings.apple_native_available
            if native
            else self._settings.apple_web_available
        ):
            return "apple"
        raise ProviderError("method_unavailable")

    def callback_uri(self, provider: Provider) -> str:
        if provider not in _ENDPOINTS or not self._settings.api_origin:
            raise ProviderError("method_unavailable")
        return f"{self._settings.api_origin}{self._api_prefix}/auth/providers/{provider}/callback"

    def _redirect(self, provider: Provider, redirect_uri: str) -> str:
        if redirect_uri != self.callback_uri(provider):
            raise ProviderError()
        return redirect_uri

    @staticmethod
    def _verifier(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9._~-]{43,128}", value
        ):
            raise ProviderError()
        return value

    def authorization_url(
        self,
        provider: Provider,
        *,
        state: str,
        nonce: str,
        redirect_uri: str,
        pkce_verifier: str | None = None,
    ) -> str:
        selected = self._require(provider)
        query = {
            "client_id": (
                self._settings.google_client_id
                if selected == "google"
                else self._settings.apple_services_id
            ),
            "redirect_uri": self._redirect(selected, redirect_uri),
            "response_type": "code",
            "state": _text(state),
            "nonce": _text(nonce),
            "scope": "openid email" if selected == "google" else "email",
        }
        if selected == "google":
            verifier = self._verifier(pkce_verifier or "")
            query.update(
                code_challenge=base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode("ascii")).digest()
                )
                .rstrip(b"=")
                .decode("ascii"),
                code_challenge_method="S256",
            )
        else:
            if pkce_verifier is not None:
                raise ProviderError()
            query["response_mode"] = "form_post"
        return _ENDPOINTS[selected][0] + "?" + urlencode(query)

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: Mapping[str, str] | None = None,
        empty_success: bool = False,
    ) -> dict[str, Any]:
        try:
            with self._client.stream(
                method, url, data=data, timeout=10.0, follow_redirects=False
            ) as response:
                if response.status_code != 200:
                    raise ProviderError("provider_unavailable")
                if empty_success:
                    return {}
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise ProviderError("provider_unavailable")
                    body.extend(chunk)
                result = json.loads(body, cls=_UniqueJSONDecoder)
                if not isinstance(result, dict):
                    raise ProviderError("provider_unavailable")
                return result
        except httpx.HTTPError, ValueError, TypeError:
            raise ProviderError("provider_unavailable") from None

    def _key_for(self, provider: Provider, kid: str) -> RSAKey:
        with self._key_lock:
            now = self._clock()
            expires, keys = self._jwks.get(provider, (0.0, {}))
            if now < expires and kid in keys:
                return keys[kid]
            last_refresh = self._last_key_refresh.get(provider)
            if last_refresh is not None and now - last_refresh < 60:
                raise ProviderError()
            self._last_key_refresh[provider] = now
            document = self._request("GET", _ENDPOINTS[provider][2])
            values = document.get("keys")
            if not isinstance(values, list) or not 1 <= len(values) <= 32:
                raise ProviderError("provider_unavailable")
            refreshed: dict[str, RSAKey] = {}
            try:
                for item in values:
                    if (
                        not isinstance(item, dict)
                        or item.get("kty") != "RSA"
                        or item.get("use", "sig") != "sig"
                        or item.get("alg", "RS256") != "RS256"
                        or any(
                            member in item
                            for member in ("d", "p", "q", "dp", "dq", "qi", "oth")
                        )
                    ):
                        raise ProviderError("provider_unavailable")
                    key_id = _text(item.get("kid"), maximum=128)
                    if key_id in refreshed:
                        raise ProviderError("provider_unavailable")
                    refreshed[key_id] = RSAKey.import_key(item)
            except JoseError, ValueError, TypeError, KeyError:
                raise ProviderError("provider_unavailable") from None
            self._jwks[provider] = (now + 3600, refreshed)
            if kid not in refreshed:
                raise ProviderError()
            return refreshed[kid]

    def _signed_claims(self, token: object, provider: Provider) -> dict[str, Any]:
        try:
            encoded = _text(token, maximum=_MAX_JWT_BYTES).encode("ascii")
            header = jws.extract_compact(encoded).protected
            if header.get("alg") != "RS256" or any(
                name in header for name in ("jku", "x5u", "jwk", "x5c", "crit", "b64")
            ):
                raise ProviderError()
            kid = _text(header.get("kid"), maximum=128)
            decoded = jwt.decode(
                encoded,
                self._key_for(provider, kid),
                algorithms=["RS256"],
                decoder_cls=_UniqueJSONDecoder,
            )
            if not isinstance(decoded.claims, dict):
                raise ProviderError()
            return decoded.claims
        except ProviderError:
            raise
        except JoseError, ValueError, TypeError, KeyError:
            raise ProviderError() from None

    def _times(self, values: Mapping[str, Any], *, require_exp: bool) -> int:
        now = self._clock()
        issued_at = _integer(values.get("iat"))
        if issued_at > now + _CLOCK_SKEW:
            raise ProviderError()
        if require_exp or "exp" in values:
            expires = _integer(values.get("exp"))
            if expires <= now - _CLOCK_SKEW or expires <= issued_at:
                raise ProviderError()
        if "nbf" in values and _integer(values["nbf"]) > now + _CLOCK_SKEW:
            raise ProviderError()
        return issued_at

    @staticmethod
    def _audience(values: Mapping[str, Any], expected: str, *, google: bool) -> None:
        audience = values.get("aud")
        if google and isinstance(audience, list):
            if (
                not 1 <= len(audience) <= 5
                or any(not isinstance(value, str) for value in audience)
                or len(set(audience)) != len(audience)
                or expected not in audience
                or (len(audience) > 1 and values.get("azp") != expected)
            ):
                raise ProviderError()
        elif audience != expected:
            raise ProviderError()
        if "azp" in values and values["azp"] != expected:
            raise ProviderError()

    def _identity(
        self, token: object, provider: Provider, audience: str, nonce: str
    ) -> ProviderIdentity:
        values = self._signed_claims(token, provider)
        issuer = values.get("iss")
        valid_issuers = (
            {_GOOGLE_ISSUER, "accounts.google.com"}
            if provider == "google"
            else {_APPLE_ISSUER}
        )
        if not isinstance(issuer, str) or issuer not in valid_issuers:
            raise ProviderError()
        self._audience(values, audience, google=provider == "google")
        issued_at = self._times(values, require_exp=True)
        if not hmac.compare_digest(_text(values.get("nonce")), _text(nonce)):
            raise ProviderError()
        subject = _text(values.get("sub"), maximum=255)
        email = _email(values.get("email"))
        verified = (
            _boolean(values["email_verified"], apple=provider == "apple")
            if "email_verified" in values
            else False
        )
        private_email = (
            _boolean(values["is_private_email"], apple=True)
            if provider == "apple" and "is_private_email" in values
            else False
        )
        hd = values.get("hd")
        workspace = (
            isinstance(hd, str) and len(hd) <= 253 and _DOMAIN.fullmatch(hd) is not None
        )
        authoritative = bool(
            email
            and verified
            and (
                provider == "apple"
                or email.rsplit("@", 1)[-1] in {"gmail.com", "googlemail.com"}
                or workspace
            )
        )
        return ProviderIdentity(
            provider,
            _GOOGLE_ISSUER if provider == "google" else _APPLE_ISSUER,
            subject,
            email,
            authoritative,
            private_email,
            audience,
            issued_at,
        )

    def exchange_google(
        self, code: str, *, redirect_uri: str, pkce_verifier: str, nonce: str
    ) -> ProviderTokens:
        self._require("google")
        document = self._request(
            "POST",
            _ENDPOINTS["google"][1],
            data={
                "grant_type": "authorization_code",
                "client_id": self._settings.google_client_id,
                "client_secret": self._settings.google_client_secret.get_secret_value(),
                "code": _text(code, maximum=4096),
                "redirect_uri": self._redirect("google", redirect_uri),
                "code_verifier": self._verifier(pkce_verifier),
            },
        )
        identity = self._identity(
            document.get("id_token"), "google", self._settings.google_client_id, nonce
        )
        return ProviderTokens(identity, self._settings.google_client_id)

    def _apple_client_secret(self, issuing_client: str) -> str:
        if (
            issuing_client
            not in {
                self._settings.apple_services_id,
                self._settings.apple_native_app_id,
            }
            or not issuing_client
        ):
            raise ProviderError("method_unavailable")
        try:
            now = int(self._clock())
            key = ECKey.import_key(self._settings.apple_private_key.get_secret_value())
            return jwt.encode(
                {"alg": "ES256", "kid": self._settings.apple_key_id},
                {
                    "iss": self._settings.apple_team_id,
                    "sub": issuing_client,
                    "aud": _APPLE_ISSUER,
                    "iat": now,
                    "exp": now + 300,
                },
                key,
                algorithms=["ES256"],
            )
        except JoseError, ValueError, TypeError:
            raise ProviderError("method_unavailable") from None

    def exchange_apple(
        self,
        code: str,
        *,
        nonce: str,
        redirect_uri: str | None = None,
        native_identity_token: str | None = None,
    ) -> ProviderTokens:
        native = native_identity_token is not None
        self._require("apple", native=native)
        client_id = (
            self._settings.apple_native_app_id
            if native
            else self._settings.apple_services_id
        )
        original = (
            self._identity(native_identity_token, "apple", client_id, nonce)
            if native_identity_token is not None
            else None
        )
        form = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": self._apple_client_secret(client_id),
            "code": _text(code, maximum=4096),
        }
        if not native:
            form["redirect_uri"] = self._redirect("apple", redirect_uri or "")
        elif redirect_uri is not None:
            raise ProviderError()
        document = self._request("POST", _ENDPOINTS["apple"][1], data=form)
        identity = self._identity(document.get("id_token"), "apple", client_id, nonce)
        if original is not None and original.subject != identity.subject:
            raise ProviderError()
        grant_type: RevocationTokenType | None = None
        grant: SecretStr | None = None
        for kind in (_REFRESH_KIND, _ACCESS_KIND):
            if kind in document:
                grant_type = kind
                grant = SecretStr(_text(document[kind], maximum=16_384))
                break
        if grant is None:
            raise ProviderError("provider_unavailable")
        return ProviderTokens(identity, client_id, grant, grant_type)

    def revoke_apple(
        self,
        token: str | SecretStr,
        issuing_client: str,
        *,
        token_type: RevocationTokenType = _REFRESH_KIND,
    ) -> None:
        native = issuing_client == self._settings.apple_native_app_id
        self._require("apple", native=native)
        if token_type not in {"refresh_token", "access_token"}:
            raise ProviderError()
        raw_token = token.get_secret_value() if isinstance(token, SecretStr) else token
        self._request(
            "POST",
            _APPLE_REVOKE,
            data={
                "client_id": issuing_client,
                "client_secret": self._apple_client_secret(issuing_client),
                "token": _text(raw_token, maximum=16_384),
                "token_type_hint": token_type,
            },
            empty_success=True,
        )

    def verify_notification(self, signed_payload: str) -> AppleNotification:
        self._require(
            "apple",
            native=self._notification_audience == self._settings.apple_native_app_id,
        )
        values = self._signed_claims(signed_payload, "apple")
        if values.get("iss") != _APPLE_ISSUER:
            raise ProviderError()
        self._audience(values, self._notification_audience, google=False)
        issued_at = self._times(values, require_exp=False)
        if issued_at < self._clock() - 7 * 86400:
            raise ProviderError()
        event = values.get("events")
        try:
            if not isinstance(event, str):
                raise ProviderError()
            event = json.loads(event, cls=_UniqueJSONDecoder)
            if not isinstance(event, dict) or event.get("type") not in {
                "account-deleted",
                "consent-revoked",
                "email-disabled",
                "email-enabled",
            }:
                raise ProviderError()
            event_time = _integer(event.get("event_time"))
            if (
                event_time < self._clock() - 7 * 86400
                or event_time > issued_at + _CLOCK_SKEW
                or event_time > self._clock() + _CLOCK_SKEW
            ):
                raise ProviderError()
            return AppleNotification(
                _text(values.get("jti"), maximum=256),
                event["type"],
                _text(event.get("sub"), maximum=255),
                self._notification_audience,
                issued_at,
                event_time,
                _email(event.get("email")),
                (
                    _boolean(event["is_private_email"], apple=True)
                    if "is_private_email" in event
                    else None
                ),
            )
        except ValueError, TypeError, KeyError:
            raise ProviderError() from None
