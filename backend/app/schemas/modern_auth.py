"""Additive authentication wire contracts; each result grants one purpose."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import EmailStr, Field

from .auth import MeResponse
from .common import StrictBaseModel

Client = Literal["web", "ios"]
Provider = Literal["google", "apple"]
EmailPurpose = Literal[
    "login", "recover", "verify_email", "change_email", "reauth", "provider_mailbox"
]
Action = Literal[
    "verify_email",
    "change_email",
    "link:google",
    "link:apple",
    "unlink:google",
    "unlink:apple",
    "password",
    "export",
    "delete",
]
RandomToken = Annotated[
    str, Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]{43}$")
]
Verifier = Annotated[
    str, Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$")
]
AccountID = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


class MethodsResponse(StrictBaseModel):
    password: bool = True
    google: bool
    apple: bool
    email: bool
    web_account_origin: str | None


class EmailRequest(StrictBaseModel):
    email: EmailStr
    purpose: EmailPurpose
    client_challenge: RandomToken = Field(repr=False)
    client: Client
    expected_account_id: AccountID | None = None
    action: Action | None = None
    recent_proof: RandomToken | None = Field(default=None, repr=False)
    provider_attempt_id: RandomToken | None = Field(default=None, repr=False)


class EmailResendRequest(StrictBaseModel):
    challenge_id: RandomToken = Field(repr=False)
    client_verifier: Verifier = Field(repr=False)


class EmailVerifyRequest(EmailResendRequest):
    code: Annotated[
        str, Field(pattern=r"^[0-9]{6}$", min_length=6, max_length=6, repr=False)
    ]
    recent_proof: RandomToken | None = Field(default=None, repr=False)


class ChallengeResponse(StrictBaseModel):
    challenge_id: str
    expires_at: datetime
    resend_at: datetime
    message: str = "If this address can be used, you will receive a code."


class ProviderStartRequest(StrictBaseModel):
    purpose: Literal["login", "link", "reauth"]
    client: Client
    client_challenge: RandomToken = Field(repr=False)
    action: Action | None = None
    expected_account_id: AccountID | None = None
    recent_proof: RandomToken | None = Field(default=None, repr=False)


class ProviderStartResponse(StrictBaseModel):
    attempt_id: str
    state: RandomToken = Field(repr=False)
    nonce: RandomToken = Field(repr=False)
    authorization_url: str | None = Field(repr=False)


class ProviderCompleteRequest(StrictBaseModel):
    attempt_id: RandomToken = Field(repr=False)
    state: RandomToken = Field(repr=False)
    handoff_code: RandomToken = Field(repr=False)
    client_verifier: Verifier = Field(repr=False)


class AppleNativeCompleteRequest(StrictBaseModel):
    attempt_id: RandomToken = Field(repr=False)
    state: RandomToken = Field(repr=False)
    authorization_code: Annotated[str, Field(min_length=1, max_length=4096, repr=False)]
    identity_token: Annotated[str, Field(min_length=1, max_length=16384, repr=False)]
    client_verifier: Verifier = Field(repr=False)


class PasswordConfirmRequest(StrictBaseModel):
    current_password: Annotated[str, Field(min_length=1, max_length=1024, repr=False)]
    action: Action
    expected_account_id: AccountID


class ResetRequest(StrictBaseModel):
    reset_grant: RandomToken = Field(repr=False)
    client_verifier: Verifier = Field(repr=False)
    new_password: Annotated[str, Field(min_length=1, max_length=1024, repr=False)]


class AccountActionRequest(StrictBaseModel):
    recent_proof: RandomToken = Field(repr=False)
    expected_account_id: AccountID


class AccountPasswordRequest(AccountActionRequest):
    new_password: Annotated[str, Field(min_length=1, max_length=1024, repr=False)]


class AppleNotificationRequest(StrictBaseModel):
    payload: Annotated[str, Field(min_length=1, max_length=16384, repr=False)]


class ConnectedMethod(StrictBaseModel):
    method: Literal["password", "email", "google", "apple"]
    state: Literal["active", "disabled"]
    usable: bool
    connected_at: datetime | None


class AccountMethodsResponse(StrictBaseModel):
    account_id: str
    email: str
    email_verified: bool
    email_delivery: Literal["available", "disabled", "unconfigured"]
    has_password: bool
    methods: list[ConnectedMethod]


class UnlinkResponse(StrictBaseModel):
    methods: AccountMethodsResponse
    signed_out: bool


class SignedInResult(StrictBaseModel):
    status: Literal["signed_in"] = "signed_in"
    user: MeResponse
    deletion_cancelled: bool = False


class LinkedResult(StrictBaseModel):
    status: Literal["linked"] = "linked"
    user: MeResponse


class VerifiedEmailResult(StrictBaseModel):
    status: Literal["verified_email", "changed_email"]
    user: MeResponse


class ResetReadyResult(StrictBaseModel):
    status: Literal["reset_ready"] = "reset_ready"
    reset_grant: RandomToken = Field(repr=False)
    expires_at: datetime


class ReauthenticatedResult(StrictBaseModel):
    status: Literal["reauthenticated"] = "reauthenticated"
    recent_proof: RandomToken = Field(repr=False)
    expires_at: datetime


class VerifyMailboxResult(ChallengeResponse):
    status: Literal["verify_mailbox"] = "verify_mailbox"


class ExistingAccountRequiredResult(StrictBaseModel):
    status: Literal["existing_account_required"] = "existing_account_required"
    message: str = (
        "Sign in to your existing account, then connect this method in Settings."
    )


AuthCompletion = Annotated[
    SignedInResult
    | LinkedResult
    | VerifiedEmailResult
    | ResetReadyResult
    | ReauthenticatedResult
    | VerifyMailboxResult
    | ExistingAccountRequiredResult,
    Field(discriminator="status"),
]
