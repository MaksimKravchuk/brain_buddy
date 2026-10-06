"""Strict wire contracts keep login results and sensitive proofs distinct."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.modern_auth import (
    AuthCompletion,
    EmailRequest,
    EmailVerifyRequest,
    ProviderCompleteRequest,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "signed_in"},
        {
            "status": "reset_ready",
            "recent_proof": "x" * 43,
            "expires_at": "2026-10-06T12:00:00Z",
        },
        {"status": "existing_account_required", "user": {"id": "other-owner"}},
        {"status": "provider_mailbox_verified"},
        {
            "status": "reauthenticated",
            "recent_proof": "x" * 43,
            "expires_at": "2026-10-06T12:00:00Z",
            "reset_grant": "x" * 43,
        },
    ],
)
def test_022_FR_014_completion_never_mixes_session_reset_and_confirmation(
    payload,
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(AuthCompletion).validate_python(payload)


def test_022_FR_001_signed_in_reuses_existing_me_contract() -> None:
    result = TypeAdapter(AuthCompletion).validate_python(
        {
            "status": "signed_in",
            "user": {"id": "user_a", "email": "a@example.com"},
            "deletion_cancelled": False,
        }
    )
    assert result.user.id == "user_a"
    assert result.user.feature_flags == {}


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "１２３４５６"])
def test_022_FR_008_email_code_requires_six_ascii_digits(code: str) -> None:
    with pytest.raises(ValidationError):
        EmailVerifyRequest(challenge_id="x" * 43, code=code, client_verifier="v" * 43)


def test_022_FR_021_request_repr_omits_credentials_and_proofs() -> None:
    payload = ProviderCompleteRequest(
        attempt_id="a" * 43,
        state="s" * 43,
        handoff_code="h" * 43,
        client_verifier="v" * 43,
    )
    assert "s" * 43 not in repr(payload)
    assert "h" * 43 not in repr(payload)
    assert "v" * 43 not in repr(payload)


def test_022_FR_021_optional_recent_proof_is_hidden_in_request_repr() -> None:
    payload = EmailRequest(
        email="a@example.com",
        purpose="change_email",
        client="web",
        client_challenge="c" * 43,
        recent_proof="p" * 43,
    )
    assert "p" * 43 not in repr(payload)


@pytest.mark.parametrize("purpose", ["admin", "signup_without_proof", "change_owner"])
def test_022_FR_014_email_purpose_cannot_select_unrecognized_authority(
    purpose: str,
) -> None:
    with pytest.raises(ValidationError):
        EmailRequest(
            email="a@example.com",
            purpose=purpose,
            client_challenge="x" * 43,
            client="web",
        )
