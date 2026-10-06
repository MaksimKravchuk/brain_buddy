"""Client-bound proofs over the existing transactional Identity authority."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import IO, Any, Literal, Protocol, cast
from urllib.parse import urlencode

from pydantic import SecretStr

from app.core.config import ModernAuthSettings
from app.exceptions import ConflictError, ValidationFailure
from app.repositories.auth_metadata import (
    AuthMetadataRepository,
    erase_settled_apple_unlinks,
)
from app.schemas.auth import MeResponse, User
from app.schemas.modern_auth import (
    AccountActionRequest,
    AccountMethodsResponse,
    AccountPasswordRequest,
    AppleNativeCompleteRequest,
    AuthCompletion,
    ChallengeResponse,
    ConnectedMethod,
    EmailRequest,
    EmailResendRequest,
    EmailVerifyRequest,
    ExistingAccountRequiredResult,
    LinkedResult,
    MethodsResponse,
    PasswordConfirmRequest,
    ProviderCompleteRequest,
    ProviderStartRequest,
    ProviderStartResponse,
    ReauthenticatedResult,
    ResetReadyResult,
    ResetRequest,
    SignedInResult,
    UnlinkResponse,
    VerifiedEmailResult,
    VerifyMailboxResult,
)
from app.services.account_service import AccountService
from app.services.auth_apple_lifecycle import AuthAppleLifecycleError
from app.services.auth_mail_service import (
    AuthMailError,
    AuthMailRateLimitError,
    AuthMailService,
)
from app.services.auth_provider_service import (
    AuthProviderService,
    ProviderError,
    ProviderIdentity,
    ProviderTokens,
)
from app.services.auth_secret_box import AuthSecretBox, AuthSecretError, SecretContext
from app.services.auth_service import AuthService
from app.utils.time import from_isoformat, utcnow


class AppleLifecycle(Protocol):
    def record_grant(
        self, connection: sqlite3.Connection, binding_id: str, tokens: ProviderTokens
    ) -> None: ...
    def schedule_cleanup(
        self, connection: sqlite3.Connection, binding_id: str, reason: str
    ) -> None: ...
    def ensure_replaceable(
        self, connection: sqlite3.Connection, binding_id: str
    ) -> None: ...
    def dispatch_one(self) -> bool: ...
    def process_notification(self, payload: str) -> None: ...


class ModernAuthError(ValueError):
    """Only coarse, non-enumerating authority errors cross the service boundary."""

    def __init__(self, code: str = "invalid_proof", status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__("Authentication could not be completed.")


@dataclass(frozen=True, slots=True)
class AuthResult:
    payload: AuthCompletion
    raw_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ProviderStartResult:
    payload: ProviderStartResponse
    binder: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ProviderCallbackResult:
    url: str = field(repr=False)


def client_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


class ModernAuthService:
    """Never trust account snapshots or consume a proof outside its final change."""

    def __init__(
        self,
        *,
        auth_service: AuthService,
        account_service: AccountService,
        settings: ModernAuthSettings,
        secret_box: AuthSecretBox | None,
        provider_service: AuthProviderService,
        mail_service: AuthMailService | None,
        clock: Callable[[], datetime] = utcnow,
        apple_lifecycle: AppleLifecycle | None = None,
    ) -> None:
        self.auth = auth_service
        self.account = account_service
        self.settings = settings
        self.box = secret_box
        self.provider = provider_service
        self.mail = mail_service
        self.store = auth_service.user_repo.store
        self.clock = clock
        self.apple = apple_lifecycle

    @staticmethod
    def _not_found() -> ModernAuthError:
        return ModernAuthError("owner_mismatch", 404)

    def methods(self, client: str) -> MethodsResponse:
        return MethodsResponse(
            google=self.settings.google_available,
            apple=(
                self.settings.apple_web_available
                if client == "web"
                else self.settings.apple_native_available
            ),
            email=self.settings.email_available,
            web_account_origin=(
                self.settings.public_origin
                if self.settings.crypto_ready
                and self.settings.api_origin
                and self.settings.public_origin
                else None
            ),
        )

    def _mail(self) -> AuthMailService:
        if self.mail is None or not self.settings.email_available:
            raise ModernAuthError("method_unavailable", 503)
        return self.mail

    @staticmethod
    def _mail_failure(error: AuthMailError) -> ModernAuthError:
        if isinstance(error, AuthMailRateLimitError):
            return ModernAuthError("rate_limited", 429)
        return ModernAuthError("method_unavailable", 503)

    def _challenge_response(self, row: sqlite3.Row) -> ChallengeResponse:
        return ChallengeResponse(
            challenge_id=row["id"],
            expires_at=from_isoformat(row["expires_at"]),
            resend_at=from_isoformat(row["resend_at"]),
        )

    def _challenge(
        self,
        connection: sqlite3.Connection,
        identifier: str,
        verifier: str,
        raw_token: str | None,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM auth_challenges WHERE id=?", (identifier,)
        ).fetchone()
        if row is None or not hmac.compare_digest(
            row["client_challenge"], client_challenge(verifier)
        ):
            raise self._not_found()
        if row["purpose"] in {"verify_email", "change_email", "reauth"}:
            user = self.auth.get_user_for_token(raw_token)
            token_hash = self.auth.hash_session_token(raw_token) if raw_token else None
            if (
                user is None
                or user.id != row["user_id"]
                or token_hash != row["session_hash"]
            ):
                raise self._not_found()
        if (
            from_isoformat(row["expires_at"]) <= self.clock()
            or row["status"] == "consumed"
        ):
            raise ModernAuthError()
        return cast(sqlite3.Row, row)

    def request_email(
        self,
        payload: EmailRequest,
        *,
        network: str,
        raw_token: str | None = None,
    ) -> ChallengeResponse:
        mail = self._mail()
        if payload.purpose == "provider_mailbox":
            raise ModernAuthError()
        address = self.auth.user_repo.normalize_email(str(payload.email))
        now = self.clock()
        identifier = secrets.token_urlsafe(32)
        try:
            with self.store.transaction() as connection:
                mail.reserve_send(address, payload.client_challenge, network)
                user: User | None
                protected = payload.purpose in {
                    "verify_email",
                    "change_email",
                    "reauth",
                }
                token_hash = (
                    self.auth.hash_session_token(raw_token) if raw_token else None
                )
                proof_digest = None
                if protected:
                    if payload.expected_account_id is None:
                        raise ModernAuthError()
                    user = self._owner(raw_token, payload.expected_account_id)
                    if user.email in self.auth.reserved_emails:
                        raise ModernAuthError("invalid_proof", 403)
                    if (
                        payload.purpose in {"verify_email", "reauth"}
                        and address != user.email
                    ):
                        raise self._not_found()
                    if payload.purpose == "reauth":
                        if (
                            not payload.action
                            or user.email_verified_at is None
                            or not self._email_usable(user)
                        ):
                            raise ModernAuthError("reauth_required", 403)
                    else:
                        action = payload.purpose
                        if payload.action != action or not payload.recent_proof:
                            raise ModernAuthError("reauth_required", 403)
                        proof = self._recent(
                            connection, payload.recent_proof, user, raw_token, action
                        )
                        if (
                            action == "verify_email"
                            and json.loads(proof["payload_json"]).get("method")
                            != "password"
                        ):
                            raise ModernAuthError("reauth_required", 403)
                        proof_digest = proof["digest"]
                    eligible = True
                else:
                    user = self.auth.user_repo.get_by_email(address)
                    eligible = (
                        address not in self.auth.reserved_emails
                        and (user is None or self._email_usable(user))
                        and (
                            payload.purpose != "recover"
                            or (user is not None and bool(user.password_hash))
                        )
                        and (
                            user is None
                            or user.deletion_requested_at is None
                            or user.deletion_requested_at + self.auth.deletion_grace
                            > now
                        )
                    )
                connection.execute(
                    "INSERT INTO auth_challenges(id,user_id,auth_version,session_hash,purpose,destination,action,client_challenge,"
                    "eligible,created_at,expires_at,resend_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        user.id if user else None,
                        user.auth_version if user else 0,
                        token_hash if protected else None,
                        payload.purpose,
                        address,
                        payload.action,
                        payload.client_challenge,
                        int(eligible),
                        now.isoformat(),
                        (now + timedelta(minutes=10)).isoformat(),
                        (now + timedelta(seconds=60)).isoformat(),
                        json.dumps(
                            {
                                "client": payload.client,
                                "authorization_digest": proof_digest,
                            }
                        ),
                    ),
                )
                if eligible:
                    mail.enqueue(identifier, f"{secrets.randbelow(1_000_000):06d}")
                row = connection.execute(
                    "SELECT * FROM auth_challenges WHERE id=?", (identifier,)
                ).fetchone()
                assert row is not None
                return self._challenge_response(row)
        except AuthMailError as error:
            raise self._mail_failure(error) from None

    def resend_email(
        self,
        payload: EmailResendRequest,
        *,
        network: str,
        raw_token: str | None = None,
    ) -> ChallengeResponse:
        mail = self._mail()
        try:
            with self.store.transaction() as connection:
                row = self._challenge(
                    connection, payload.challenge_id, payload.client_verifier, raw_token
                )
                if row["failures"] >= 5:
                    raise ModernAuthError("rate_limited", 429)
                if row["eligible"]:
                    mail.resend(row["id"], network=network)
                else:
                    mail.reserve_send(
                        row["destination"], row["client_challenge"], network
                    )
                    connection.execute(
                        "UPDATE auth_challenges SET resend_at=?,generation=generation+1 WHERE id=?",
                        ((self.clock() + timedelta(seconds=60)).isoformat(), row["id"]),
                    )
                fresh = connection.execute(
                    "SELECT * FROM auth_challenges WHERE id=?", (row["id"],)
                ).fetchone()
                assert fresh is not None
                return self._challenge_response(fresh)
        except AuthMailError as error:
            raise self._mail_failure(error) from None

    def verify_email(
        self,
        payload: EmailVerifyRequest,
        *,
        network: str,
        raw_token: str | None = None,
    ) -> AuthResult:
        mail = self._mail()
        with self.store.connection() as connection:
            self._challenge(
                connection, payload.challenge_id, payload.client_verifier, raw_token
            )
        try:
            if not mail.verify_code(
                payload.challenge_id, payload.code, network=network
            ):
                raise ModernAuthError()
            with self.store.transaction() as connection:
                row = self._challenge(
                    connection, payload.challenge_id, payload.client_verifier, raw_token
                )
                if not mail.code_matches(
                    connection, row["id"], payload.code, network=network
                ):
                    raise ModernAuthError()
                if row["purpose"] == "provider_mailbox":
                    attempt = self._attempt(
                        connection, row["attempt_id"], payload.client_verifier
                    )
                    if attempt["status"] != "awaiting_mailbox":
                        raise ModernAuthError()
                    claims = self._provider_claims(attempt)
                    if claims["identity"]["email"] != row["destination"]:
                        raise ModernAuthError()
                    self._consume_challenge(connection, row["id"])
                    return self._finalize_provider(
                        connection, attempt, claims, raw_token
                    )
                if row["purpose"] != "login":
                    return self._finish_email_action(
                        connection, row, payload, raw_token
                    )
                # Known-owner rows cascade on purge; they never become signup.
                user = (
                    self.auth.user_repo.get_by_id(row["user_id"])
                    if row["user_id"]
                    else None
                )
                if row["user_id"]:
                    if (
                        user is None
                        or user.auth_version != row["auth_version"]
                        or user.email != row["destination"]
                        or user.email_verified_at is None
                    ):
                        raise self._not_found()
                elif self.auth.user_repo.get_by_email(row["destination"]) is not None:
                    self._consume_challenge(connection, row["id"])
                    return AuthResult(ExistingAccountRequiredResult())
                if row["destination"] in self.auth.reserved_emails:
                    raise ModernAuthError()
                if user is None:
                    user = self.auth.user_repo.create(
                        User(
                            id="user_" + secrets.token_hex(6),
                            email=row["destination"],
                            password_hash="",
                            email_verified_at=self.clock(),
                            created_at=self.clock(),
                        )
                    )
                acting = self.auth.get_user_for_token(raw_token)
                if acting is not None and acting.id != user.id:
                    raise self._not_found()
                user, cancelled = self._login_owner(
                    user, from_isoformat(row["created_at"])
                )
                self._consume_challenge(connection, row["id"])
                token, _ = self.auth._create_session(user.id, auth_method="email")
                return self._signed_in(user, token, cancelled)
        except AuthMailError as error:
            raise self._mail_failure(error) from None
        except ConflictError:
            raise ModernAuthError("conflict", 409) from None

    def _login_owner(self, user: User, proof_started_at: datetime) -> tuple[User, bool]:
        if user.email in self.auth.reserved_emails:
            raise ModernAuthError()
        if user.deletion_requested_at is None:
            return user, False
        if (
            user.deletion_requested_at + self.auth.deletion_grace <= self.clock()
            or proof_started_at < user.deletion_requested_at
        ):
            raise ModernAuthError()
        fresh = self.auth.user_repo.mutate(
            user.id,
            lambda current: current.model_copy(update={"deletion_requested_at": None}),
        )
        return fresh, True

    def _consume_challenge(
        self, connection: sqlite3.Connection, identifier: str
    ) -> None:
        changed = connection.execute(
            "UPDATE auth_challenges SET status='consumed',code_hmac=NULL,key_id=NULL "
            "WHERE id=? AND status='active'",
            (identifier,),
        ).rowcount
        if changed != 1:
            raise ModernAuthError()
        connection.execute(
            "DELETE FROM auth_mail_jobs WHERE challenge_id=?", (identifier,)
        )

    @staticmethod
    def _signed_in(user: User, token: str, cancelled: bool = False) -> AuthResult:
        return AuthResult(
            SignedInResult(
                user=MeResponse(
                    id=user.id,
                    email=user.email,
                    display_name=user.display_name,
                    deletion_cancelled=cancelled,
                ),
                deletion_cancelled=cancelled,
            ),
            token,
        )

    @staticmethod
    def _attempt_context(row: sqlite3.Row, kind: str) -> SecretContext:
        return SecretContext(
            kind=kind,
            attempt_id=row["id"],
            owner_id=row["user_id"] or "",
            client_id=f"{row['audience']}:{row['client_challenge']}",
        )

    def _box(self) -> AuthSecretBox:
        if self.box is None:
            raise ModernAuthError("method_unavailable", 503)
        return self.box

    def start_provider(
        self,
        provider: Literal["google", "apple"],
        payload: ProviderStartRequest,
        *,
        raw_token: str | None = None,
        network: str = "unknown",
    ) -> ProviderStartResult:
        available = self.methods(payload.client)
        if (provider == "google" and not available.google) or (
            provider == "apple" and not available.apple
        ):
            raise ModernAuthError("method_unavailable", 503)
        if provider not in {"google", "apple"}:
            raise self._not_found()
        identifier, state, nonce = (secrets.token_urlsafe(32) for _ in range(3))
        binder = secrets.token_urlsafe(32) if payload.client == "web" else None
        upstream_verifier = secrets.token_urlsafe(32) if provider == "google" else None
        audience = (
            self.settings.google_client_id
            if provider == "google"
            else (
                self.settings.apple_services_id
                if payload.client == "web"
                else self.settings.apple_native_app_id
            )
        )
        native_apple = provider == "apple" and payload.client == "ios"
        url = (
            None
            if native_apple
            else self.provider.authorization_url(
                provider,
                state=state,
                nonce=nonce,
                redirect_uri=self.provider.callback_uri(provider),
                pkce_verifier=upstream_verifier,
            )
        )
        now = self.clock()
        with self.store.transaction() as connection:
            self._reserve_provider_start(connection, payload.client_challenge, network)
            user, token_hash, deadline = None, None, None
            if payload.purpose != "login":
                if payload.expected_account_id is None:
                    raise ModernAuthError()
                user = self._owner(raw_token, payload.expected_account_id)
                if user.email in self.auth.reserved_emails or not payload.action:
                    raise ModernAuthError("reauth_required", 403)
                token_hash = (
                    self.auth.hash_session_token(raw_token) if raw_token else None
                )
                if payload.purpose == "link":
                    if payload.action != f"link:{provider}" or not payload.recent_proof:
                        raise ModernAuthError("reauth_required", 403)
                    proof = self._recent(
                        connection,
                        payload.recent_proof,
                        user,
                        raw_token,
                        payload.action,
                        consume=True,
                    )
                    deadline = proof["expires_at"]
            connection.execute(
                "INSERT INTO auth_attempts(id,user_id,auth_version,session_hash,provider,intent,action,channel,client_challenge,state_hash,nonce_hash,binder_hash,"
                "audience,redirect_label,created_at,expires_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    user.id if user else None,
                    user.auth_version if user else 0,
                    token_hash,
                    provider,
                    payload.purpose,
                    payload.action,
                    payload.client,
                    payload.client_challenge,
                    self.auth.hash_session_token(state),
                    self.auth.hash_session_token(nonce),
                    self.auth.hash_session_token(binder) if binder else None,
                    audience,
                    "web" if payload.client == "web" else "ios",
                    now.isoformat(),
                    (now + timedelta(minutes=10)).isoformat(),
                    json.dumps({"confirmation_deadline": deadline}),
                ),
            )
            row = connection.execute(
                "SELECT * FROM auth_attempts WHERE id=?", (identifier,)
            ).fetchone()
            assert row is not None
            sealed = self._box().seal(
                json.dumps({"nonce": nonce, "verifier": upstream_verifier}).encode(),
                self._attempt_context(row, "provider_start"),
            )
            connection.execute(
                "UPDATE auth_attempts SET sealed_payload=?,key_id=? WHERE id=?",
                (sealed, self._box().current_key_id, identifier),
            )
        return ProviderStartResult(
            ProviderStartResponse(
                attempt_id=identifier, state=state, nonce=nonce, authorization_url=url
            ),
            binder,
        )

    def _attempt(
        self, connection: sqlite3.Connection, identifier: str, verifier: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM auth_attempts WHERE id=?", (identifier,)
        ).fetchone()
        if row is None or not hmac.compare_digest(
            row["client_challenge"], client_challenge(verifier)
        ):
            raise self._not_found()
        if from_isoformat(row["expires_at"]) <= self.clock() or row["status"] in {
            "consumed",
            "failed",
        }:
            raise ModernAuthError()
        return cast(sqlite3.Row, row)

    def provider_callback(
        self,
        provider: Literal["google", "apple"],
        *,
        code: str,
        state: str,
        binder: str | None = None,
    ) -> ProviderCallbackResult:
        identifier, lease = "", secrets.token_urlsafe(32)
        try:
            with self.store.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM auth_attempts WHERE state_hash=?",
                    (self.auth.hash_session_token(state),),
                ).fetchone()
                if row is None or row["provider"] != provider:
                    raise self._not_found()
                if row["channel"] == "web" and (
                    binder is None
                    or not hmac.compare_digest(
                        row["binder_hash"], self.auth.hash_session_token(binder)
                    )
                ):
                    raise ModernAuthError("invalid_proof", 403)
                if (
                    row["status"] != "started"
                    or from_isoformat(row["expires_at"]) <= self.clock()
                ):
                    raise ModernAuthError()
                if provider == "apple" and row["channel"] != "web":
                    raise ModernAuthError()
                identifier = row["id"]
                start = json.loads(
                    self._box().open(
                        row["sealed_payload"],
                        self._attempt_context(row, "provider_start"),
                    )
                )
                connection.execute(
                    "UPDATE auth_attempts SET status='exchanging',lease_id=?,lease_expires_at=? WHERE id=?",
                    (
                        lease,
                        (self.clock() + timedelta(seconds=30)).isoformat(),
                        identifier,
                    ),
                )
            # The provider call is bounded and never runs under an Identity write.
            if provider == "google":
                tokens = self.provider.exchange_google(
                    code,
                    redirect_uri=self.provider.callback_uri(provider),
                    pkce_verifier=start["verifier"],
                    nonce=start["nonce"],
                )
            else:
                tokens = self.provider.exchange_apple(
                    code,
                    redirect_uri=self.provider.callback_uri(provider),
                    nonce=start["nonce"],
                )
            handoff = secrets.token_urlsafe(32)
            with self.store.transaction() as connection:
                current = connection.execute(
                    "SELECT * FROM auth_attempts WHERE id=?", (identifier,)
                ).fetchone()
                if (
                    current is None
                    or current["status"] != "exchanging"
                    or current["lease_id"] != lease
                    or from_isoformat(current["lease_expires_at"]) <= self.clock()
                    or from_isoformat(current["expires_at"]) <= self.clock()
                ):
                    raise ModernAuthError()
                self._stage_provider(connection, current, tokens)
                connection.execute(
                    "INSERT INTO auth_handoffs(digest,attempt_id,expires_at) VALUES(?,?,?)",
                    (
                        self.auth.hash_session_token(handoff),
                        identifier,
                        min(
                            self.clock() + timedelta(seconds=60),
                            from_isoformat(current["expires_at"]),
                        ).isoformat(),
                    ),
                )
                connection.execute(
                    "UPDATE auth_attempts SET status='callback_ready',lease_id=NULL,lease_expires_at=NULL WHERE id=?",
                    (identifier,),
                )
                query = urlencode(
                    {"attempt": identifier, "state": state, "grant": handoff}
                )
                url = (
                    f"{self.settings.public_origin}/auth/complete#{query}"
                    if current["channel"] == "web"
                    else f"brainbuddy://auth/callback?{query}"
                )
                return ProviderCallbackResult(url)
        except (ProviderError, AuthSecretError, ModernAuthError) as error:
            if identifier:
                with self.store.transaction() as connection:
                    connection.execute(
                        "UPDATE auth_attempts SET status='failed',sealed_payload=NULL,key_id=NULL,lease_id=NULL WHERE id=? AND lease_id=?",
                        (identifier, lease),
                    )
            if isinstance(error, ModernAuthError):
                raise
            failure_code = (
                error.code if isinstance(error, ProviderError) else "invalid_proof"
            )
            raise ModernAuthError(
                failure_code, 503 if failure_code != "invalid_proof" else 400
            ) from None

    def _stage_provider(
        self, connection: sqlite3.Connection, row: sqlite3.Row, tokens: ProviderTokens
    ) -> None:
        identity = tokens.identity
        if identity.provider != row["provider"] or identity.audience != row["audience"]:
            raise ModernAuthError()
        binding = connection.execute(
            "SELECT * FROM auth_identity_bindings WHERE provider=? AND issuer=? AND namespace=? AND subject=?",
            (identity.provider, identity.issuer, identity.namespace, identity.subject),
        ).fetchone()
        owner = (
            self.auth.user_repo.get_by_id(binding["user_id"])
            if binding
            else (
                self.auth.user_repo.get_by_email(identity.email)
                if identity.email
                else None
            )
        )
        if owner is not None and row["intent"] == "login":
            connection.execute(
                "UPDATE auth_attempts SET user_id=?,auth_version=? WHERE id=?",
                (owner.id, owner.auth_version, row["id"]),
            )
        current = connection.execute(
            "SELECT * FROM auth_attempts WHERE id=?", (row["id"],)
        ).fetchone()
        assert current is not None
        claims = {
            "identity": asdict(identity),
            "issuing_client": tokens.issuing_client,
            "revocation_token": (
                tokens.revocation_token.get_secret_value()
                if tokens.revocation_token
                else None
            ),
            "revocation_token_type": tokens.revocation_token_type,
            "binding_id": binding["id"] if binding else None,
            "generation": binding["generation"] if binding else None,
        }
        sealed = self._box().seal(
            json.dumps(claims).encode(),
            self._attempt_context(current, "provider_identity"),
        )
        connection.execute(
            "UPDATE auth_attempts SET sealed_payload=?,key_id=? WHERE id=?",
            (sealed, self._box().current_key_id, row["id"]),
        )

    def _provider_claims(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            claims = json.loads(
                self._box().open(
                    row["sealed_payload"],
                    self._attempt_context(row, "provider_identity"),
                )
            )
            if not isinstance(claims, dict):
                raise ModernAuthError()
            return claims
        except (AuthSecretError, ValueError, TypeError):
            raise ModernAuthError() from None

    def complete_provider(
        self,
        payload: ProviderCompleteRequest,
        *,
        raw_token: str | None = None,
        network: str = "unknown",
    ) -> AuthResult:
        with self.store.transaction() as connection:
            row = self._attempt(connection, payload.attempt_id, payload.client_verifier)
            if row["status"] != "callback_ready" or not hmac.compare_digest(
                row["state_hash"], self.auth.hash_session_token(payload.state)
            ):
                raise ModernAuthError()
            handoff = connection.execute(
                "SELECT * FROM auth_handoffs WHERE digest=? AND attempt_id=?",
                (self.auth.hash_session_token(payload.handoff_code), row["id"]),
            ).fetchone()
            if (
                handoff is None
                or handoff["consumed_at"] is not None
                or from_isoformat(handoff["expires_at"]) <= self.clock()
            ):
                raise ModernAuthError()
            claims = self._provider_claims(row)
            connection.execute(
                "UPDATE auth_handoffs SET consumed_at=? WHERE digest=? AND consumed_at IS NULL",
                (self.clock().isoformat(), handoff["digest"]),
            )
            return self._complete_staged(connection, row, claims, raw_token, network)

    def _complete_staged(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        claims: dict[str, Any],
        raw_token: str | None,
        network: str,
    ) -> AuthResult:
        identity = ProviderIdentity(**claims["identity"])
        if (
            row["intent"] == "login"
            and claims["binding_id"] is None
            and not identity.email_authoritative
        ):
            if not identity.email or identity.email in self.auth.reserved_emails:
                raise ModernAuthError()
            mail = self._mail()
            try:
                mail.reserve_send(identity.email, row["client_challenge"], network)
                identifier = secrets.token_urlsafe(32)
                now = self.clock()
                connection.execute(
                    "INSERT INTO auth_challenges(id,user_id,auth_version,purpose,destination,attempt_id,client_challenge,eligible,created_at,expires_at,resend_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        row["user_id"],
                        row["auth_version"],
                        "provider_mailbox",
                        identity.email,
                        row["id"],
                        row["client_challenge"],
                        1,
                        now.isoformat(),
                        row["expires_at"],
                        (now + timedelta(seconds=60)).isoformat(),
                    ),
                )
                mail.enqueue(identifier, f"{secrets.randbelow(1_000_000):06d}")
                connection.execute(
                    "UPDATE auth_attempts SET status='awaiting_mailbox' WHERE id=?",
                    (row["id"],),
                )
                challenge_row = connection.execute(
                    "SELECT * FROM auth_challenges WHERE id=?", (identifier,)
                ).fetchone()
                assert challenge_row is not None
                return AuthResult(
                    VerifyMailboxResult(
                        **self._challenge_response(challenge_row).model_dump()
                    )
                )
            except AuthMailError as error:
                raise self._mail_failure(error) from None
        return self._finalize_provider(connection, row, claims, raw_token)

    def _finalize_provider(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        claims: dict[str, Any],
        raw_token: str | None,
    ) -> AuthResult:
        identity = ProviderIdentity(**claims["identity"])
        owner = (
            self.auth.user_repo.get_by_id(row["user_id"]) if row["user_id"] else None
        )
        if row["user_id"] and (
            owner is None or owner.auth_version != row["auth_version"]
        ):
            raise self._not_found()
        binding = connection.execute(
            "SELECT * FROM auth_identity_bindings WHERE provider=? AND issuer=? AND namespace=? AND subject=?",
            (identity.provider, identity.issuer, identity.namespace, identity.subject),
        ).fetchone()
        if row["intent"] != "login":
            return self._finish_provider_action(
                connection, row, claims, binding, raw_token
            )
        if claims["binding_id"]:
            if (
                binding is None
                or binding["id"] != claims["binding_id"]
                or binding["generation"] != claims["generation"]
            ):
                raise ModernAuthError()
            if binding["state"] == "unlinked":
                self._consume_attempt(connection, row["id"])
                return AuthResult(ExistingAccountRequiredResult())
            owner = self.auth.user_repo.get_by_id(binding["user_id"])
        elif (
            binding is not None
            or owner is not None
            or (identity.email and self.auth.user_repo.get_by_email(identity.email))
        ):
            self._consume_attempt(connection, row["id"])
            return AuthResult(ExistingAccountRequiredResult())
        acting = self.auth.get_user_for_token(raw_token)
        if acting is not None and (owner is None or acting.id != owner.id):
            raise self._not_found()
        if owner is None:
            if not identity.email or identity.email in self.auth.reserved_emails:
                raise ModernAuthError()
            owner = self.auth.user_repo.create(
                User(
                    id="user_" + secrets.token_hex(6),
                    email=identity.email,
                    email_verified_at=self.clock(),
                    created_at=self.clock(),
                )
            )
            identifier = "binding_" + secrets.token_hex(16)
            connection.execute(
                "INSERT INTO auth_identity_bindings(id,user_id,provider,issuer,namespace,subject,created_at,updated_at,email,email_verified,is_private_email) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    owner.id,
                    identity.provider,
                    identity.issuer,
                    identity.namespace,
                    identity.subject,
                    self.clock().isoformat(),
                    self.clock().isoformat(),
                    identity.email,
                    1,
                    int(identity.is_private_email),
                ),
            )
        else:
            if binding is None:
                raise ModernAuthError()
            identifier = binding["id"]
        if binding is not None and identity.provider == "apple":
            self._apple().ensure_replaceable(connection, binding["id"])
        if binding is not None and binding["state"] != "active":
            connection.execute(
                "UPDATE auth_identity_bindings SET state='active',generation=generation+1,updated_at=? WHERE id=?",
                (self.clock().isoformat(), identifier),
            )
        self._record_apple(connection, identifier, claims)
        owner, cancelled = self._login_owner(owner, from_isoformat(row["created_at"]))
        self._consume_attempt(connection, row["id"])
        token, _ = self.auth._create_session(
            owner.id, auth_method=identity.provider, provider_binding_id=identifier
        )
        return self._signed_in(owner, token, cancelled)

    def _consume_attempt(self, connection: sqlite3.Connection, identifier: str) -> None:
        changed = connection.execute(
            "UPDATE auth_attempts SET status='consumed',sealed_payload=NULL,key_id=NULL,lease_id=NULL,lease_expires_at=NULL WHERE id=? AND status IN ('callback_ready','awaiting_mailbox')",
            (identifier,),
        ).rowcount
        if changed != 1:
            raise ModernAuthError()

    def _owner(self, raw_token: str | None, expected: str | None = None) -> User:
        user = self.auth.get_user_for_token(raw_token)
        if user is None:
            raise ModernAuthError("invalid_proof", 401)
        if expected is not None and not hmac.compare_digest(user.id, expected):
            raise self._not_found()
        return user

    def _email_usable(self, user: User) -> bool:
        if (
            not self.settings.email_available
            or not user.email_verified_at
            or user.email in self.auth.reserved_emails
        ):
            return False
        with self.store.connection() as connection:
            bindings = connection.execute(
                "SELECT email,payload_json FROM auth_identity_bindings WHERE user_id=? AND provider='apple'",
                (user.id,),
            ).fetchall()
            return not any(
                row["email"] == user.email
                and json.loads(row["payload_json"]).get(
                    "email_delivery_disabled", False
                )
                for row in bindings
            )

    def _issue_proof(
        self,
        connection: sqlite3.Connection,
        user: User,
        *,
        purpose: str,
        raw_token: str | None = None,
        action: str | None = None,
        client: str | None = None,
        method: str = "password",
        binding_id: str | None = None,
    ) -> tuple[str, datetime]:
        secret = secrets.token_urlsafe(32)
        expires = self.clock() + timedelta(minutes=5 if purpose == "recent" else 10)
        generation = None
        if binding_id:
            binding = connection.execute(
                "SELECT generation FROM auth_identity_bindings WHERE id=? AND user_id=? AND state='active'",
                (binding_id, user.id),
            ).fetchone()
            if binding is None:
                raise ModernAuthError("reauth_required", 403)
            generation = binding["generation"]
        connection.execute(
            "INSERT INTO auth_proofs(digest,user_id,auth_version,session_hash,client_challenge,purpose,action,provider_binding_id,generation,created_at,expires_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.auth.hash_session_token(secret),
                user.id,
                user.auth_version,
                self.auth.hash_session_token(raw_token) if raw_token else None,
                client,
                purpose,
                action,
                binding_id,
                generation,
                self.clock().isoformat(),
                expires.isoformat(),
                json.dumps({"method": method}),
            ),
        )
        return secret, expires

    def _recent(
        self,
        connection: sqlite3.Connection,
        secret: str,
        user: User,
        raw_token: str | None,
        action: str,
        *,
        consume: bool = False,
        is_digest: bool = False,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM auth_proofs WHERE digest=?",
            (secret if is_digest else self.auth.hash_session_token(secret),),
        ).fetchone()
        if row is None or row["user_id"] != user.id:
            raise self._not_found()
        if row["session_hash"] != (
            self.auth.hash_session_token(raw_token) if raw_token else None
        ):
            raise self._not_found()
        if (
            row["purpose"] != "recent"
            or row["action"] != action
            or row["auth_version"] != user.auth_version
            or row["consumed_at"]
            or from_isoformat(row["expires_at"]) <= self.clock()
        ):
            raise ModernAuthError("reauth_required", 403)
        if row["provider_binding_id"]:
            binding = connection.execute(
                "SELECT state,generation FROM auth_identity_bindings WHERE id=? AND user_id=?",
                (row["provider_binding_id"], user.id),
            ).fetchone()
            if (
                binding is None
                or binding["state"] != "active"
                or binding["generation"] != row["generation"]
            ):
                raise ModernAuthError("reauth_required", 403)
        if consume and (
            connection.execute(
                "UPDATE auth_proofs SET consumed_at=? WHERE digest=? AND consumed_at IS NULL",
                (self.clock().isoformat(), row["digest"]),
            ).rowcount
            != 1
        ):
            raise ModernAuthError("reauth_required", 403)
        return cast(sqlite3.Row, row)

    def confirm_password(
        self, payload: PasswordConfirmRequest, *, raw_token: str | None
    ) -> ReauthenticatedResult:
        with self.store.connection():
            snapshot = self._owner(raw_token, payload.expected_account_id)
        if not self.auth.verify_password(snapshot, payload.current_password):
            raise ModernAuthError("reauth_required", 403)
        with self.store.transaction() as connection:
            user = self._owner(raw_token, payload.expected_account_id)
            if not self.auth.same_authority(snapshot, user):
                raise ModernAuthError("reauth_required", 403)
            secret, expires = self._issue_proof(
                connection,
                user,
                purpose="recent",
                raw_token=raw_token,
                action=payload.action,
            )
            return ReauthenticatedResult(recent_proof=secret, expires_at=expires)

    def _finish_email_action(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        payload: EmailVerifyRequest,
        raw_token: str | None,
    ) -> AuthResult:
        user = self.auth.user_repo.get_by_id(row["user_id"]) if row["user_id"] else None
        if (
            user is None
            or user.auth_version != row["auth_version"]
            or user.email in self.auth.reserved_emails
        ):
            raise self._not_found()
        if user.deletion_requested_at is not None:
            raise ModernAuthError()
        if row["purpose"] == "recover":
            if (
                user.email != row["destination"]
                or not self._email_usable(user)
                or not user.password_hash
            ):
                raise ModernAuthError()
            self._consume_challenge(connection, row["id"])
            secret, expires = self._issue_proof(
                connection,
                user,
                purpose="reset",
                client=row["client_challenge"],
                method="email",
            )
            return AuthResult(ResetReadyResult(reset_grant=secret, expires_at=expires))
        user = self._owner(raw_token, row["user_id"])
        if row["purpose"] == "reauth":
            if (
                row["destination"] != user.email
                or not self._email_usable(user)
                or not row["action"]
            ):
                raise ModernAuthError()
            self._consume_challenge(connection, row["id"])
            secret, expires = self._issue_proof(
                connection,
                user,
                purpose="recent",
                raw_token=raw_token,
                action=row["action"],
                method="email",
            )
            return AuthResult(
                ReauthenticatedResult(recent_proof=secret, expires_at=expires)
            )
        if row["purpose"] not in {"verify_email", "change_email"}:
            raise ModernAuthError()
        recorded = json.loads(row["payload_json"]).get("authorization_digest")
        proof = self._recent(
            connection,
            payload.recent_proof or recorded or "",
            user,
            raw_token,
            row["purpose"],
            consume=True,
            is_digest=payload.recent_proof is None,
        )
        if (
            row["purpose"] == "verify_email"
            and json.loads(proof["payload_json"]).get("method") != "password"
        ):
            raise ModernAuthError("reauth_required", 403)
        self._consume_challenge(connection, row["id"])
        if row["purpose"] == "change_email":
            if row["destination"] in self.auth.reserved_emails:
                raise ModernAuthError("conflict", 409)
            user = self.auth.user_repo.update_email(user.id, row["destination"])
        user = self.auth.user_repo.mutate(
            user.id,
            lambda fresh: fresh.model_copy(update={"email_verified_at": self.clock()}),
        )
        self.account._keep_current_session(
            user, self.auth.hash_session_token(raw_token) if raw_token else None
        )
        self.auth.session_repo.delete_all_for_user(
            user.id,
            keep=(self.auth.hash_session_token(raw_token) if raw_token else None),
        )
        return AuthResult(
            VerifiedEmailResult(
                status=(
                    "changed_email"
                    if row["purpose"] == "change_email"
                    else "verified_email"
                ),
                user=MeResponse(
                    id=user.id, email=user.email, display_name=user.display_name
                ),
            )
        )

    def reset_password(self, payload: ResetRequest) -> None:
        try:
            self.auth.validate_password_format(payload.new_password)
        except ValidationFailure:
            raise ModernAuthError("invalid_proof", 400) from None
        hashed = self.auth.hash_password(payload.new_password)
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM auth_proofs WHERE digest=?",
                (self.auth.hash_session_token(payload.reset_grant),),
            ).fetchone()
            if (
                row is None
                or not row["client_challenge"]
                or not hmac.compare_digest(
                    row["client_challenge"], client_challenge(payload.client_verifier)
                )
            ):
                raise self._not_found()
            user = self.auth.user_repo.get_by_id(row["user_id"])
            if (
                user is None
                or row["purpose"] != "reset"
                or row["consumed_at"]
                or from_isoformat(row["expires_at"]) <= self.clock()
                or user.auth_version != row["auth_version"]
                or not user.password_hash
                or not self._email_usable(user)
                or user.deletion_requested_at is not None
            ):
                raise ModernAuthError()
            self.auth.user_repo.mutate(
                user.id,
                lambda fresh: fresh.model_copy(update={"password_hash": hashed}),
            )
            self.auth.session_repo.delete_all_for_user(user.id)

    def account_methods(self, *, raw_token: str | None) -> AccountMethodsResponse:
        with self.store.connection() as connection:
            user = self._owner(raw_token)
            email_usable = self._email_usable(user)
            delivery: Literal["available", "disabled", "unconfigured"] = (
                "unconfigured"
                if not self.settings.email_available
                else ("available" if email_usable else "disabled")
            )
            methods = [
                ConnectedMethod(
                    method="password",
                    state="active" if user.password_hash else "disabled",
                    usable=bool(user.password_hash),
                    connected_at=user.created_at if user.password_hash else None,
                ),
                ConnectedMethod(
                    method="email",
                    state="active" if email_usable else "disabled",
                    usable=email_usable,
                    connected_at=user.email_verified_at,
                ),
            ]
            for binding in connection.execute(
                "SELECT * FROM auth_identity_bindings WHERE user_id=? ORDER BY provider",
                (user.id,),
            ).fetchall():
                provider = binding["provider"]
                usable = (
                    binding["state"] == "active"
                    and user.email not in self.auth.reserved_emails
                    and (
                        self.settings.google_available
                        if provider == "google"
                        else (
                            self.settings.apple_web_available
                            or self.settings.apple_native_available
                        )
                    )
                )
                methods.append(
                    ConnectedMethod(
                        method=provider,
                        state="active" if binding["state"] == "active" else "disabled",
                        usable=usable,
                        connected_at=from_isoformat(binding["created_at"]),
                    )
                )
            return AccountMethodsResponse(
                account_id=user.id,
                email=user.email,
                email_verified=user.email_verified_at is not None,
                email_delivery=delivery,
                has_password=bool(user.password_hash),
                methods=methods,
            )

    def set_password(
        self, payload: AccountPasswordRequest, *, raw_token: str | None
    ) -> None:
        self._owner(raw_token, payload.expected_account_id)
        try:
            self.auth.validate_password_format(payload.new_password)
        except ValidationFailure:
            raise ModernAuthError() from None
        hashed = self.auth.hash_password(payload.new_password)
        with self.store.transaction() as connection:
            user = self._owner(raw_token, payload.expected_account_id)
            self._recent(
                connection,
                payload.recent_proof,
                user,
                raw_token,
                "password",
                consume=True,
            )
            user = self.auth.user_repo.mutate(
                user.id,
                lambda fresh: fresh.model_copy(update={"password_hash": hashed}),
            )
            token_hash = self.auth.hash_session_token(raw_token) if raw_token else None
            self.account._keep_current_session(user, token_hash)
            self.auth.session_repo.delete_all_for_user(user.id, keep=token_hash)

    def export_account(
        self, payload: AccountActionRequest, *, raw_token: str | None
    ) -> tuple[str, IO[bytes]]:
        with self.store.transaction() as connection:
            user = self._owner(raw_token, payload.expected_account_id)
            self._recent(
                connection,
                payload.recent_proof,
                user,
                raw_token,
                "export",
                consume=True,
            )
            return self.account.export_account_data(user)

    def delete_account(
        self, payload: AccountActionRequest, *, raw_token: str | None
    ) -> User:
        with self.store.transaction() as connection:
            user = self._owner(raw_token, payload.expected_account_id)
            self._recent(
                connection,
                payload.recent_proof,
                user,
                raw_token,
                "delete",
                consume=True,
            )
            user = self.auth.user_repo.mutate(
                user.id,
                lambda fresh: fresh.model_copy(
                    update={
                        "deletion_requested_at": fresh.deletion_requested_at
                        or self.clock(),
                        "auth_version": fresh.auth_version + 1,
                    }
                ),
            )
            self._schedule_apple_owner(connection, user.id, "delete")
            self._invalidate_owner(connection, user.id)
            self.auth.session_repo.delete_all_for_user(user.id)
            return user

    @staticmethod
    def _invalidate_owner(connection: sqlite3.Connection, owner_id: str) -> None:
        connection.execute("DELETE FROM auth_proofs WHERE user_id=?", (owner_id,))
        connection.execute("DELETE FROM auth_challenges WHERE user_id=?", (owner_id,))
        connection.execute("DELETE FROM auth_attempts WHERE user_id=?", (owner_id,))

    def unlink(
        self,
        provider: Literal["google", "apple"],
        payload: AccountActionRequest,
        *,
        raw_token: str | None,
    ) -> UnlinkResponse:
        with self.store.transaction() as connection:
            user = self._owner(raw_token, payload.expected_account_id)
            self._recent(
                connection, payload.recent_proof, user, raw_token, f"unlink:{provider}"
            )
            binding = connection.execute(
                "SELECT * FROM auth_identity_bindings WHERE user_id=? AND provider=? AND state='active'",
                (user.id, provider),
            ).fetchone()
            if binding is None:
                raise self._not_found()
            current = self.account_methods(raw_token=raw_token)
            if not any(
                method.usable and method.method != provider
                for method in current.methods
            ):
                raise ModernAuthError("last_method", 409)
            self._recent(
                connection,
                payload.recent_proof,
                user,
                raw_token,
                f"unlink:{provider}",
                consume=True,
            )
            token_hash = self.auth.hash_session_token(raw_token) if raw_token else None
            caller = self.auth.session_repo.get(token_hash) if token_hash else None
            signed_out = (
                caller is not None and caller.provider_binding_id == binding["id"]
            )
            if provider == "apple":
                self._apple().schedule_cleanup(connection, binding["id"], "unlink")
                deadline = self.clock() + timedelta(hours=24)
                job_deadline = connection.execute(
                    "SELECT min(expires_at) FROM auth_apple_cleanup_jobs WHERE binding_id=?",
                    (binding["id"],),
                ).fetchone()[0]
                if job_deadline is not None:
                    deadline = min(deadline, from_isoformat(job_deadline))
                connection.execute(
                    "UPDATE auth_identity_bindings SET state='unlinked',updated_at=?,email=NULL,email_verified=0,is_private_email=0,payload_json=? WHERE id=?",
                    (
                        self.clock().isoformat(),
                        json.dumps({"unlinked_expires_at": deadline.isoformat()}),
                        binding["id"],
                    ),
                )
            else:
                connection.execute(
                    "DELETE FROM auth_identity_bindings WHERE id=?", (binding["id"],)
                )
            connection.execute(
                "DELETE FROM sessions WHERE provider_binding_id=?", (binding["id"],)
            )
            connection.execute("DELETE FROM auth_proofs WHERE user_id=?", (user.id,))
            connection.execute(
                "DELETE FROM auth_attempts WHERE user_id=? AND provider=?",
                (user.id, provider),
            )
            erase_settled_apple_unlinks(connection, now=self.clock())
            # Compute safe remaining methods before clearing the originating session.
            remaining = current.model_copy(
                update={
                    "methods": [
                        (
                            method.model_copy(
                                update={"state": "disabled", "usable": False}
                            )
                            if method.method == provider
                            else method
                        )
                        for method in current.methods
                    ]
                }
            )
            response = UnlinkResponse(methods=remaining, signed_out=signed_out)
        self.store.checkpoint()
        return response

    def _finish_provider_action(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        claims: dict[str, Any],
        binding: sqlite3.Row | None,
        raw_token: str | None,
    ) -> AuthResult:
        user = self._owner(raw_token, row["user_id"])
        if user.auth_version != row["auth_version"] or row["session_hash"] != (
            self.auth.hash_session_token(raw_token) if raw_token else None
        ):
            raise self._not_found()
        if user.email in self.auth.reserved_emails:
            raise ModernAuthError("invalid_proof", 403)
        identity = ProviderIdentity(**claims["identity"])
        if binding is not None and binding["user_id"] != user.id:
            raise self._not_found()
        if identity.provider == "apple" and binding is not None:
            self._apple().ensure_replaceable(connection, binding["id"])
        if row["intent"] == "reauth":
            if (
                binding is None
                or binding["state"] != "active"
                or binding["id"] != claims["binding_id"]
                or binding["generation"] != claims["generation"]
            ):
                raise ModernAuthError("reauth_required", 403)
            self._record_apple(connection, binding["id"], claims)
            self._consume_attempt(connection, row["id"])
            secret, expires = self._issue_proof(
                connection,
                user,
                purpose="recent",
                raw_token=raw_token,
                action=row["action"],
                method=identity.provider,
                binding_id=binding["id"],
            )
            return AuthResult(
                ReauthenticatedResult(recent_proof=secret, expires_at=expires)
            )
        deadline = json.loads(row["payload_json"]).get("confirmation_deadline")
        if not deadline or from_isoformat(deadline) <= self.clock():
            raise ModernAuthError("reauth_required", 403)
        existing = connection.execute(
            "SELECT * FROM auth_identity_bindings WHERE user_id=? AND provider=?",
            (user.id, identity.provider),
        ).fetchone()
        if existing is not None and (
            binding is None or existing["id"] != binding["id"]
        ):
            raise ModernAuthError("conflict", 409)
        if binding is None:
            connection.execute(
                "INSERT INTO auth_identity_bindings(id,user_id,provider,issuer,namespace,subject,created_at,updated_at,email,email_verified,is_private_email) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "binding_" + secrets.token_hex(16),
                    user.id,
                    identity.provider,
                    identity.issuer,
                    identity.namespace,
                    identity.subject,
                    self.clock().isoformat(),
                    self.clock().isoformat(),
                    identity.email,
                    int(identity.email_authoritative),
                    int(identity.is_private_email),
                ),
            )
        elif binding["state"] != "active":
            if binding["generation"] != claims["generation"]:
                raise ModernAuthError()
            connection.execute(
                "UPDATE auth_identity_bindings SET state='active',generation=generation+1,updated_at=?,email=?,email_verified=?,is_private_email=? WHERE id=?",
                (
                    self.clock().isoformat(),
                    identity.email,
                    int(identity.email_authoritative),
                    int(identity.is_private_email),
                    binding["id"],
                ),
            )
        linked_binding = connection.execute(
            "SELECT id FROM auth_identity_bindings WHERE user_id=? AND provider=?",
            (user.id, identity.provider),
        ).fetchone()
        assert linked_binding is not None
        self._record_apple(connection, linked_binding["id"], claims)
        self._consume_attempt(connection, row["id"])
        return AuthResult(
            LinkedResult(
                user=MeResponse(
                    id=user.id, email=user.email, display_name=user.display_name
                )
            )
        )

    def complete_native_apple(
        self,
        payload: AppleNativeCompleteRequest,
        *,
        raw_token: str | None = None,
        network: str = "unknown",
    ) -> AuthResult:
        lease = secrets.token_urlsafe(32)
        with self.store.transaction() as connection:
            row = self._attempt(connection, payload.attempt_id, payload.client_verifier)
            if (
                row["provider"] != "apple"
                or row["channel"] != "ios"
                or row["status"] != "started"
                or not hmac.compare_digest(
                    row["state_hash"], self.auth.hash_session_token(payload.state)
                )
            ):
                raise ModernAuthError()
            connection.execute(
                "UPDATE auth_attempts SET status='exchanging',lease_id=?,lease_expires_at=? WHERE id=?",
                (lease, (self.clock() + timedelta(seconds=30)).isoformat(), row["id"]),
            )
        try:
            start = json.loads(
                self._box().open(
                    row["sealed_payload"], self._attempt_context(row, "provider_start")
                )
            )
            tokens = self.provider.exchange_apple(
                payload.authorization_code,
                nonce=start["nonce"],
                native_identity_token=payload.identity_token,
            )
            with self.store.transaction() as connection:
                row = self._attempt(
                    connection, payload.attempt_id, payload.client_verifier
                )
                if (
                    row["status"] != "exchanging"
                    or row["lease_id"] != lease
                    or from_isoformat(row["lease_expires_at"]) <= self.clock()
                ):
                    raise ModernAuthError()
                self._stage_provider(connection, row, tokens)
                connection.execute(
                    "UPDATE auth_attempts SET status='callback_ready',lease_id=NULL,lease_expires_at=NULL WHERE id=?",
                    (row["id"],),
                )
                current = connection.execute(
                    "SELECT * FROM auth_attempts WHERE id=?", (row["id"],)
                ).fetchone()
                assert current is not None
                return self._complete_staged(
                    connection,
                    current,
                    self._provider_claims(current),
                    raw_token,
                    network,
                )
        except (
            ProviderError,
            AuthSecretError,
            ModernAuthError,
            AuthAppleLifecycleError,
        ) as error:
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE auth_attempts SET status='failed',sealed_payload=NULL,key_id=NULL,lease_id=NULL,lease_expires_at=NULL WHERE id=? AND lease_id=?",
                    (payload.attempt_id, lease),
                )
            if isinstance(error, ModernAuthError):
                raise
            if isinstance(error, AuthAppleLifecycleError):
                raise ModernAuthError(error.code, error.status_code) from None
            code = error.code if isinstance(error, ProviderError) else "invalid_proof"
            raise ModernAuthError(
                code, 503 if code != "invalid_proof" else 400
            ) from None

    def completion_user(self, identifier: str) -> User:
        user = self.auth.user_repo.get_by_id(identifier)
        if user is None:
            raise self._not_found()
        return user

    def caller(self, raw_token: str | None, expected: str) -> User:
        return self._owner(raw_token, expected)

    def _apple(self) -> AppleLifecycle:
        if self.apple is None:
            raise ModernAuthError("method_unavailable", 503)
        return self.apple

    def _record_apple(
        self, connection: sqlite3.Connection, binding_id: str, claims: dict[str, Any]
    ) -> None:
        identity = ProviderIdentity(**claims["identity"])
        if identity.provider == "apple":
            token = claims["revocation_token"]
            if not token:
                raise ModernAuthError()
            self._apple().record_grant(
                connection,
                binding_id,
                ProviderTokens(
                    identity,
                    claims["issuing_client"],
                    SecretStr(token),
                    claims["revocation_token_type"],
                ),
            )

    def _schedule_apple_owner(
        self, connection: sqlite3.Connection, owner_id: str, reason: str
    ) -> None:
        for row in connection.execute(
            "SELECT id FROM auth_identity_bindings WHERE user_id=? AND provider='apple'",
            (owner_id,),
        ).fetchall():
            self._apple().schedule_cleanup(connection, row["id"], reason)

    def process_apple_notification(self, payload: str) -> None:
        self._apple().process_notification(payload)

    def dispatch_one(self) -> bool:
        delivered = self.mail.dispatch_one() if self.mail else False
        revoked = self.apple.dispatch_one() if self.apple else False
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE auth_attempts SET status='failed',sealed_payload=NULL,key_id=NULL,lease_id=NULL,lease_expires_at=NULL WHERE status='exchanging' AND lease_expires_at<=?",
                (self.clock().isoformat(),),
            )
        AuthMetadataRepository(self.store.root, self.store).cleanup_expired(
            now=self.clock(), limit=100
        )
        return delivered or revoked

    def _reserve_provider_start(
        self, connection: sqlite3.Connection, client: str, network: str
    ) -> None:
        box = self._box()
        now = self.clock()
        live = connection.execute(
            "SELECT DISTINCT key_id FROM auth_budgets WHERE expires_at>?",
            (now.isoformat(),),
        ).fetchall()
        if any(row["key_id"] not in box.key_ids for row in live):
            raise ModernAuthError("method_unavailable", 503)
        pending: list[tuple[str, str]] = []
        for scope, value, limit in (
            ("provider:client", client, 25),
            ("provider:network", network, 100),
        ):
            fingerprints = box.budget_fingerprints(value, scope)
            rows = connection.execute(
                "SELECT fingerprint,key_id,count FROM auth_budgets WHERE scope=? AND window_started_at>? AND expires_at>?",
                (scope, (now - timedelta(hours=1)).isoformat(), now.isoformat()),
            ).fetchall()
            if (
                sum(
                    row["count"]
                    for row in rows
                    if fingerprints.get(row["key_id"]) == row["fingerprint"]
                )
                >= limit
            ):
                raise ModernAuthError("rate_limited", 429)
            pending.append((scope, fingerprints[box.current_key_id]))
        for scope, fingerprint in pending:
            connection.execute(
                "INSERT INTO auth_budgets(scope,fingerprint,key_id,window_started_at,count,expires_at) VALUES(?,?,?,?,1,?) ON CONFLICT(scope,fingerprint,key_id,window_started_at) DO UPDATE SET count=count+1",
                (
                    scope,
                    fingerprint,
                    box.current_key_id,
                    now.isoformat(),
                    (now + timedelta(hours=24)).isoformat(),
                ),
            )
